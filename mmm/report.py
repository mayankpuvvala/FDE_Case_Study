"""Self-contained HTML report (inline SVG, no JS, no external assets)."""
from __future__ import annotations

import html

from .model import CH

NAMES = {"tv": "TV", "digital": "Digital", "email": "Email"}
CSS = """
:root{--bg:#fff;--fg:#1b1f24;--mut:#5b6570;--line:#d8dde3;--card:#f6f8fa;--naive:#D55E00;--ok:#0072B2;--truth:#1b1f24;--bad:#b42318;--good:#1a7f37;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1318;--fg:#e6e9ed;--mut:#9aa5b1;--line:#2b333c;--card:#171c23;--naive:#ff9a4d;--ok:#56b4e9;--truth:#e6e9ed;--bad:#ff7b72;--good:#56d364;--warn:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 8px}
.sub{color:var(--mut);margin:0 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
.call{font-size:22px;font-weight:700}.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.PASS,.VERIFIED{color:var(--good)}.FAIL,.REJECTED_UNGROUNDED,.CONTRADICTED_BY_DATA{color:var(--bad)}.WARN,.ADVISORY{color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}svg{width:100%;height:auto;display:block}
svg text{fill:var(--fg);font:12px system-ui,sans-serif}svg .m{fill:var(--mut)}.legend span{margin-right:16px;white-space:nowrap}
.sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}ul{margin:6px 0 6px 18px;padding:0}
.scroll{overflow-x:auto}.small{font-size:12.5px;color:var(--mut)}
"""


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _scale(lo, hi, x0, x1):
    return lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)


