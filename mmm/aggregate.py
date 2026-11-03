"""Weekly (Mon-Sun) -> calendar-month aggregation, the wrong way and the right way."""
from __future__ import annotations

import pandas as pd


def _to_month(s: pd.Series) -> pd.Series:
    return s.dt.to_period("M").dt.to_timestamp()


def weekly_to_monthly_naive(weekly: pd.DataFrame, date_col: str, value_col: str,
                            anchor: str = "start") -> pd.Series:
    """THE BUG: assign the whole week to the month of its first (or last) day."""
    d = weekly[date_col]
    if anchor == "end":
        d = d + pd.Timedelta(days=6)
    return weekly.groupby(_to_month(d))[value_col].sum().rename("naive")


def weekly_to_monthly_apportioned(weekly: pd.DataFrame, date_col: str, value_col: str) -> pd.Series:
    """CORRECT: spread each week's spend evenly over its 7 days, then sum by calendar month."""
    days = weekly[date_col].repeat(7).reset_index(drop=True)
    offsets = pd.Series(list(range(7)) * len(weekly))
    daily = pd.DataFrame({"day": days + pd.to_timedelta(offsets, unit="D"),
                          "v": weekly[value_col].repeat(7).values / 7.0})
    return daily.groupby(_to_month(daily["day"]))["v"].sum().rename("apportioned")


def align_to_months(s: pd.Series, months: pd.DatetimeIndex) -> pd.Series:
    """Restrict to the modelling window (weeks spilling outside it are dropped)."""
    return s.reindex(months).fillna(0.0)
