import pytest

from mmm.generator import CHANNELS, GenConfig, generate, true_realloc_effect


def test_true_shares_match_config(ds):
    for c in CHANNELS:
        assert ds.true_shares[c] == pytest.approx(ds.cfg.truth[c].share, rel=0.05)


def test_grain_of_published_files(ds):
    assert (ds.tv_weekly.week_start.dt.day_of_week == 0).all()
    assert (ds.digital_monthly.month_start.dt.day == 1).all()
    assert len(ds.sales_monthly) == 48  # at least two years


def test_seed_is_reproducible():
    a, b = generate(GenConfig(seed=1)), generate(GenConfig(seed=1))
    assert a.sales_monthly.equals(b.sales_monthly)


def test_truth_counterfactual_zero_move_is_zero(ds):
    assert true_realloc_effect(ds, frac=0.0)["delta_sales"] == pytest.approx(0.0, abs=1e-9)
