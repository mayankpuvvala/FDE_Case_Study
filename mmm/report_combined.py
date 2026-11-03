"""Presentation-grade combined report: both TV scenarios on one page, CSS-only tabs, no JavaScript."""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from . import aggregate as agg
from .generator import GenConfig, generate
from .model import CH
from .report import NAMES, drift_chart, interval_chart, legend

CSS = """
:root{--bg:#f4f8f5;--surface:#fff;--fg:#1F2A24;--mut:#5F6B64;--line:#DDE5E0;--g:#1B7F4B;--gd:#13633A;--tint:#E8F3EC;
--naive:#8A948E;--ok:#1B7F4B;--truth:#1F2A24;--bad:#B42318;--warn:#9A6700;--good:#1B7F4B;--shadow:0 1px 2px rgba(20,40,30,.06),0 6px 20px rgba(20,40,30,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e1612;--surface:#15201a;--fg:#e7efe9;--mut:#9fb0a5;--line:#26362d;--g:#3fb877;--gd:#2e9a60;--tint:#183226;--naive:#8d9a92;--ok:#3fb877;--truth:#e7efe9;--bad:#ff7b72;--warn:#e3b341;--good:#3fb877;--shadow:none}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 Inter,system-ui,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:0 20px}
header.hero{background:linear-gradient(135deg,#13633A 0%,#1B7F4B 55%,#2E9A60 100%);color:#fff;padding:44px 0 90px}
.hero h1{font-size:34px;line-height:1.15;margin:0 0 10px;letter-spacing:-.5px;max-width:780px}.hero p{margin:0;max-width:740px;opacity:.92;font-size:16px}
.eyebrow{text-transform:uppercase;letter-spacing:1.5px;font-size:12px;font-weight:700;opacity:.8;margin-bottom:10px}
.chips{margin-top:18px;display:flex;flex-wrap:wrap;gap:8px}.chip{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:99px;padding:3px 12px;font-size:12.5px}
.pull{margin-top:-62px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:20px;margin:0 0 16px}
.card h3{margin:0 0 2px;font-size:17px}.sc-tag{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--g);background:var(--tint);border-radius:6px;padding:2px 8px;margin-bottom:8px}
.trio{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0 10px}.trio>div{background:var(--tint);border-radius:10px;padding:10px 12px}
.trio .l{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.6px}.trio .n{font-size:22px;font-weight:800;letter-spacing:-.4px}.trio .s{font-size:12px;color:var(--mut)}
.neg{color:var(--bad)}.pos{color:var(--g)}
h2{font-size:24px;letter-spacing:-.3px;margin:44px 0 6px}h2 .n{color:var(--g);margin-right:8px}.lede{color:var(--mut);margin:0 0 16px;max-width:760px}
.takeaways{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.tk{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--g);border-radius:12px;padding:16px;box-shadow:var(--shadow)}
.tk b{display:block;margin-bottom:4px}.tk span{color:var(--mut);font-size:14px}
.tabs>input{display:none}.tab-labels{display:flex;gap:8px;margin:0 0 16px;flex-wrap:wrap}
.tab-labels label{cursor:pointer;padding:9px 18px;border-radius:99px;border:1px solid var(--line);background:var(--surface);font-weight:600;font-size:14px;color:var(--mut)}
#tB:checked~.tab-labels label[for=tB],#tA:checked~.tab-labels label[for=tA]{background:var(--g);border-color:var(--g);color:#fff}
.panels section{display:none}#tB:checked~.panels #pB,#tA:checked~.panels #pA{display:block}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 16px}.kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--shadow)}
.kpi .k{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.6px}.kpi .v{font-size:26px;font-weight:800;letter-spacing:-.5px}.kpi .s{font-size:12px;color:var(--mut)}
.banner{border-radius:12px;padding:14px 18px;margin:0 0 16px;border:1px solid var(--line);background:var(--tint)}.banner b{font-size:17px}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.PASS,.VERIFIED{color:var(--good)}.FAIL,.REJECTED_UNGROUNDED,.CONTRADICTED_BY_DATA{color:var(--bad)}.WARN,.ADVISORY{color:var(--warn)}
svg{width:100%;height:auto;display:block}svg text{fill:var(--fg);font:12px Inter,system-ui,sans-serif}svg .m{fill:var(--mut)}
.legend span{margin-right:16px;white-space:nowrap}.sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.small{font-size:12.5px;color:var(--mut)}.scroll{overflow-x:auto}details{background:var(--surface);border:1px solid var(--line);border-radius:12px;margin:0 0 12px;box-shadow:var(--shadow)}
summary{cursor:pointer;padding:14px 18px;font-weight:700}details>div{padding:0 18px 16px}ul{margin:6px 0 6px 18px;padding:0}
footer{margin:48px 0 40px;color:var(--mut);font-size:13px}
@media(max-width:760px){.two,.takeaways,.kpis{grid-template-columns:1fr 1fr}.hero h1{font-size:26px}}@media(max-width:520px){.two,.takeaways,.kpis{grid-template-columns:1fr}}
"""


