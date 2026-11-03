import pandas as pd

from mmm import pipeline as pl
from mmm import validate as v


def good(data_dir):
    d = pl.load_refresh(data_dir)
    months = pd.DatetimeIndex(d["sales"]["month_start"])
    return d, months, pl.tv_versions(d["tv"], months)


def test_clean_refresh_passes(data_dir):
    d, _, ver = good(data_dir)
    rep = pl.validate_refresh(d, ver)
    assert rep.ok
    assert any(c.status == "WARN" for c in rep.checks)  # drift warning is expected


def test_tuesday_start_week_is_caught(data_dir):
    d, _, _ = good(data_dir)
    bad = d["tv"].copy()
    bad["week_start"] = bad["week_start"] + pd.Timedelta(days=1)
    assert not all(c.passed for c in v.check_weekly_grain(bad, "TV", "week_start"))


def test_week_gap_is_caught(data_dir):
    d, _, _ = good(data_dir)
    assert not all(c.passed for c in v.check_weekly_grain(d["tv"].drop(index=40), "TV", "week_start"))


def test_monthly_file_with_period_end_dates_is_caught(data_dir):
    d, _, _ = good(data_dir)
    bad = d["sales"].copy()
    bad["month_start"] = bad["month_start"] + pd.offsets.MonthEnd(0)
    assert not v.check_monthly_grain(bad, "Sales", "month_start")[0].passed


def test_445_style_fiscal_period_dates_are_caught(data_dir):
    d, _, _ = good(data_dir)
    bad = d["sales"].copy()
    bad["month_start"] = pd.date_range("2022-01-03", periods=len(bad), freq="28D")  # fiscal period starts
    assert not all(c.passed for c in v.check_monthly_grain(bad, "Sales", "month_start"))


def test_missing_month_is_caught(data_dir):
    d, _, _ = good(data_dir)
    assert not v.check_monthly_grain(d["digital"].drop(index=10), "Digital", "month_start")[1].passed


def test_mismatched_month_sets_are_caught(data_dir):
    d, _, _ = good(data_dir)
    c = v.check_months_match(("sales", d["sales"], "month_start"), ("digital", d["digital"].iloc[:-1], "month_start"))
    assert not c.passed


def test_short_tv_history_fails_coverage(data_dir):
    d, months, _ = good(data_dir)
    assert not v.check_coverage(d["tv"].iloc[5:], "week_start", months).passed


def test_duplicates_are_caught(data_dir):
    d, _, _ = good(data_dir)
    bad = pd.concat([d["tv"], d["tv"].iloc[[3]]])
    assert not v.check_schema(bad, "TV", ["week_start", "spend"])[1].passed


def test_failed_validation_blocks_pipeline(data_dir):
    d, months, ver = good(data_dir)
    d["tv"]["week_start"] = d["tv"]["week_start"] + pd.Timedelta(days=2)
    assert not pl.validate_refresh(d, ver).ok


def test_drift_check_flags_large_deviation():
    idx = pd.date_range("2024-01-01", periods=3, freq="MS")
    c = v.check_alignment_drift(pd.Series([110.0, 100, 100], idx), pd.Series([100.0, 100, 100], idx))
    assert not c.passed and c.severity == "warn"