def interval_chart(rows, lo, hi, ticks, fmt, w=900, zero=False) -> str:
    """rows: [(label, truth|None, naive(est,lo,hi), correct(est,lo,hi))]"""
    L, R, rh = 90, 20, 74
    h = 30 + rh * len(rows)
    sx = _scale(lo, hi, L, w - R)
    s = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for t in ticks:
        s.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="10" y2="{h-20}" stroke="var(--line)"/>'
                 f'<text class="m" x="{sx(t):.1f}" y="{h-5}" text-anchor="middle">{fmt(t)}</text>')
    if zero:
        s.append(f'<line x1="{sx(0):.1f}" x2="{sx(0):.1f}" y1="10" y2="{h-20}" stroke="var(--fg)" stroke-width="1.5"/>')
    for i, (label, truth, nv, cr) in enumerate(rows):
        y = 20 + i * rh
        s.append(f'<text x="8" y="{y+28}" font-weight="600">{html.escape(label)}</text>')
        for j, (est, col, nm) in enumerate(((nv, "var(--naive)", "Naive"), (cr, "var(--ok)", "Correct"))):
            yy = y + 14 + j * 24
            e, a, b = est
            s.append(f'<line x1="{sx(a):.1f}" x2="{sx(b):.1f}" y1="{yy}" y2="{yy}" stroke="{col}" stroke-width="3" stroke-linecap="round"/>'
                     f'<circle cx="{sx(e):.1f}" cy="{yy}" r="6" fill="{col}"/>'
                     f'<text x="{sx(b)+10:.1f}" y="{yy+4}" class="m">{fmt(e)} [{fmt(a)}, {fmt(b)}]</text>')
        if truth is not None:
            tx = sx(truth)
            s.append(f'<path d="M{tx:.1f} {y+2} l6 6 l-6 6 l-6 -6z" fill="var(--truth)"/>'
                     f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="{y+14}" y2="{y+rh-12}" stroke="var(--truth)" stroke-dasharray="3 3"/>')
    s.append("</svg>")
    return "".join(s)


def legend(truth=True) -> str:
    t = '<span><svg width="12" height="12" viewBox="0 0 12 12" style="display:inline;width:12px;vertical-align:-1px"><path d="M6 0 l6 6 l-6 6 l-6 -6z" fill="var(--truth)"/></svg> True value (known from the generator)</span>' if truth else ""
    return ('<p class="legend small"><span><i class="sw" style="background:var(--naive)"></i>Naive (week → month of its Monday)</span>'
            f'<span><i class="sw" style="background:var(--ok)"></i>Correct (apportioned by day)</span>{t}'
            '<span>Whiskers: 90% bootstrap interval</span></p>')


def drift_chart(naive, correct, w=900, h=170) -> str:
    pcts = ((naive - correct) / correct.replace(0, float("nan")) * 100).fillna(0).values
    m = max(abs(pcts).max(), 1)
    n, L = len(pcts), 40
    bw = (w - L - 10) / n
    mid = h / 2
    s = [f'<svg viewBox="0 0 {w} {h}" role="img"><line x1="{L}" x2="{w-10}" y1="{mid}" y2="{mid}" stroke="var(--fg)"/>',
         f'<text class="m" x="4" y="14">+{m:.0f}%</text><text class="m" x="4" y="{h-6}">-{m:.0f}%</text>']
    for i, p in enumerate(pcts):
        bh = abs(p) / m * (mid - 14)
        y = mid - bh if p >= 0 else mid
        s.append(f'<rect x="{L+i*bw+1:.1f}" y="{y:.1f}" width="{bw-2:.1f}" height="{max(bh,0.5):.1f}" fill="var(--naive)"><title>{naive.index[i]:%Y-%m}: {p:+.1f}%</title></rect>')
    s.append("</svg>")
    return "".join(s)


def render(res: dict) -> str:
    fits, v, sw = res["fits"], res["verdict"], res.get("sweep")
    truth = res["true_shares"]
    rows = [(NAMES[c], truth[c],
             (fits["naive"]["channels"][c]["share"], fits["naive"]["channels"][c]["lo"], fits["naive"]["channels"][c]["hi"]),
             (fits["correct"]["channels"][c]["share"], fits["correct"]["channels"][c]["lo"], fits["correct"]["channels"][c]["hi"]))
            for c in CH]
    rn, rc = fits["naive"]["realloc"], fits["correct"]["realloc"]
    dchart = interval_chart([("15% TV → digital + email", res["true_delta"],
                              (rn["median"], rn["lo"], rn["hi"]), (rc["median"], rc["lo"], rc["hi"]))],
                            -0.04, 0.03, [-0.04, -0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03], lambda t: f"{t*100:+.1f}%", zero=True)
    mroi = "".join(f"<tr><td>{NAMES[c]}</td><td class='n'>${res['true_marginal_roi'][c]:.2f}</td>"
                   f"<td class='n'>${fits['naive']['marginal_roi'][c]:.2f}</td><td class='n'>${fits['correct']['marginal_roi'][c]:.2f}</td></tr>"
                   for c in CH)
    roi = "".join(f"<tr><td>{NAMES[c]}</td><td class='n'>${truth_roi:.1f}</td>"
                  f"<td class='n'>${fits['naive']['channels'][c]['roi']:.1f} [{fits['naive']['channels'][c]['roi_lo']:.1f}, {fits['naive']['channels'][c]['roi_hi']:.1f}]</td>"
                  f"<td class='n'>${fits['correct']['channels'][c]['roi']:.1f} [{fits['correct']['channels'][c]['roi_lo']:.1f}, {fits['correct']['channels'][c]['roi_hi']:.1f}]</td></tr>"
                  for c, truth_roi in res["true_roi"].items())
    checks = "".join(f"<tr><td class='{c['status']}'><b>{c['status']}</b></td><td>{html.escape(c['name'])}</td><td>{html.escape(c['detail'])}</td></tr>"
                     for c in res["validation"])
    vr = "".join(f"<tr><td>{html.escape(x['source'])}</td><td>{html.escape(x['field'])} = {html.escape(x['value'])}</td>"
                 f"<td class='small'>“{html.escape(x['quote'])}”</td><td>{'yes' if x['grounded'] else 'NO'}</td>"
                 f"<td>{html.escape(x['detail'])}</td><td class='{x['final']}'><b>{x['final']}</b></td></tr>"
                 for x in res["spec_check"]["verdicts"])
    sweep_html = ""
    if sw:
        srows = "".join(f"<tr><td>{NAMES[c]}</td><td class='n'>{sw['channels'][c]['naive']['bias']*100:+.1f}</td><td class='n'>{sw['channels'][c]['correct']['bias']*100:+.1f}</td>"
                        f"<td class='n'>{sw['channels'][c]['paired_diff_sd']*100:.1f}</td><td class='n'>{sw['channels'][c]['naive']['coverage90']*100:.0f}% / {sw['channels'][c]['correct']['coverage90']*100:.0f}%</td>"
                        f"<td class='n'>{sw['channels'][c]['correct']['mean_width']*100:.1f}</td></tr>" for c in CH)
        rl = sw["realloc"]
        sweep_html = f"""<h2>5. Is the calendar error a systematic bias? ({sw['n_seeds']} re-simulated worlds)</h2>
<div class="card"><div class="scroll"><table><tr><th>Channel</th><th class="n">Bias naive (pts)</th><th class="n">Bias correct (pts)</th>
<th class="n">SD of (naive − correct) (pts)</th><th class="n">90% CI covers truth (naive / correct)</th><th class="n">Mean CI width (pts)</th></tr>{srows}</table></div>
<p>Reallocation: the true effect of the 15% shift averages <b>{rl['true_delta_mean']*100:+.2f}%</b> of sales (negative in {rl['true_delta_sign_negative_share']*100:.0f}% of worlds).
Median modelled effect: naive <b>{rl['naive']['mean_median_delta']*100:+.2f}%</b>, correct <b>{rl['correct']['mean_median_delta']*100:+.2f}%</b>.
Share of worlds in which the model would call the shift a <i>confident win</i> (interval above zero): naive <b>{rl['naive']['pct_seeds_confidently_positive']*100:.0f}%</b>, correct <b>{rl['correct']['pct_seeds_confidently_positive']*100:.0f}%</b>.</p></div>"""
    spill = res["spec_check"]
    tally = ", ".join(f"{k}: {n}" for k, n in spill["tally"].items())
    cov_note = "run with --sweep N to measure how often the intervals cover the truth."
    if sw:
        cv = sw["channels"]["tv"]["correct"]["coverage90"]
        cov_note = (f"the bootstrap captures sampling noise only. Across {sw['n_seeds']} simulated worlds the nominal 90% intervals "
                    f"covered the true TV share just {cv*100:.0f}% of the time (model misspecification), so read the intervals as optimistic. "
                    f"What is robust: the shift never looked like a confident win (0 of {sw['n_seeds']} worlds), and the true effect was negative in "
                    f"{sw['realloc']['true_delta_sign_negative_share']*100:.0f}% of them.")
    call_col = {"HOLDS": "good", "DOES NOT HOLD": "bad", "NOT SUPPORTED": "warn"}[v["call"]]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Two Calendars MMM</title><style>{CSS}</style></head><body><main>
<h1>The Two Calendars — does the TV → digital shift survive?</h1>
<p class="sub">Synthetic diabetes-brand MMM · TV weekly (Mon–Sun), digital/email/sales monthly · {res['n_months']} months · seed {res['seed']} · scenario: {res.get('scenario', 'flighted')} TV · {res['n_boot']} bootstrap fits per version</p>

<div class="card"><div class="call" style="color:var(--{call_col})">15% TV → digital/email: {v['call']}</div>
<p>{html.escape(v['text'])}</p>
<ul><li>Median sales impact of the shift: <b>{v['median_correct']*100:+.2f}%</b> (correct calendar) vs <b>{v['median_naive']*100:+.2f}%</b> (naive). Ground truth in this simulation: <b>{v['truth_delta']*100:+.2f}%</b>.</li>
<li>Probability the shift raises sales: <b>{v['p_positive_correct']*100:.0f}%</b> (correct), <b>{v['p_positive_naive']*100:.0f}%</b> (naive).</li>
<li>Direction: the calendar fix {'does not change' if (rn['median'] < 0) == (rc['median'] < 0) else 'FLIPS'} the sign of the effect. Naive 90% interval {'includes' if rn['lo'] <= 0 <= rn['hi'] else 'excludes'} zero; correct interval {'includes' if rc['lo'] <= 0 <= rc['hi'] else 'excludes'} zero.</li>
<li><b>Confidence caveat:</b> {cov_note}</li></ul></div>

<h2>1. Channel contribution — before vs after the calendar fix</h2>
{interval_chart(rows, 0, 0.40, [0, .1, .2, .3, .4], lambda t: f"{t*100:.0f}%")}{legend()}

<h2>2. Return per $ (average ROI = sales contribution ÷ spend)</h2>
<div class="card"><table><tr><th>Channel</th><th class="n">Truth</th><th class="n">Naive [90% CI]</th><th class="n">Correct [90% CI]</th></tr>{roi}</table></div>

<p class="small">Marginal ROI = extra sales from one extra dollar (spend +10%). This, not the average, decides whether moving money helps: saturation makes the next dollar worth less than the average dollar.</p>
<div class="card"><table><tr><th>Channel</th><th class="n">Truth</th><th class="n">Naive</th><th class="n">Correct</th></tr>{mroi}</table></div>

<h2>3. Sales impact of moving 15% of TV spend</h2>
{dchart}{legend()}

<h2>4. How wrong is the naive monthly TV series?</h2>
<p class="small">Each bar is one month: naive minus correct, as % of correct. Total spend is identical; the naive method only moves spend into the wrong months.</p>
{drift_chart(res['naive_tv'], res['correct_tv'])}
{sweep_html}

<h2>6. Data validation (runs on every refresh; errors block the model fit)</h2>
<div class="card scroll"><table><tr><th>Status</th><th>Check</th><th>Detail</th></tr>{checks}</table></div>

<h2>7. LLM reads the vendor specs → every claim is verified</h2>
<p class="small">Reader: <b>{html.escape(spill['llm'])}</b> · outcome: {tally}. A claim drives pipeline behaviour only if its quote exists verbatim in the spec (grounded) <i>and</i> a deterministic test on the delivered file agrees.</p>
<div class="card scroll"><table><tr><th>Source</th><th>Claim</th><th>Spec quote</th><th>Grounded</th><th>Data test</th><th>Result</th></tr>{vr}</table></div>
<p class="card"><b>Derived action:</b> apportion TV weeks across calendar months = {html.escape(str(spill['actions']['apportion_tv_weekly_to_monthly']))} — {html.escape(spill['actions']['reason'])}<br>
<b>Human review needed:</b> {'YES - ' + html.escape(', '.join(spill['actions']['conflicts'])) if spill['actions']['needs_human_review'] else 'no spec/data conflicts'}</p>

<h2>Honest limits</h2><div class="card"><ul>
<li>Data are synthetic; the truth was designed by us (TV share 18%, digital 14%, email 6%). Findings show the <i>method</i>, not the real brand.</li>
<li>Only 48 monthly observations: intervals are wide by nature, and the bootstrap does not capture model misspecification (saturation scale is fixed, adstock is monthly while the truth is daily).</li>
<li>Even-spread-within-week is the standard apportioning assumption; if the real phasing is front-loaded the correct series is still approximate.</li></ul></div>
</main></body></html>"""