def _sgn(x, d=2):
    return f"<span class='{'neg' if x < 0 else 'pos'}'>{x * 100:+.{d}f}%</span>"


def _panel(res, drift_n, drift_c, label):
    fits, sw, v = res["fits"], res["sweep"], res["verdict"]
    rn, rc = fits["naive"]["realloc"], fits["correct"]["realloc"]
    rows = [(NAMES[c], res["true_shares"][c],
             (fits["naive"]["channels"][c]["share"], fits["naive"]["channels"][c]["lo"], fits["naive"]["channels"][c]["hi"]),
             (fits["correct"]["channels"][c]["share"], fits["correct"]["channels"][c]["lo"], fits["correct"]["channels"][c]["hi"])) for c in CH]
    d_chart = interval_chart([("15% TV → digital + email", res["true_delta"], (rn["median"], rn["lo"], rn["hi"]), (rc["median"], rc["lo"], rc["hi"]))],
                             -0.04, 0.03, [-0.04, -0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03], lambda t: f"{t*100:+.1f}%", zero=True)
    pct = ((drift_n - drift_c) / drift_c.replace(0, float("nan")) * 100).abs().dropna()
    cn, cr = sw["realloc"]["naive"], sw["realloc"]["correct"]
    roi = "".join(
        f"<tr><td><b>{NAMES[c]}</b></td><td class='n'>${res['true_roi'][c]:.1f}</td><td class='n'>${fits['naive']['channels'][c]['roi']:.1f}</td><td class='n'>${fits['correct']['channels'][c]['roi']:.1f}</td>"
        f"<td class='n'>${res['true_marginal_roi'][c]:.2f}</td><td class='n'>${fits['naive']['marginal_roi'][c]:.2f}</td><td class='n'>${fits['correct']['marginal_roi'][c]:.2f}</td></tr>" for c in CH)
    srows = "".join(
        f"<tr><td><b>{NAMES[c]}</b></td><td class='n'>{sw['channels'][c]['naive']['bias']*100:+.1f}</td><td class='n'>{sw['channels'][c]['correct']['bias']*100:+.1f}</td>"
        f"<td class='n'>{sw['channels'][c]['paired_diff_sd']*100:.1f}</td><td class='n'>{sw['channels'][c]['naive']['coverage90']*100:.0f}% / {sw['channels'][c]['correct']['coverage90']*100:.0f}%</td></tr>" for c in CH)
    return f"""
<div class="banner"><b>{label}: {html.escape(v['call'])}</b><br>Naive calendar says the shift moves sales {_sgn(rn['median'])} ({rn['p_positive']*100:.0f}% chance it helps). Correct calendar says {_sgn(rc['median'])} ({rc['p_positive']*100:.0f}%). Truth: {_sgn(res['true_delta'])}.</div>
<div class="kpis">
 <div class="kpi"><div class="k">True effect of shift</div><div class="v">{_sgn(res['true_delta'])}</div><div class="s">answer key</div></div>
 <div class="kpi"><div class="k">Naive calendar</div><div class="v">{_sgn(rn['median'])}</div><div class="s">P(helps) {rn['p_positive']*100:.0f}%</div></div>
 <div class="kpi"><div class="k">Correct calendar</div><div class="v">{_sgn(rc['median'])}</div><div class="s">P(helps) {rc['p_positive']*100:.0f}%</div></div>
 <div class="kpi"><div class="k">Confident gain, {sw['n_seeds']} worlds</div><div class="v">{cn['pct_seeds_confidently_positive']*100:.0f}% vs {cr['pct_seeds_confidently_positive']*100:.0f}%</div><div class="s">naive vs correct</div></div>
</div>
<div class="card"><h3>Sales impact of moving 15% of TV</h3><p class="small">Whiskers are 90% bootstrap intervals; the vertical line is zero change.</p>{d_chart}{legend()}</div>
<div class="card"><h3>Who gets the credit? Channel contribution to sales</h3>{interval_chart(rows, 0, 0.40, [0, .1, .2, .3, .4], lambda t: f"{t*100:.0f}%")}{legend()}</div>
<div class="card scroll"><h3>Return per dollar</h3><p class="small">Average ROI says what a channel earned. Marginal ROI (spend +10%) says what the <i>next</i> dollar earns, and that decides whether moving money helps.</p>
<table><tr><th>Channel</th><th class="n">Avg ROI truth</th><th class="n">Naive</th><th class="n">Correct</th><th class="n">Marginal truth</th><th class="n">Naive</th><th class="n">Correct</th></tr>{roi}</table></div>
<div class="card"><h3>How wrong is the naive monthly TV series?</h3><p class="small">Each bar is a month: naive minus correct as % of correct. Median absolute deviation <b>{pct.median():.1f}%</b>; total spend is identical, only timing moves.</p>{drift_chart(drift_n, drift_c)}</div>
<div class="card scroll"><h3>Is it a systematic bias? {sw['n_seeds']} re-simulated worlds</h3>
<table><tr><th>Channel</th><th class="n">Bias naive (pts)</th><th class="n">Bias correct (pts)</th><th class="n">SD naive − correct (pts)</th><th class="n">90% CI covers truth (naive / correct)</th></tr>{srows}</table>
<p class="small">True effect of the shift was negative in {sw['realloc']['true_delta_sign_negative_share']*100:.0f}% of worlds. Mean modelled impact: naive {sw['realloc']['naive']['mean_median_delta']*100:+.2f}%, correct {sw['realloc']['correct']['mean_median_delta']*100:+.2f}%.</p></div>"""


