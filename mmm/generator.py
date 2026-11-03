"""Synthetic data generator with a KNOWN true effect per channel.

The truth lives at DAILY grain (that is how the world works). We then publish it
the way vendors do: TV weekly (Mon-Sun), digital/email monthly, sales monthly.
Because the daily process is known, we can score any model against the truth,
including the "what if we moved 15% of TV into digital/email" counterfactual.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

CHANNELS = ("tv", "digital", "email")


@dataclass
class ChannelTruth:
    share: float      # true share of total sales caused by the channel
    decay: float      # DAILY adstock decay
    sat_mult: float   # saturation scale = sat_mult * mean adstocked spend


@dataclass
class GenConfig:
    seed: int = 7
    first_monday: str = "2021-12-27"      # vendor weeks must fully cover the window
    last_sunday: str = "2026-01-04"
    window_start: str = "2022-01-01"      # 48 modelled calendar months
    window_end: str = "2025-12-31"
    base_daily_sales: float = 820.0       # $k / day
    trend_per_year: float = 0.04
    season_amp: float = 0.10
    noise_frac: float = 0.02              # monthly sales noise, share of level
    tv_weekly_mean: float = 480.0         # $k / week  (~$25M / yr)
    digital_monthly_mean: float = 1650.0  # $k / month (~$20M / yr)
    email_monthly_mean: float = 250.0     # $k / month (~$3M / yr)
    tv_flighting: bool = True             # on/off pulses -> weeks differ a lot
    truth: dict = field(default_factory=lambda: {
        "tv": ChannelTruth(share=0.18, decay=0.95, sat_mult=1.5),
        "digital": ChannelTruth(share=0.14, decay=0.85, sat_mult=0.8),
        "email": ChannelTruth(share=0.06, decay=0.70, sat_mult=0.6),
    })


@dataclass
class Dataset:
    cfg: GenConfig
    tv_weekly: pd.DataFrame        # week_start (Monday), spend
    digital_monthly: pd.DataFrame  # month_start, spend
    email_monthly: pd.DataFrame
    sales_monthly: pd.DataFrame    # month_start, sales
    daily: pd.DataFrame            # latent truth (never shown to the model)
    betas: dict
    scales: dict
    true_shares: dict              # realised share of window sales per channel

    def window_mask(self) -> pd.Series:
        d = self.daily.index
        return pd.Series((d >= self.cfg.window_start) & (d <= self.cfg.window_end), index=d)


def _adstock(x: np.ndarray, decay: float) -> np.ndarray:
    return lfilter([1.0], [1.0, -decay], x)


def _flighted_weeks(rng, n: int, mean: float, flighting: bool) -> np.ndarray:
    if not flighting:
        w = rng.lognormal(0, 0.15, n)
    else:
        levels = np.array([0.15, 0.5, 1.0, 1.6, 2.3])
        out: list[float] = []
        while len(out) < n:
            block = int(rng.integers(2, 5))
            lvl = rng.choice(levels)
            out += [lvl * rng.lognormal(0, 0.15)] * block
        w = np.array(out[:n])
    return w * mean / w.mean()


def _monthly_budget(rng, months: pd.DatetimeIndex, mean: float) -> np.ndarray:
    season = 1 + 0.04 * np.sin(2 * np.pi * (months.month.values - 3) / 12)
    v = season * rng.lognormal(0, 0.35, len(months))
    return v * mean / v.mean()


def _effects(daily_spend: dict, betas: dict, scales: dict, truth: dict) -> dict:
    return {c: betas[c] * (1 - np.exp(-_adstock(daily_spend[c], truth[c].decay) / scales[c]))
            for c in CHANNELS}


def generate(cfg: GenConfig | None = None) -> Dataset:
    cfg = cfg or GenConfig()
    rng = np.random.default_rng(cfg.seed)
    days = pd.date_range(cfg.first_monday, cfg.last_sunday, freq="D")
    weeks = pd.date_range(cfg.first_monday, cfg.last_sunday, freq="W-MON")
    months = pd.date_range(cfg.window_start, cfg.window_end, freq="MS")
    in_win = (days >= cfg.window_start) & (days <= cfg.window_end)

    # --- spend: weekly TV, monthly digital / email -> daily (even spread) -----
    tv_w = _flighted_weeks(rng, len(weeks), cfg.tv_weekly_mean, cfg.tv_flighting)
    dig_m = _monthly_budget(rng, months, cfg.digital_monthly_mean)
    em_m = _monthly_budget(rng, months, cfg.email_monthly_mean)

    tv_d = np.repeat(tv_w / 7.0, 7)[: len(days)]
    dim = months.days_in_month.values
    month_idx = pd.Series(range(len(months)), index=months)
    dmon = days.to_period("M").to_timestamp()
    dig_d = np.zeros(len(days))
    em_d = np.zeros(len(days))
    for i, d in enumerate(dmon):
        if d in month_idx.index:
            k = month_idx[d]
            dig_d[i] = dig_m[k] / dim[k]
            em_d[i] = em_m[k] / dim[k]
    spend = {"tv": tv_d, "digital": dig_d, "email": em_d}

    # --- baseline (trend + seasonality), then calibrate betas to hit true shares
    t = np.arange(len(days)) / 365.25
    doy = days.dayofyear.values
    base = cfg.base_daily_sales * (1 + cfg.trend_per_year * t) * (
        1 + cfg.season_amp * np.sin(2 * np.pi * (doy - 30) / 365.25)
        + 0.04 * np.cos(4 * np.pi * doy / 365.25))
    scales, sat = {}, {}
    for c in CHANNELS:
        ad = _adstock(spend[c], cfg.truth[c].decay)
        scales[c] = cfg.truth[c].sat_mult * ad[in_win].mean()
        sat[c] = 1 - np.exp(-ad / scales[c])
    tot_share = sum(cfg.truth[c].share for c in CHANNELS)
    betas = {c: cfg.truth[c].share / (1 - tot_share) * base[in_win].sum() / sat[c][in_win].sum()
             for c in CHANNELS}
    eff = _effects(spend, betas, scales, cfg.truth)

    daily = pd.DataFrame({"base": base, **{f"spend_{c}": spend[c] for c in CHANNELS},
                          **{f"eff_{c}": eff[c] for c in CHANNELS}}, index=days)
    daily["sales"] = daily["base"] + sum(daily[f"eff_{c}"] for c in CHANNELS)

    win = daily[in_win]
    msales = win["sales"].groupby(win.index.to_period("M").to_timestamp()).sum()
    msales = msales * (1 + rng.normal(0, cfg.noise_frac, len(msales)))
    true_shares = {c: float(win[f"eff_{c}"].sum() / msales.sum()) for c in CHANNELS}

    return Dataset(
        cfg=cfg,
        tv_weekly=pd.DataFrame({"week_start": weeks, "spend": tv_w}),
        digital_monthly=pd.DataFrame({"month_start": months, "spend": dig_m}),
        email_monthly=pd.DataFrame({"month_start": months, "spend": em_m}),
        sales_monthly=pd.DataFrame({"month_start": msales.index, "sales": msales.values}),
        daily=daily, betas=betas, scales=scales, true_shares=true_shares)


def true_realloc_effect(ds: Dataset, frac: float = 0.15) -> dict:
    """Ground-truth effect of moving `frac` of TV $ into digital+email (split pro-rata
    to their current spend), evaluated on the true daily process."""
    cfg, d = ds.cfg, ds.daily
    win = ds.window_mask().values
    sp = {c: d[f"spend_{c}"].values.copy() for c in CHANNELS}
    moved = frac * sp["tv"][win].sum()
    dig_tot, em_tot = sp["digital"].sum(), sp["email"].sum()
    w_dig = dig_tot / (dig_tot + em_tot)
    new = dict(sp)
    new["tv"] = sp["tv"] * (1 - frac)
    new["digital"] = sp["digital"] + moved * w_dig * sp["digital"] / dig_tot
    new["email"] = sp["email"] + moved * (1 - w_dig) * sp["email"] / em_tot
    e0 = _effects(sp, ds.betas, ds.scales, cfg.truth)
    e1 = _effects(new, ds.betas, ds.scales, cfg.truth)
    delta = sum(e1[c][win].sum() - e0[c][win].sum() for c in CHANNELS)
    total = d["sales"].values[win].sum()
    return {"delta_sales": float(delta), "delta_pct": float(delta / total), "moved_spend": float(moved)}


def true_marginal_roi(ds: Dataset, channel: str, frac: float = 0.10) -> float:
    """True extra sales per extra $ when `channel` spend is raised by `frac` (window days only)."""
    win = ds.window_mask().values
    sp = {c: ds.daily[f"spend_{c}"].values for c in CHANNELS}
    up = dict(sp)
    up[channel] = sp[channel] * (1 + frac)
    e0 = _effects(sp, ds.betas, ds.scales, ds.cfg.truth)[channel]
    e1 = _effects(up, ds.betas, ds.scales, ds.cfg.truth)[channel]
    return float((e1[win].sum() - e0[win].sum()) / (frac * sp[channel][win].sum()))


def write_csvs(ds: Dataset, out_dir: str | Path) -> dict:
    """Write files in the shape the vendors would send them."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "tv_media_weekly": out / "tv_media_weekly.csv",
        "digital_monthly": out / "digital_monthly.csv",
        "email_monthly": out / "email_monthly.csv",
        "sales_monthly": out / "sales_monthly.csv",
    }
    ds.tv_weekly.rename(columns={"week_start": "week_commencing", "spend": "spend_usd_k"}).to_csv(
        paths["tv_media_weekly"], index=False, date_format="%Y-%m-%d")
    ds.digital_monthly.rename(columns={"month_start": "month", "spend": "spend_usd_k"}).to_csv(
        paths["digital_monthly"], index=False, date_format="%Y-%m-%d")
    ds.email_monthly.rename(columns={"month_start": "month", "spend": "spend_usd_k"}).to_csv(
        paths["email_monthly"], index=False, date_format="%Y-%m-%d")
    ds.sales_monthly.rename(columns={"month_start": "month", "sales": "sales_usd_k"}).to_csv(
        paths["sales_monthly"], index=False, date_format="%Y-%m-%d")
    return paths
