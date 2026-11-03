"""A deliberately small MMM: geometric adstock -> exponential saturation -> non-negative
linear response, plus trend/seasonality controls. Fit on per-day rates at monthly grain.

Estimation: grid search over each channel's adstock decay; for each grid point the
channel coefficients come from NNLS after partialling out the controls (Frisch-Waugh).
Uncertainty: residual bootstrap that re-runs the whole search each replicate, so decay
uncertainty is propagated into the intervals.

Known simplifications (stated in README): saturation scale is fixed at `sat_mult` x mean
adstocked spend (not estimated); adstock is monthly while the truth is daily.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from scipy.signal import lfilter

CH = ("tv", "digital", "email")


@dataclass
class MMMConfig:
    decay_grid: tuple = (0.0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.75)
    sat_mult: float = 1.0
    n_boot: int = 300
    seed: int = 0
    realloc_frac: float = 0.15


def adstock(x, decay):
    return lfilter([1.0], [1.0, -decay], x)


def controls(months: pd.DatetimeIndex) -> np.ndarray:
    n = len(months)
    t = np.arange(n) / 12.0
    m = (months.month.values - 0.5) / 12.0
    cols = [np.ones(n), t - t.mean()]
    for h in (1, 2):
        cols += [np.sin(2 * np.pi * h * m), np.cos(2 * np.pi * h * m)]
    return np.column_stack(cols)


@dataclass
class Fit:
    decays: dict
    betas: dict
    ctrl: np.ndarray
    scales: dict
    contrib_share: dict
    roi: dict


class MMM:
    """df columns: month, days, sales, tv, digital, email (monthly totals)."""

    def __init__(self, df: pd.DataFrame, cfg: MMMConfig | None = None):
        self.cfg = cfg or MMMConfig()
        self.df = df.reset_index(drop=True)
        self.days = self.df["days"].values.astype(float)
        self.months = pd.DatetimeIndex(self.df["month"])
        self.y = self.df["sales"].values / self.days
        self.rate = {c: self.df[c].values / self.days for c in CH}
        self.Q = controls(self.months)
        self.M = np.eye(len(self.y)) - self.Q @ np.linalg.pinv(self.Q)
        g = self.cfg.decay_grid
        self.scale = {c: [self.cfg.sat_mult * adstock(self.rate[c], d).mean() for d in g] for c in CH}
        self.feat = {c: [self._feature(self.rate[c], d, self.scale[c][i]) for i, d in enumerate(g)]
                     for c in CH}
        self.feat_res = {c: [self.M @ f for f in self.feat[c]] for c in CH}
        self.total_sales = self.df["sales"].sum()
        self.total_spend = {c: self.df[c].sum() for c in CH}

    @staticmethod
    def _feature(rate, decay, scale):
        return 1 - np.exp(-adstock(rate, decay) / scale)

    # ---- estimation ------------------------------------------------------
    def _search(self, y):
        yr = self.M @ y
        best = (np.inf, None, None)
        for idx in itertools.product(range(len(self.cfg.decay_grid)), repeat=3):
            A = np.column_stack([self.feat_res[c][i] for c, i in zip(CH, idx)])
            b, rn = nnls(A, yr)
            if rn < best[0]:
                best = (rn, idx, b)
        return best[1], best[2]

    def _make_fit(self, idx, b, y) -> Fit:
        F = np.column_stack([self.feat[c][i] for c, i in zip(CH, idx)])
        ctrl = np.linalg.lstsq(self.Q, y - F @ b, rcond=None)[0]
        contrib = {c: float((self.days * b[k] * F[:, k]).sum()) for k, c in enumerate(CH)}
        return Fit(
            decays={c: self.cfg.decay_grid[i] for c, i in zip(CH, idx)},
            betas=dict(zip(CH, b)), ctrl=ctrl,
            scales={c: self.scale[c][i] for c, i in zip(CH, idx)},
            contrib_share={c: contrib[c] / self.total_sales for c in CH},
            roi={c: contrib[c] / self.total_spend[c] for c in CH})

    def fit(self) -> Fit:
        idx, b = self._search(self.y)
        self._idx, self._fitted = idx, None
        return self._make_fit(idx, b, self.y)

    # ---- counterfactual: move spend ---------------------------------------
    def realloc_spend(self, frac: float | None = None) -> dict:
        frac = self.cfg.realloc_frac if frac is None else frac
        moved = frac * self.total_spend["tv"]
        w = self.total_spend["digital"] / (self.total_spend["digital"] + self.total_spend["email"])
        d, e = self.df["digital"].values, self.df["email"].values
        return {"tv": self.df["tv"].values * (1 - frac),
                "digital": d + moved * w * d / d.sum(),
                "email": e + moved * (1 - w) * e / e.sum()}, moved

    def delta_sales(self, fit: Fit, frac: float | None = None) -> float:
        new, _ = self.realloc_spend(frac)
        delta = 0.0
        for c in CH:
            f0 = self._feature(self.rate[c], fit.decays[c], fit.scales[c])
            f1 = self._feature(new[c] / self.days, fit.decays[c], fit.scales[c])
            delta += float((self.days * fit.betas[c] * (f1 - f0)).sum())
        return delta

    def marginal_roi(self, fit: Fit, channel: str, frac: float = 0.10) -> float:
        """Extra sales per extra $ when this channel's spend rises by `frac` (not the average ROI)."""
        r = self.rate[channel]
        f0 = self._feature(r, fit.decays[channel], fit.scales[channel])
        f1 = self._feature(r * (1 + frac), fit.decays[channel], fit.scales[channel])
        return float((self.days * fit.betas[channel] * (f1 - f0)).sum() / (frac * self.total_spend[channel]))

    # ---- uncertainty -----------------------------------------------------
    def bootstrap(self) -> dict:
        fit = self.fit()
        F = np.column_stack([self.feat[c][self._idx[k]] for k, c in enumerate(CH)])
        fitted = F @ np.array([fit.betas[c] for c in CH]) + self.Q @ fit.ctrl
        resid = self.y - fitted
        rng = np.random.default_rng(self.cfg.seed)
        shares, rois, deltas = [], [], []
        for _ in range(self.cfg.n_boot):
            ys = fitted + rng.choice(resid, size=len(resid), replace=True)
            idx, b = self._search(ys)
            f = self._make_fit(idx, b, ys)
            shares.append([f.contrib_share[c] for c in CH])
            rois.append([f.roi[c] for c in CH])
            deltas.append(self.delta_sales(f) / self.total_sales)
        return {"fit": fit, "shares": np.array(shares), "rois": np.array(rois),
                "delta_pct": np.array(deltas), "point_delta_pct": self.delta_sales(fit) / self.total_sales}