def render_combined(fl: dict, sm: dict, drifts: dict) -> str:
    ssw = sm["sweep"]["realloc"]

    def trio(res):
        n, c = res["fits"]["naive"]["realloc"], res["fits"]["correct"]["realloc"]
        return (f"<div class='trio'><div><div class='l'>Naive</div><div class='n'>{_sgn(n['median'])}</div><div class='s'>{n['p_positive']*100:.0f}% chance it helps</div></div>"
                f"<div><div class='l'>Correct</div><div class='n'>{_sgn(c['median'])}</div><div class='s'>{c['p_positive']*100:.0f}% chance it helps</div></div>"
                f"<div><div class='l'>Truth</div><div class='n'>{_sgn(res['true_delta'])}</div><div class='s'>answer key</div></div></div>")
    checks = "".join(f"<tr><td class='{c['status']}'><b>{c['status']}</b></td><td>{html.escape(c['name'])}</td><td>{html.escape(c['detail'])}</td></tr>" for c in fl["validation"])
    vr = "".join(f"<tr><td>{html.escape(x['source'])}</td><td>{html.escape(x['field'])} = {html.escape(x['value'])}</td><td class='small'>“{html.escape(x['quote'])}”</td>"
                 f"<td>{'yes' if x['grounded'] else 'NO'}</td><td>{html.escape(x['detail'])}</td><td class='{x['final']}'><b>{x['final']}</b></td></tr>" for x in fl["spec_check"]["verdicts"])
    tally = ", ".join(f"{k}: {n}" for k, n in fl["spec_check"]["tally"].items())
    npass = sum(c["status"] == "PASS" for c in fl["validation"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Two Calendars MMM</title><style>{CSS}</style></head><body>
<header class="hero"><div class="wrap"><div class="eyebrow">Marketing mix modelling · diabetes brand · FDE case</div>
<h1>The Two Calendars: did a weekly-vs-monthly mismatch drive the 15% TV → digital shift?</h1>
<p>TV arrives by Monday–Sunday media week; digital, email and sales by calendar month. We built a world with a known answer and tested what the calendar error does to the recommendation.</p>
<div class="chips"><span class="chip">48 months · 210 TV weeks</span><span class="chip">300 bootstrap fits per version</span><span class="chip">{sm['sweep']['n_seeds']} simulated worlds per scenario</span><span class="chip">Synthetic data</span></div></div></header>

<main class="wrap pull">
<div class="two">
 <div class="card"><span class="sc-tag">Steady TV</span><h3>The naive calendar manufactures the shift</h3>{trio(sm)}
  <p class="small">Naive showed a confident gain in <b>{ssw['naive']['pct_seeds_confidently_positive']*100:.0f}%</b> of {sm['sweep']['n_seeds']} worlds; the correct calendar in <b>{ssw['correct']['pct_seeds_confidently_positive']*100:.0f}%</b>. True effect negative in all.</p></div>
 <div class="card"><span class="sc-tag">Heavily pulsed TV</span><h3>The calendar is second-order; the shift still fails</h3>{trio(fl)}
  <p class="small">Both versions agree on direction. Intervals are optimistic: the 90% interval caught the true TV share only <b>{fl['sweep']['channels']['tv']['correct']['coverage90']*100:.0f}%</b> of the time.</p></div>
</div>

<h2><span class="n">01</span>What this shows</h2>
<div class="takeaways">
 <div class="tk"><b>The error is real</b><span>Naive aggregation books whole weeks to one month. A typical month is off by about 12%; total spend is unchanged.</span></div>
 <div class="tk"><b>It matters most when TV is steady</b><span>Spurious month-to-month swings make TV look weak, which is exactly the signal behind “shift to digital”.</span></div>
 <div class="tk"><b>The shift is not demonstrated</b><span>The correct calendar never showed a confident gain in any world, and the true effect was negative in every one.</span></div>
</div>

<h2><span class="n">02</span>Before vs after the calendar fix</h2>
<p class="lede">Pick the TV scenario. Grey is the naive calendar, green is the day-level (apportioned) calendar, the dark diamond is the known truth.</p>
<div class="tabs"><input type="radio" name="t" id="tB" checked><input type="radio" name="t" id="tA">
<div class="tab-labels"><label for="tB">Steady TV</label><label for="tA">Heavily pulsed TV</label></div>
<div class="panels"><section id="pB">{_panel(sm, drifts['smooth'][0], drifts['smooth'][1], 'Steady TV')}</section>
<section id="pA">{_panel(fl, drifts['flighted'][0], drifts['flighted'][1], 'Heavily pulsed TV')}</section></div></div>

<h2><span class="n">03</span>The safeguard</h2>
<p class="lede">Every refresh passes a validation gate, and every claim an LLM reads from a vendor spec is verified against the actual file.</p>
<details open><summary>Data validation: {npass} of {len(fl['validation'])} checks pass, 1 intended warning</summary><div class="scroll"><table><tr><th>Status</th><th>Check</th><th>Detail</th></tr>{checks}</table></div></details>
<details><summary>LLM spec reading ({html.escape(fl['spec_check']['llm'])}): {tally}</summary><div class="scroll"><p class="small">A claim acts only if its quote exists verbatim in the spec and a deterministic test on the delivered file agrees. Any conflict raises a human-review flag.</p>
<table><tr><th>Source</th><th>Claim</th><th>Spec quote</th><th>Grounded</th><th>Data test</th><th>Result</th></tr>{vr}</table></div></details>

<h2><span class="n">04</span>Honest limits</h2>
<div class="card"><ul>
<li>The data are synthetic and the true effects (TV 18%, digital 14%, email 6%) are our design. This validates a method and a mechanism, not the real brand's numbers.</li>
<li>Only 48 monthly points. The bootstrap captures sampling noise but not model misspecification (fixed saturation, monthly adstock against a daily truth), so intervals are optimistic.</li>
<li>Spend is assumed even within a week; real phasing may differ.</li>
<li>With steady TV the correct series barely varies, so TV is weakly identified: the honest answer there is “cannot tell”, not “the shift is bad”.</li></ul></div>
<footer>Generated by build_report.py from outputs/results.json and outputs/results_smooth.json.</footer>
</main></body></html>"""


def write_combined(out_dir) -> bool:
    """Write outputs/report.html when both scenario result files exist."""
    out = Path(out_dir)
    f_fl, f_sm = out / "results.json", out / "results_smooth.json"
    if not (f_fl.exists() and f_sm.exists()):
        return False
    fl, sm = json.loads(f_fl.read_text()), json.loads(f_sm.read_text())
    drifts = {}
    for key, res, flight in (("flighted", fl, True), ("smooth", sm, False)):
        ds = generate(GenConfig(seed=res["seed"], tv_flighting=flight))
        months = pd.DatetimeIndex(ds.sales_monthly.month_start)
        n = agg.align_to_months(agg.weekly_to_monthly_naive(ds.tv_weekly, "week_start", "spend"), months)
        c = agg.align_to_months(agg.weekly_to_monthly_apportioned(ds.tv_weekly, "week_start", "spend"), months)
        drifts[key] = (n, c)
    (out / "report.html").write_text(render_combined(fl, sm, drifts), encoding="utf-8")
    return True
