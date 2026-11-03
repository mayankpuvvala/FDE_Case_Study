"""End-to-end run:  uv run python run_pipeline.py [--sweep 12] [--llm auto|mock|mock-flawed|anthropic]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mmm import pipeline as pl
from mmm.experiment import run_sweep
from mmm.generator import GenConfig, generate, true_realloc_effect, write_csvs
from mmm.model import CH, MMMConfig
from mmm.report import render
from mmm.spec_llm import get_llm, run_spec_check

ROOT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--boot", type=int, default=300)
    ap.add_argument("--sweep", type=int, default=0, help="number of re-simulated worlds (0 = skip)")
    ap.add_argument("--llm", default="auto")
    ap.add_argument("--scenario", choices=["flighted", "smooth"], default="flighted",
                    help="flighted: on/off TV pulses; smooth: steady weekly TV (calendar error bites harder)")
    ap.add_argument("--skip-gate", action="store_true", help="fit even if validation fails (not recommended)")
    a = ap.parse_args()

    smooth = a.scenario == "smooth"
    sfx = "_smooth" if smooth else ""
    data_dir = ROOT / "data" / "scenario_smooth" if smooth else ROOT / "data"
    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)

    print("1/6 generating synthetic vendor files ...")
    ds = generate(GenConfig(seed=a.seed, tv_flighting=not smooth))
    write_csvs(ds, data_dir)
    truth = true_realloc_effect(ds)

    print("2/6 loading refresh + validating grain/calendar ...")
    d = pl.load_refresh(data_dir)
    import pandas as pd
    months = pd.DatetimeIndex(d["sales"]["month_start"])
    versions = pl.tv_versions(d["tv"], months)
    report = pl.validate_refresh(d, versions)
    print(report)
    if not report.ok and not a.skip_gate:
        print("VALIDATION FAILED - model fit blocked.")
        return 1

    print("3/6 LLM spec reading + claim verification ...")
    llm = get_llm(a.llm)
    spec = run_spec_check(llm, ROOT / "data" / "vendor_specs", data_dir)
    print(f"   reader={spec['llm']} tally={spec['tally']}")

    print(f"4/6 fitting MMM on naive and apportioned TV ({a.boot} bootstrap fits each) ...")
    fits = pl.fit_versions(d, versions, MMMConfig(n_boot=a.boot, seed=a.seed))

    sweep = None
    if a.sweep:
        print(f"5/6 sweep over {a.sweep} simulated worlds ...")
        sweep = run_sweep(range(a.sweep), n_boot=80, tv_flighting=not smooth)

    print("6/6 writing outputs ...")
    verdict = pl.verdict(fits, truth["delta_pct"])
    spend = {c: float(ds.daily.loc[ds.window_mask(), f"spend_{c}"].sum()) for c in CH}
    win = ds.daily[ds.window_mask()]
    true_roi = {c: float(win[f"eff_{c}"].sum() / spend[c]) for c in CH}
    from mmm.generator import true_marginal_roi
    true_mroi = {c: true_marginal_roi(ds, c) for c in CH}
    res = {"scenario": a.scenario, "true_marginal_roi": true_mroi, "seed": a.seed, "n_boot": a.boot, "n_months": len(months), "fits": fits, "verdict": verdict,
           "true_shares": ds.true_shares, "true_roi": true_roi, "true_delta": truth["delta_pct"],
           "validation": report.to_dicts(), "spec_check": spec, "sweep": sweep,
           "naive_tv": versions["naive"], "correct_tv": versions["correct"]}
    # single-scenario page keeps its own name; report.html is the combined view of both scenarios
    (out_dir / ("report_smooth.html" if smooth else "report_flighted.html")).write_text(render(res), encoding="utf-8")
    ser = {k: v for k, v in res.items() if k not in ("naive_tv", "correct_tv")}
    (out_dir / f"results{sfx}.json").write_text(json.dumps(ser, indent=2, default=float), encoding="utf-8")

    from mmm.report_combined import write_combined
    if write_combined(out_dir):
        print(f"combined report (both scenarios): {out_dir / 'report.html'}")
    print(f"\nVERDICT: {verdict['call']} - {verdict['text']}")
    print(f"  median impact correct {verdict['median_correct']*100:+.2f}% | naive {verdict['median_naive']*100:+.2f}% | truth {verdict['truth_delta']*100:+.2f}%")
    print(f"  report: {out_dir / f'report{sfx}.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
