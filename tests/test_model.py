import numpy as np
import pandas as pd
import pytest

from mmm import aggregate as agg
from mmm.model import CH, MMM, MMMConfig, adstock, build_model_frame, summarise


def frame(ds, fn=agg.weekly_to_monthly_apportioned):
    months = pd.DatetimeIndex(ds.sales_monthly.month_start)
    tv = agg.align_to_months(fn(ds.tv_weekly, "week_start", "spend"), months)
    return build_model_frame(ds.sales_monthly, tv, ds.digital_monthly, ds.email_monthly)


def test_adstock_geometric():
    assert adstock(np.array([1.0, 0, 0]), 0.5).tolist() == [1.0, 0.5, 0.25]


def test_coefficients_non_negative_and_intervals_ordered(ds):
    r = summarise(MMM(frame(ds), MMMConfig(n_boot=10)).bootstrap())
    for c in CH:
        assert r["channels"][c]["share"] >= 0
        assert r["channels"][c]["lo"] <= r["channels"][c]["hi"]
    assert sum(r["channels"][c]["share"] for c in CH) < 0.8


def test_bootstrap_is_deterministic(ds):
    a = summarise(MMM(frame(ds), MMMConfig(n_boot=8, seed=1)).bootstrap())
    b = summarise(MMM(frame(ds), MMMConfig(n_boot=8, seed=1)).bootstrap())
    assert a["realloc"] == b["realloc"]


def test_zero_reallocation_changes_nothing(ds):
    m = MMM(frame(ds), MMMConfig(n_boot=1))
    assert m.delta_sales(m.fit(), frac=0.0) == pytest.approx(0.0, abs=1e-6)


def test_reallocation_conserves_total_spend(ds):
    m = MMM(frame(ds), MMMConfig(n_boot=1))
    new, _ = m.realloc_spend()
    assert sum(v.sum() for v in new.values()) == pytest.approx(sum(m.total_spend.values()))


def test_fit_explains_monthly_sales(ds):
    m = MMM(frame(ds), MMMConfig(n_boot=1))
    fit = m.fit()
    F = np.column_stack([m._feature(m.rate[c], fit.decays[c], fit.scales[c]) for c in CH])
    pred = F @ np.array([fit.betas[c] for c in CH]) + m.Q @ fit.ctrl
    r2 = 1 - ((m.y - pred) ** 2).sum() / ((m.y - m.y.mean()) ** 2).sum()
    assert r2 > 0.9
