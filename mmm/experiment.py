"""Many-seed experiment: is the calendar error a systematic bias, or just noise, and how
often would each version have told the client to make the shift?"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import aggregate as agg
from .generator import GenConfig, generate, true_realloc_effect
from .model import CH, MMM, MMMConfig, build_model_frame, summarise


def run_sweep(seeds: range, n_boot: int = 100, tv_flighting: bool = True) -> dict:
    rows = []
    for s in seeds:
        ds = generate(GenConfig(seed=s, tv_flighting=tv_flighting))
        months = pd.DatetimeIndex(ds.sales_monthly.month_start)
        row = {"seed": s, "true_delta": true_realloc_effect(ds)["delta_pct"],
               "true": [ds.true_shares[c] for c in CH]}
        for name, fn in (("naive", agg.weekly_to_monthly_naive), ("correct", agg.weekly_to_monthly_apportioned)):
            tv = agg.align_to_months(fn(ds.tv_weekly, "week_start", "spend"), months)
            m = MMM(build_model_frame(ds.sales_monthly, tv, ds.digital_monthly, ds.email_monthly),
                    MMMConfig(n_boot=n_boot, seed=s))
            r = summarise(m.bootstrap())
            row[name] = {"share": [r["channels"][c]["share"] for c in CH],
                         "covered": [r["channels"][c]["lo"] <= ds.true_shares[c] <= r["channels"][c]["hi"] for c in CH],
                         "width": [r["channels"][c]["hi"] - r["channels"][c]["lo"] for c in CH],
                         "delta": r["realloc"]["median"], "p_pos": r["realloc"]["p_positive"],
                         "excl0_pos": r["realloc"]["lo"] > 0}
        rows.append(row)
    truth = np.array([r["true"] for r in rows])
    out = {"n_seeds": len(rows), "channels": {}, "realloc": {}}
    for k, c in enumerate(CH):
        d = {}
        for name in ("naive", "correct"):
            est = np.array([r[name]["share"][k] for r in rows])
            d[name] = {"bias": float((est - truth[:, k]).mean()), "rmse": float(np.sqrt(((est - truth[:, k]) ** 2).mean())),
                       "coverage90": float(np.mean([r[name]["covered"][k] for r in rows])),
                       "mean_width": float(np.mean([r[name]["width"][k] for r in rows]))}
        paired = np.array([r["naive"]["share"][k] - r["correct"]["share"][k] for r in rows])
        d["paired_diff_mean"], d["paired_diff_sd"] = float(paired.mean()), float(paired.std())
        out["channels"][c] = d
    for name in ("naive", "correct"):
        out["realloc"][name] = {"mean_median_delta": float(np.mean([r[name]["delta"] for r in rows])),
                                "mean_p_positive": float(np.mean([r[name]["p_pos"] for r in rows])),
                                "pct_seeds_confidently_positive": float(np.mean([r[name]["excl0_pos"] for r in rows]))}
    out["realloc"]["true_delta_mean"] = float(np.mean([r["true_delta"] for r in rows]))
    out["realloc"]["true_delta_sign_negative_share"] = float(np.mean([r["true_delta"] < 0 for r in rows]))
    return out
