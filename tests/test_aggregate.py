import pandas as pd
import pytest

from mmm.aggregate import weekly_to_monthly_apportioned as correct
from mmm.aggregate import weekly_to_monthly_naive as naive


def weekly(dates, vals):
    return pd.DataFrame({"w": pd.to_datetime(dates), "v": vals})


def test_straddling_week_is_split_by_days():
    # Mon 2024-01-29 .. Sun 2024-02-04: 3 days in Jan (29,30,31), 4 in Feb
    out = correct(weekly(["2024-01-29"], [700.0]), "w", "v")
    assert out[pd.Timestamp("2024-01-01")] == pytest.approx(300.0)
    assert out[pd.Timestamp("2024-02-01")] == pytest.approx(400.0)


def test_naive_puts_whole_week_in_one_month():
    df = weekly(["2024-01-29"], [700.0])
    assert naive(df, "w", "v")[pd.Timestamp("2024-01-01")] == 700.0
    assert naive(df, "w", "v", anchor="end")[pd.Timestamp("2024-02-01")] == 700.0


def test_apportioning_conserves_total_incl_leap_february():
    dates = pd.date_range("2023-12-25", periods=20, freq="W-MON")
    df = weekly(dates, list(range(100, 120)))
    assert correct(df, "w", "v").sum() == pytest.approx(df["v"].sum())


def test_aligned_weeks_give_identical_results():
    df = weekly(["2024-01-08"], [70.0])  # week fully inside one month
    assert naive(df, "w", "v").iloc[0] == pytest.approx(correct(df, "w", "v").iloc[0])


def test_generated_data_really_differs(ds):
    n = naive(ds.tv_weekly, "week_start", "spend")
    c = correct(ds.tv_weekly, "week_start", "spend")
    assert ((n - c).abs() / c).median() > 0.02