def summarise(res: dict, lo: float = 5, hi: float = 95) -> dict:
    fit = res["fit"]
    out = {"channels": {}}
    for k, c in enumerate(CH):
        out["channels"][c] = {
            "share": fit.contrib_share[c],
            "lo": float(np.percentile(res["shares"][:, k], lo)),
            "hi": float(np.percentile(res["shares"][:, k], hi)),
            "roi": fit.roi[c],
            "roi_lo": float(np.percentile(res["rois"][:, k], lo)),
            "roi_hi": float(np.percentile(res["rois"][:, k], hi)),
            "decay": fit.decays[c]}
    d = res["delta_pct"]
    out["realloc"] = {"point": res["point_delta_pct"], "median": float(np.median(d)),
                      "lo": float(np.percentile(d, lo)), "hi": float(np.percentile(d, hi)),
                      "p_positive": float((d > 0).mean())}
    return out


def build_model_frame(sales: pd.DataFrame, tv: pd.Series, digital: pd.DataFrame,
                      email: pd.DataFrame) -> pd.DataFrame:
    months = pd.DatetimeIndex(sales["month_start"])
    return pd.DataFrame({
        "month": months, "days": months.days_in_month.values, "sales": sales["sales"].values,
        "tv": tv.reindex(months).fillna(0.0).values,
        "digital": digital.set_index("month_start")["spend"].reindex(months).values,
        "email": email.set_index("month_start")["spend"].reindex(months).values})
