"""How does the calendar effect depend on the scenario?  uv run python run_sensitivity.py
Point fits only (no bootstrap) over N seeds per scenario; writes outputs/sensitivity.json."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from mmm import aggregate as agg
from mmm.generator import GenConfig, generate, true_realloc_effect
from mmm.model import CH, MMM, MMMConfig, build_model_frame

SEEDS = range(10)


def scenario(name, mk):
    err = {"naive": [], "correct": []}
    paired, delta = [], {"naive": [], "correct": []}
    truth = []
    for s in SEEDS:
        ds = generate(mk(s))
        months = pd.DatetimeIndex(ds.sales_monthly.month_start)
        truth.append(true_realloc_effect(ds)["delta_pct"])
        sh = {}
        for v, fn in (("naive", agg.weekly_to_monthly_naive), ("correct", agg.weekly_to_monthly_apportioned)):
            tv = agg.align_to_months(fn(ds.tv_weekly, "week_start", "spend"), months)
            m = MMM(build_model_frame(ds.sales_monthly, tv, ds.digital_monthly, ds.email_monthly), MMMConfig(n_boot=1))
            f = m.fit()
            sh[v] = np.array([f.contrib_share[c] for c in CH])
            err[v].append(sh[v] - np.array([ds.true_shares[c] for c in CH]))
            delta[v].append(m.delta_sales(f) / m.total_sales)
        paired.append(sh["naive"] - sh["correct"])
    p = np.array(paired)
    return {"scenario": name, "seeds": len(SEEDS),
            "bias_naive_pts": (np.mean(err["naive"], 0) * 100).round(2).tolist(),
            "bias_correct_pts": (np.mean(err["correct"], 0) * 100).round(2).tolist(),
            "paired_mean_pts": (p.mean(0) * 100).round(2).tolist(), "paired_sd_pts": (p.std(0) * 100).round(2).tolist(),
            "delta_naive_pct": round(float(np.mean(delta["naive"])) * 100, 3),
            "delta_correct_pct": round(float(np.mean(delta["correct"])) * 100, 3),
            "delta_true_pct": round(float(np.mean(truth)) * 100, 3)}


def sat_equal(s):
    c = GenConfig(seed=s)
    for k in c.truth:
        c.truth[k].sat_mult = 1.0
    return c


def low_noise(s):
    c = sat_equal(s)
    c.noise_frac = 0.003
    return c


def no_flighting(s):
    c = GenConfig(seed=s)
    c.tv_flighting = False
    return c


if __name__ == "__main__":
    out = [scenario("default (designed truth)", lambda s: GenConfig(seed=s)),
           scenario("TV not flighted (smooth weekly spend)", no_flighting),
           scenario("saturation scale matches the model", sat_equal),
           scenario("matched saturation + 0.3% noise", low_noise)]
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/sensitivity.json").write_text(json.dumps(out, indent=2))
    for o in out:
        print(o)
