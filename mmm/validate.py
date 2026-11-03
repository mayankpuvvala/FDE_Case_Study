"""Deterministic grain / calendar-alignment checks. Run on EVERY refresh, before any model fit.

Severity: "error" blocks the pipeline, "warn" is reported but does not block.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    severity: str = "error"

    @property
    def status(self) -> str:
        return "PASS" if self.passed else ("FAIL" if self.severity == "error" else "WARN")


class ValidationReport:
    def __init__(self, checks: list[Check]):
        self.checks = checks

    @property
    def ok(self) -> bool:
        return all(c.passed or c.severity != "error" for c in self.checks)

    def to_dicts(self) -> list[dict]:
        return [{**asdict(c), "status": c.status} for c in self.checks]

    def __str__(self) -> str:
        return "\n".join(f"[{c.status}] {c.name}: {c.detail}" for c in self.checks)


def _dates(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_datetime(df[col])


def check_schema(df, name, cols) -> list[Check]:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return [Check(f"{name}: schema", False, f"missing columns {missing}")]
    nulls = int(df[list(cols)].isna().sum().sum())
    dups = int(df[cols[0]].duplicated().sum())
    return [Check(f"{name}: schema", True, f"columns present {list(cols)}"),
            Check(f"{name}: no nulls/duplicates", nulls == 0 and dups == 0,
                  f"{nulls} null cells, {dups} duplicate dates")]


def check_weekly_grain(df, name, date_col, weekday: int = 0) -> list[Check]:
    d = _dates(df, date_col).sort_values()
    bad = d[d.dt.day_of_week != weekday]
    gaps = d.diff().dropna()
    off = gaps[gaps != pd.Timedelta(days=7)]
    return [Check(f"{name}: week starts {WEEKDAYS[weekday]}", bad.empty,
                  "all dates match" if bad.empty else f"{len(bad)} dates not {WEEKDAYS[weekday]}, e.g. {bad.iloc[0].date()}"),
            Check(f"{name}: contiguous 7-day spacing", off.empty,
                  "no gaps" if off.empty else f"{len(off)} irregular gaps, e.g. {off.iloc[0].days} days")]


def check_monthly_grain(df, name, date_col) -> list[Check]:
    d = _dates(df, date_col).sort_values()
    bad = d[d.dt.day != 1]
    expected = pd.date_range(d.min(), d.max(), freq="MS")
    missing = expected.difference(pd.DatetimeIndex(d))
    return [Check(f"{name}: dates are calendar-month starts", bad.empty,
                  "all on the 1st" if bad.empty else f"{len(bad)} dates not on the 1st, e.g. {bad.iloc[0].date()}"),
            Check(f"{name}: no missing months", len(missing) == 0,
                  "contiguous" if len(missing) == 0 else f"missing {[str(m.date()) for m in missing[:3]]}")]


def check_coverage(weekly: pd.DataFrame, week_col: str, month_starts: pd.DatetimeIndex) -> Check:
    w = _dates(weekly, week_col)
    first_need, last_need = month_starts.min(), month_starts.max() + pd.offsets.MonthEnd(0)
    ok = w.min() <= first_need and w.max() + pd.Timedelta(days=6) >= last_need
    return Check("TV weeks fully cover the modelled months", ok,
                 f"weeks span {w.min().date()}..{(w.max() + pd.Timedelta(days=6)).date()}; need {first_need.date()}..{last_need.date()}")


def check_conservation(weekly_total: float, apportioned: pd.Series, spill: float, tol: float = 1e-6) -> Check:
    """Apportioning must move spend between months, never create or destroy it."""
    err = abs(weekly_total - apportioned.sum() - spill) / max(weekly_total, 1e-12)
    return Check("Apportioning conserves total TV spend", err < tol, f"relative error {err:.2e}")


def check_alignment_drift(naive: pd.Series, correct: pd.Series, warn_pct: float = 2.0) -> Check:
    """How wrong would a week->month shortcut be on THIS data? Quantifies calendar risk."""
    pct = ((naive - correct).abs() / correct.replace(0, float("nan")) * 100).dropna()
    worst = pct.idxmax()
    return Check("Calendar drift: naive vs apportioned monthly TV", bool(pct.max() < warn_pct),
                 f"max monthly deviation {pct.max():.1f}% (worst {worst:%Y-%m}), median {pct.median():.1f}%; "
                 f"apportioning is mandatory above {warn_pct}%", severity="warn")


def check_months_match(*frames_cols) -> Check:
    sets = {n: set(_dates(df, c)) for n, df, c in frames_cols}
    ref_name, ref = next(iter(sets.items()))
    diff = {n: len(s ^ ref) for n, s in sets.items() if s != ref}
    return Check("Digital/email/sales cover identical months", not diff,
                 "identical" if not diff else f"month sets differ from {ref_name}: {diff}")


def run_all(tv_weekly: pd.DataFrame, digital: pd.DataFrame, email: pd.DataFrame, sales: pd.DataFrame,
            naive: pd.Series, correct: pd.Series, spill: float) -> ValidationReport:
    checks: list[Check] = []
    checks += check_schema(tv_weekly, "TV", ["week_start", "spend"])
    checks += check_schema(digital, "Digital", ["month_start", "spend"])
    checks += check_schema(email, "Email", ["month_start", "spend"])
    checks += check_schema(sales, "Sales", ["month_start", "sales"])
    if not all(c.passed for c in checks):
        return ValidationReport(checks)
    checks += check_weekly_grain(tv_weekly, "TV", "week_start")
    for n, df in (("Digital", digital), ("Email", email), ("Sales", sales)):
        checks += check_monthly_grain(df, n, "month_start")
    checks.append(check_months_match(("sales", sales, "month_start"), ("digital", digital, "month_start"),
                                     ("email", email, "month_start")))
    months = pd.DatetimeIndex(_dates(sales, "month_start"))
    checks.append(check_coverage(tv_weekly, "week_start", months))
    checks.append(check_conservation(float(tv_weekly["spend"].sum()), correct, spill))
    checks.append(check_alignment_drift(naive, correct))
    return ValidationReport(checks)
