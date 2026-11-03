"""Refresh pipeline: load vendor files -> validate (gate) -> aggregate two ways -> fit both."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import aggregate as agg
from . import validate as val
from .model import CH, MMM, MMMConfig, build_model_frame, summarise


def load_refresh(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    p = Path(data_dir)
    rd = lambda f, c, v, nc, nv: pd.read_csv(p / f, parse_dates=[c]).rename(columns={c: nc, v: nv})
    return {
        "tv": rd("tv_media_weekly.csv", "week_commencing", "spend_usd_k", "week_start", "spend"),
        "digital": rd("digital_monthly.csv", "month", "spend_usd_k", "month_start", "spend"),
        "email": rd("email_monthly.csv", "month", "spend_usd_k", "month_start", "spend"),
        "sales": rd("sales_monthly.csv", "month", "sales_usd_k", "month_start", "sales"),
    }


def tv_versions(tv: pd.DataFrame, months: pd.DatetimeIndex) -> dict:
    """Naive and apportioned monthly TV, plus the spend that spills outside the window."""
    full = agg.weekly_to_monthly_apportioned(tv, "week_start", "spend")
    naive = agg.align_to_months(agg.weekly_to_monthly_naive(tv, "week_start", "spend"), months)
    correct = agg.align_to_months(full, months)
    return {"naive": naive, "correct": correct, "spill": float(full.drop(months, errors="ignore").sum())}


def validate_refresh(d: dict, v: dict) -> val.ValidationReport:
    return val.run_all(d["tv"], d["digital"], d["email"], d["sales"], v["naive"], v["correct"], v["spill"])


def fit_versions(d: dict, v: dict, cfg: MMMConfig) -> dict:
    out = {}
    for name in ("naive", "correct"):
        frame = build_model_frame(d["sales"], v[name], d["digital"], d["email"])
        m = MMM(frame, cfg)
        res = m.bootstrap()
        out[name] = summarise(res)
        out[name]["marginal_roi"] = {c: m.marginal_roi(res["fit"], c) for c in CH}
    return out


def verdict(fits: dict, truth_delta: float | None = None) -> dict:
    """Plain-language call on the 15% TV -> digital/email shift, from the CORRECT-calendar fit."""
    r, n = fits["correct"]["realloc"], fits["naive"]["realloc"]
    if r["lo"] > 0:
        call, text = "HOLDS", "The shift is expected to add sales, and the interval excludes zero."
    elif r["hi"] < 0:
        call, text = "DOES NOT HOLD", "The shift is expected to LOSE sales, and the interval excludes zero."
    else:
        call = "NOT SUPPORTED"
        text = ("The interval for the sales impact spans zero, so the data cannot show the shift pays off "
                "(the point estimate is " + ("negative" if r["median"] < 0 else "positive") + ").")
    return {"call": call, "text": text, "p_positive_correct": r["p_positive"],
            "p_positive_naive": n["p_positive"], "median_correct": r["median"], "median_naive": n["median"],
            "truth_delta": truth_delta,
            "agree": (n["lo"] > 0) == (r["lo"] > 0) and (n["hi"] < 0) == (r["hi"] < 0)}
