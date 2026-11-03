"""Builds outputs/Solution_Document.docx (explicit and exhaustive) from the pipeline outputs.
Run:  uv run python build_doc.py   (after run_pipeline.py, run_pipeline.py --scenario smooth, run_sensitivity.py)"""
from __future__ import annotations

import ast
import dataclasses
import json
import sys
from importlib import metadata
from pathlib import Path

import pandas as pd
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from mmm.generator import GenConfig
from mmm.model import MMMConfig
from mmm.spec_llm import FIELDS, PROMPT, SOURCES

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
FL = json.loads((OUT / "results.json").read_text())
SM = json.loads((OUT / "results_smooth.json").read_text())
SEN = json.loads((OUT / "sensitivity.json").read_text())
CH = ["tv", "digital", "email"]
NAME = {"tv": "TV", "digital": "Digital", "email": "Email"}
GREEN = RGBColor(0x1B, 0x7F, 0x4B)
P = lambda x, d=1: f"{x * 100:.{d}f}%"
SP = lambda x, d=2: f"{x * 100:+.{d}f}%"
ci = lambda lo, hi, d=1: f"[{lo * 100:.{d}f}, {hi * 100:.{d}f}]"

doc = Document()
st = doc.styles["Normal"]
st.font.name, st.font.size = "Calibri", Pt(10.5)
for lvl, size in ((1, 16), (2, 12.5), (3, 11)):
    h = doc.styles[f"Heading {lvl}"]
    h.font.name, h.font.size, h.font.color.rgb, h.font.bold = "Calibri", Pt(size), GREEN, True
for sec in doc.sections:
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Pt(60)


def shade(cell, hex_):
    pr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hex_)
    pr.append(sh)


def H(t, lvl=2):
    return doc.add_heading(t, lvl)


def para(t="", lead=None, style=None, italic=False):
    p = doc.add_paragraph(style=style)
    if lead:
        p.add_run(lead).bold = True
    r = p.add_run(t)
    r.italic = italic
    p.paragraph_format.space_after = Pt(4)
    return p


def bullets(items):
    for it in items:
        para(it[1], lead=it[0], style="List Bullet") if isinstance(it, tuple) else para(it, style="List Bullet")


def numbered(items):
    for it in items:
        para(it[1], lead=it[0], style="List Number") if isinstance(it, tuple) else para(it, style="List Number")


def mono(t):
    p = doc.add_paragraph()
    r = p.add_run(t)
    r.font.name, r.font.size = "Consolas", Pt(8.5)
    p.paragraph_format.left_indent = Pt(10)
    p.paragraph_format.space_after = Pt(4)


def table(header, rows, size=9):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size, r.font.color.rgb = True, Pt(size), RGBColor(255, 255, 255)
        shade(c, "1B7F4B")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(size)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ------------------------------------------------------------------ reusable result tables
def contrib_table(res):
    rows = []
    for c in CH:
        n, k = res["fits"]["naive"]["channels"][c], res["fits"]["correct"]["channels"][c]
        tr = res["true_shares"][c]
        rows.append([NAME[c], P(tr), f"{P(n['share'])} {ci(n['lo'], n['hi'])}", f"{(n['share'] - tr) * 100:+.1f}",
                     f"{P(k['share'])} {ci(k['lo'], k['hi'])}", f"{(k['share'] - tr) * 100:+.1f}", f"{n['decay']:.2f} / {k['decay']:.2f}"])
    table(["Channel", "True share", "Naive share [90% CI]", "Naive error (pts)", "Correct share [90% CI]", "Correct error (pts)", "Chosen adstock decay naive / correct"], rows)


def roi_table(res):
    rows = []
    for c in CH:
        n, k = res["fits"]["naive"], res["fits"]["correct"]
        rows.append([NAME[c], f"{res['true_roi'][c]:.2f}", f"{n['channels'][c]['roi']:.2f} {ci(n['channels'][c]['roi_lo'], n['channels'][c]['roi_hi'], 1).replace('%', '')}".replace("[", "[").replace("]", "]"),
                     f"{k['channels'][c]['roi']:.2f}", f"{res['true_marginal_roi'][c]:.2f}", f"{n['marginal_roi'][c]:.2f}", f"{k['marginal_roi'][c]:.2f}"])
    table(["Channel", "True avg ROI ($/$)", "Naive avg ROI", "Correct avg ROI", "True marginal ROI", "Naive marginal ROI", "Correct marginal ROI"], rows)


def realloc_table(res):
    n, k = res["fits"]["naive"]["realloc"], res["fits"]["correct"]["realloc"]
    table(["Version", "Point estimate", "Bootstrap median", "90% interval", "P(impact > 0)"], [
        ["Naive", SP(n["point"]), SP(n["median"]), ci(n["lo"], n["hi"], 2) + "%", P(n["p_positive"], 0)],
        ["Correct", SP(k["point"]), SP(k["median"]), ci(k["lo"], k["hi"], 2) + "%", P(k["p_positive"], 0)],
        ["Truth (true daily process)", SP(res["true_delta"]), "-", "-", "-"]])


def sweep_table(res):
    sw, rows = res["sweep"], []
    for c in CH:
        d = sw["channels"][c]
        rows.append([NAME[c], f"{d['naive']['bias']*100:+.1f}", f"{d['correct']['bias']*100:+.1f}", f"{d['naive']['rmse']*100:.1f}", f"{d['correct']['rmse']*100:.1f}",
                     f"{d['paired_diff_mean']*100:+.1f}", f"{d['paired_diff_sd']*100:.1f}", f"{P(d['naive']['coverage90'], 0)} / {P(d['correct']['coverage90'], 0)}",
                     f"{d['naive']['mean_width']*100:.1f} / {d['correct']['mean_width']*100:.1f}"])
    table(["Channel", "Bias naive (pts)", "Bias correct (pts)", "RMSE naive", "RMSE correct", "Mean of naive−correct (pts)", "SD of naive−correct (pts)", "90% CI covers truth: naive / correct", "Mean CI width (pts): naive / correct"], rows, size=8.5)
    r = sw["realloc"]
    table(["Reallocation metric (over %d worlds)" % sw["n_seeds"], "Naive", "Correct"], [
        ["Mean of median modelled impact", SP(r["naive"]["mean_median_delta"]), SP(r["correct"]["mean_median_delta"])],
        ["Mean P(impact > 0)", P(r["naive"]["mean_p_positive"], 0), P(r["correct"]["mean_p_positive"], 0)],
        ["Worlds with a confident gain (90% interval above 0)", P(r["naive"]["pct_seeds_confidently_positive"], 0), P(r["correct"]["pct_seeds_confidently_positive"], 0)],
        ["True impact (mean over worlds)", SP(r["true_delta_mean"]), SP(r["true_delta_mean"])],
        ["Worlds in which the true impact is negative", P(r["true_delta_sign_negative_share"], 0), P(r["true_delta_sign_negative_share"], 0)]])


def validation_table(res):
    table(["Status", "Check", "Detail (this run)"], [[c["status"], c["name"], c["detail"]] for c in res["validation"]], size=8.5)


def claims_table(res):
    table(["Source", "Field = value", "Quote from spec", "Grounded", "Data test", "Final"],
          [[v["source"], f"{v['field']} = {v['value']}", v["quote"], "yes" if v["grounded"] else "no", v["detail"], v["final"]] for v in res["spec_check"]["verdicts"]], size=8)


# ================================================================== title
t = doc.add_paragraph()
r = t.add_run("The Two Calendars: Solution Document")
r.bold, r.font.size, r.font.color.rgb = True, Pt(22), GREEN
para("Case 3 · Pharma (diabetes brand) · Marketing mix modelling · FDE associate submission · 3 November 2026")
table(["Item", "Value"], [
    ["Main run seed / bootstrap fits", f"seed {FL['seed']}, {FL['n_boot']} fits per version per scenario; sweep: {FL['sweep']['n_seeds']} seeds × 80 fits"],
    ["Scenarios reported", "A: 'flighted' TV (on/off pulses). B: 'smooth' TV (steady weekly spend). Both are reported in full; neither was dropped."],
    ["Python", sys.version.split()[0]],
    ["LLM used for the reported runs", f"{FL['spec_check']['llm']} (Groq)"],
    ["Companion files", "outputs/report.html (before/after view of both scenarios), outputs/slides.pptx (storytelling deck), outputs/results*.json, outputs/sensitivity.json"],
])

# ================================================================== 1
H("1. Solution overview", 1)
para("The client's marketing mix model joins TV spend reported by Monday-to-Sunday media weeks with digital, email and sales reported by calendar month, "
     "and the Brand Director has already moved 15% of TV spend into digital and email on the strength of it. "
     "I built a reproducible pipeline: a synthetic generator with a known true effect per channel, naive and day-level (apportioned) aggregation, "
     "an adstock-and-saturation MMM with a 300-fit bootstrap, a grain and calendar validation gate, and an LLM that reads vendor specifications with every claim verified against the delivered files. "
     f"Main result: the shift is not supported by the data in either world I simulated, but the calendar error matters a lot when TV spend is steady: the naive calendar then reports a gain of {SP(SM['fits']['naive']['realloc']['median'])} "
     f"(P(gain) {P(SM['fits']['naive']['realloc']['p_positive'], 0)}) where the truth is {SP(SM['true_delta'])}, and showed a confident gain in {P(SM['sweep']['realloc']['naive']['pct_seeds_confidently_positive'], 0)} of {SM['sweep']['n_seeds']} simulated worlds against 0% for the correct calendar. "
     f"When TV is heavily pulsed the calendar is second-order (shares move about ±2 points) and both versions say the shift loses sales ({SP(FL['fits']['naive']['realloc']['median'])} naive, {SP(FL['fits']['correct']['realloc']['median'])} correct, truth {SP(FL['true_delta'])}). "
     f"Confidence is high that the shift is not a demonstrated win and low on its exact size, because the bootstrap intervals covered the true TV share only {P(FL['sweep']['channels']['tv']['correct']['coverage90'], 0)} of the time in the pulsed world.")
H("Headline numbers", 2)
table(["Quantity", "A: flighted TV", "B: smooth TV"], [
    ["True effect of the 15% shift on total sales", SP(FL["true_delta"]), SP(SM["true_delta"])],
    ["Naive calendar: modelled effect (median) / P(>0)", f"{SP(FL['fits']['naive']['realloc']['median'])} / {P(FL['fits']['naive']['realloc']['p_positive'], 0)}", f"{SP(SM['fits']['naive']['realloc']['median'])} / {P(SM['fits']['naive']['realloc']['p_positive'], 0)}"],
    ["Correct calendar: modelled effect (median) / P(>0)", f"{SP(FL['fits']['correct']['realloc']['median'])} / {P(FL['fits']['correct']['realloc']['p_positive'], 0)}", f"{SP(SM['fits']['correct']['realloc']['median'])} / {P(SM['fits']['correct']['realloc']['p_positive'], 0)}"],
    ["TV share credited: truth / naive / correct", f"{P(FL['true_shares']['tv'])} / {P(FL['fits']['naive']['channels']['tv']['share'])} / {P(FL['fits']['correct']['channels']['tv']['share'])}", f"{P(SM['true_shares']['tv'])} / {P(SM['fits']['naive']['channels']['tv']['share'])} / {P(SM['fits']['correct']['channels']['tv']['share'])}"],
    ["Sweep: worlds showing a confident gain, naive / correct", f"{P(FL['sweep']['realloc']['naive']['pct_seeds_confidently_positive'], 0)} / {P(FL['sweep']['realloc']['correct']['pct_seeds_confidently_positive'], 0)}", f"{P(SM['sweep']['realloc']['naive']['pct_seeds_confidently_positive'], 0)} / {P(SM['sweep']['realloc']['correct']['pct_seeds_confidently_positive'], 0)}"],
    ["Sweep: SD of (naive − correct) TV share, points", f"{FL['sweep']['channels']['tv']['paired_diff_sd']*100:.1f}", f"{SM['sweep']['channels']['tv']['paired_diff_sd']*100:.1f}"],
    ["Sweep: mean TV share bias, naive / correct (points)", f"{FL['sweep']['channels']['tv']['naive']['bias']*100:+.1f} / {FL['sweep']['channels']['tv']['correct']['bias']*100:+.1f}", f"{SM['sweep']['channels']['tv']['naive']['bias']*100:+.1f} / {SM['sweep']['channels']['tv']['correct']['bias']*100:+.1f}"],
    ["Validation checks (pass / total)", f"{sum(c['status'] == 'PASS' for c in FL['validation'])} / {len(FL['validation'])} (1 intended warning)", f"{sum(c['status'] == 'PASS' for c in SM['validation'])} / {len(SM['validation'])} (1 intended warning)"],
    ["LLM claims verified / advisory / rejected", f"{FL['spec_check']['tally'].get('VERIFIED', 0)} / {FL['spec_check']['tally'].get('ADVISORY', 0)} / {FL['spec_check']['tally'].get('REJECTED_UNGROUNDED', 0) + FL['spec_check']['tally'].get('CONTRADICTED_BY_DATA', 0)}", "same specs"],
])

# ================================================================== 2
H("2. Approach and methodology", 1)
H("2.1 Pipeline at a glance", 2)
mono("generate daily truth -> publish vendor files (TV weekly, rest monthly) -> LOAD refresh -> VALIDATE (gate) -> LLM reads specs -> VERIFY claims\n"
     "   -> aggregate TV two ways (naive | apportioned) -> fit MMM on each (+300 bootstrap fits) -> counterfactual 15% move -> verdict + report\n"
     "   -> repeat over N simulated worlds (robustness) and over scenarios (sensitivity)")
para("Why this order: validation and spec verification come before any modelling so a calendar or grain fault is caught while it is still cheap; the two aggregation versions are fitted with identical code so any difference is attributable to the calendar alone; "
     "the simulated truth lets every estimate be scored.")
H("2.2 Step 1: synthetic data with a known truth (mmm/generator.py)", 2)
para("The simulator lives at daily grain because that is how the world works; vendors then publish at coarser grain. For each day d and channel c:")
mono("adstock_c(d)   = spend_c(d) + decay_c * adstock_c(d-1)                (daily, geometric)\n"
     "sat_c(d)       = 1 - exp( -adstock_c(d) / s_c ),   s_c = sat_mult_c * mean(adstock_c over the window)\n"
     "effect_c(d)    = beta_c * sat_c(d)\n"
     "sales(d)       = base(d) + sum_c effect_c(d)\n"
     "base(d)        = base_daily * (1 + trend*t) * (1 + amp*sin(2*pi*(doy-30)/365.25) + 0.04*cos(4*pi*doy/365.25))\n"
     "beta_c         = share_c / (1 - sum shares) * sum(base) / sum(sat_c)   [window days]  -> realised share = share_c by construction\n"
     "monthly sales  = sum of daily sales in the calendar month * (1 + N(0, noise_frac))")
para("The beta calibration is what plants the known truth: it forces channel c to cause exactly share_c of window sales (18%, 14%, 6%). Because the full daily process is stored, the same code can be re-run with different spend to obtain the TRUE effect of any counterfactual (function true_realloc_effect) and the TRUE marginal ROI of any channel (true_marginal_roi).")
H("2.3 Step 2: reproducing the calendar error (mmm/aggregate.py)", 2)
para("Naive: each week goes entirely to the calendar month of its first day (the week-ending anchor is also implemented). Correct: each week's spend is divided by 7, assigned to its 7 days, and days are summed by calendar month. "
     "Worked example, a $700k week from Monday 29 Jan to Sunday 4 Feb:")
table(["Method", "January", "February", "Total"], [["Naive (anchor = Monday)", "$700k", "$0k", "$700k"], ["Naive (anchor = Sunday)", "$0k", "$700k", "$700k"], ["Apportioned (3 days Jan, 4 days Feb)", "$300k", "$400k", "$700k"]])
para("Apportioning conserves total spend (a tested invariant, relative error 1.4e-16 in the main run). Weeks that spill outside the modelling window (the week starting 27 Dec 2021 and the week starting 29 Dec 2025) are handled by dropping the out-of-window days, so December 2025 receives 3/7 of its last week under the correct method and all of it under the naive one; this edge effect is why the worst-month deviation (66.8%) is far above the median (11.8%).")
H("2.4 Step 3: validation gate (mmm/validate.py)", 2)
para("Every refresh runs the checks below before any fit. 'error' blocks the pipeline (run_pipeline.py exits with code 1 unless --skip-gate), 'warn' is reported only.")
table(["Check", "Rule", "Severity", "Why it exists"], [
    ["Schema", "Required columns present for each file", "error", "A renamed/missing column silently breaks joins"],
    ["No nulls / duplicates", "0 null cells; 0 duplicate dates", "error", "Duplicate weeks double-count spend"],
    ["TV week starts Monday", "Every date has weekday = Monday", "error", "A shifted week changes which days are apportioned to which month"],
    ["TV contiguous 7-day spacing", "All consecutive gaps = 7 days", "error", "Gaps or doubled weeks distort monthly totals"],
    ["Monthly files: dates on the 1st", "day = 1 for Digital, Email, Sales", "error", "Catches period-end dates and 4-4-5 fiscal period starts mistaken for months"],
    ["Monthly files: no missing months", "Date range has every month start", "error", "A missing month is read as zero"],
    ["Identical month sets", "Digital, Email and Sales cover the same months", "error", "Misaligned joins"],
    ["TV coverage of the window", "First week start <= first modelled day; last week end >= last modelled day", "error", "Partial coverage understates edge months"],
    ["Conservation", "weekly total = apportioned in-window total + out-of-window spill (tolerance 1e-6)", "error", "Proves the apportioning moved spend without creating or losing any"],
    ["Calendar drift", "Max monthly deviation naive vs apportioned < 2%", "warn", "Quantifies calendar risk on THIS data; above 2% apportioning is mandatory"],
])
H("2.5 Step 4: LLM reads vendor specifications and every claim is verified (mmm/spec_llm.py)", 2)
para("Detailed in Section 7. In one sentence: the LLM turns free-text specs into {source, field, value, quote} claims; a claim drives behaviour only if its quote exists verbatim in the spec and a deterministic test on the delivered file agrees.")
H("2.6 Step 5: the MMM (mmm/model.py)", 2)
para("Model, estimated on per-day rates (monthly total divided by days in the month) so that 28- and 31-day months are comparable (the Sales spec explicitly states no day-count normalisation is applied):")
mono("y_m / days_m  =  Q_m . gamma  +  sum_c beta_c * f_c(m)  +  eps_m                 beta_c >= 0\n"
     "f_c(m)        =  1 - exp( - A_c(m) / s_c ),     A_c(m) = x_c(m)/days_m + decay_c * A_c(m-1)    (geometric adstock, monthly)\n"
     "s_c           =  sat_mult * mean(A_c)  with sat_mult = 1.0 (FIXED, not estimated)\n"
     "Q             =  [1, trend, sin/cos(2*pi*month/12), sin/cos(4*pi*month/12)]  (intercept, linear trend, two seasonal harmonics)")
numbered([
    ("Decay grid. ", "decay_c in {0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.75} per channel: 7^3 = 343 combinations."),
    ("Partial out controls (Frisch-Waugh). ", "With M = I - Q Q+, regress M*y on M*f_c; this removes trend and seasonality exactly while keeping beta >= 0 tractable."),
    ("NNLS. ", "For each grid point solve the non-negative least squares problem (scipy.optimize.nnls) and keep the combination with the lowest residual norm."),
    ("Recover the controls. ", "gamma = lstsq(Q, y - F beta)."),
    ("Contribution and ROI. ", "contribution_c = sum_m days_m * beta_c * f_c(m); share_c = contribution_c / total sales; average ROI_c = contribution_c / total spend_c."),
    ("Marginal ROI. ", "Raise channel spend by 10%, recompute f_c, and divide the sales gain by the extra dollars. Average ROI answers 'what did the channel earn'; marginal ROI answers 'what would one more dollar earn' and is what a reallocation depends on."),
])
H("2.7 Step 6: uncertainty (bootstrap)", 2)
para("Residual bootstrap: fitted values + resampled residuals (with replacement), refit including the whole decay search, 300 times per version. Intervals are the 5th and 95th percentiles. "
     "This captures sampling noise and decay uncertainty only; it cannot capture model misspecification (Section 5.6 measures how much that matters).")
H("2.8 Step 7: the business question (counterfactual reallocation)", 2)
bullets(["Move fraction 0.15 of total TV spend. TV monthly spend is multiplied by 0.85.",
         f"The moved dollars are split between digital and email pro-rata to their current total spend (about {1650/(1650+250)*100:.0f}% to digital, {250/(1650+250)*100:.0f}% to email at the default spend levels) and distributed over months pro-rata to each channel's own monthly pattern.",
         "Total sales are re-predicted with each bootstrap fit; the output is the change in total sales as a percentage of baseline sales, its interval, and P(change > 0).",
         "The TRUE effect is obtained by running the identical move through the true daily process."])
H("2.9 Step 8: robustness experiments", 2)
bullets([("Multi-world sweep (mmm/experiment.py). ", f"{FL['sweep']['n_seeds']} re-simulated worlds (seeds 0 to {FL['sweep']['n_seeds']-1}), 80 bootstrap fits per version per world, run separately for scenario A and B. Reports bias, RMSE, interval coverage, the paired naive-minus-correct difference and how often a confident gain is shown."),
         ("Sensitivity (run_sensitivity.py). ", "10 worlds per scenario with point fits: default, TV not flighted, saturation matching the model, matched saturation plus 0.3% noise (Section 5.5).")])

# ================================================================== 3
H("3. How I arrived at it", 1)
H("3.1 Alternatives considered and rejected", 2)
table(["Decision", "Alternative(s)", "Why I chose / rejected"], [
    ["MMM implementation", "Meridian, Robyn, PyMC / Stan", "Rejected for the build: heavy installs and slow iteration on a machine whose system Python was broken (resolved with uv); I also needed control over adstock, the decay search and the bootstrap so naive and correct runs differ only in the calendar. Recommended for a client deployment (Section 8)."],
    ["Public dataset", "Robyn simulated weekly data, Meridian sample data", "Rejected: they have no known true effects for a TV/digital/email counterfactual and are not at the mixed weekly/monthly grain; the case allows synthetic generation."],
    ["Modelling grain", "Weekly model by splitting monthly sales into weeks", "Rejected: sales are monthly, disaggregation invents data. Model at monthly grain on per-day rates."],
    ["Fixing the calendar", "Assign by week-ending date; treat 4-4-5 periods as months; allocate by business days", "Week-ending anchor implemented as a naive variant. 4-4-5-as-months is caught by the validator (period starts are not the 1st). Day-level apportioning is the only method that conserves spend and respects true month boundaries."],
    ["Saturation", "Estimate a scale per channel", "Rejected: 48 points and three channels cannot identify it; scale fixed at the mean adstocked spend (a stated misspecification, 5.6)."],
    ["Uncertainty", "MCMC posterior; pairs bootstrap", "Residual bootstrap including decay search is cheap and transparent; MCMC with priors is the recommended upgrade. Pairs bootstrap would break the time series."],
    ["Who reads the spec", "Regex; the LLM also deciding the calendar; no spec reading", "Regex is brittle across vendors; an unchecked LLM would add risk to the very failure being fixed; so LLM extracts, code verifies."],
    ["LLM provider", "Anthropic, OpenAI, Groq", "Groq (free tier) worked live with openai/gpt-oss-120b; the OpenAI key returned HTTP 429 'no credits remaining'; no Anthropic key was available. All three backends are implemented behind one interface."],
])
H("3.2 Assumptions register", 2)
table(["#", "Assumption", "If wrong", "Tested?"], [
    ["A1", "Spend is spread evenly across the 7 days of a week and across the days of a month", "Apportioning is approximate; real phasing (e.g. front-loaded) shifts spend between months", "Not tested; stated limitation"],
    ["A2", "Naive pipeline anchors a week to the month of its Monday", "If the client used week-ending or 4-4-5 periods the size of the error changes", "Week-ending variant implemented and unit-tested; 4-4-5 caught by validator"],
    ["A3", "Moved dollars split pro-rata to current digital:email spend", "A different split changes the shift's effect (email has the higher marginal ROI)", "Not varied"],
    ["A4", "Contribution share = modelled channel sales / total sales", "Different baselines move shares", "Used consistently for truth and model"],
    ["A5", "True effects (TV 18%, digital 14%, email 6%) and flighting severity are my design", "Client's real effects (Exhibit 2: TV 22%, digital 19%, email 11%) differ", "Two phasing scenarios and four sensitivity scenarios"],
    ["A6", "Saturation scale fixed; adstock monthly while the truth is daily", "Biases shares (TV +6 pts, digital -4 pts in scenario A)", "Quantified in the sweeps"],
    ["A7", "Window Jan 2022 to Dec 2025, 48 months, no restatements", "Late invoices may restate prior weeks (TV spec 4)", "Not simulated"],
])
H("3.3 Clarification Desk answers relied on", 2)
para("No Clarification Desk answers were provided to me during this build, so none are relied on. At the start I asked the author seven scoping questions (time limit, LLM key, library constraints, data source, slide format, expected result, working style). "
     "They were not answered individually, so I took the defaults stated below. [Author note: add any real Clarification Desk answers here, for example how the client's pipeline actually maps weeks to months.]")
table(["Question", "Default I applied"], [
    ["Time limit", "Build a complete MVP rather than a minimal one"], ["LLM key", "Use live API where a key exists, with an offline mock for tests"],
    ["Libraries", "Own numpy/scipy implementation; no Meridian/Robyn/PyMC"], ["Data source", "Synthetic"],
    ["Slide format", "pptx"], ["Expected result", "Let the data decide and report honestly"], ["Working style", "Build all, then explain"]])
H("3.4 How the solution changed during the build (decision log)", 2)
table(["Step", "What happened", "What I changed"], [
    ["1", "First run: digital share was badly under-estimated (about 6% vs 14%).", "Cause: my digital/email budgets carried a seasonal pattern collinear with the model's seasonal controls. Reduced the budget seasonality amplitude 0.15 -> 0.04 and increased budget noise 0.25 -> 0.35 so the channels are identifiable. Disclosed here; done before any sweep results were seen."],
    ["2", "A 12-seed sweep with flighted TV showed naive ~ correct.", "Rather than stop at 'the calendar does not matter', I tested why: added the smooth-TV scenario and the sensitivity script. Result: in steady-TV worlds the naive calendar creates a false signal. Both scenarios are reported; neither is hidden."],
    ["3", "Unit test for 'flat digital spend => ~0 contribution' failed (42%).", "A constant channel is not identifiable against the intercept, so the model can credit it arbitrarily. I replaced the test with an R-squared test and record this as a model limitation."],
    ["4", "Spec-lie test failed: with Tuesday-start TV weeks the action still said 'apportion'.", "derive_actions now also requires a verified week_start_day; any contradiction sets needs_human_review."],
    ["5", "Live LLM runs: Groq model llama-3.3-70b-versatile returned 404; OpenAI key returned 429.", "Listed Groq's models, switched to openai/gpt-oss-120b; kept the OpenAI backend but marked it unused."],
    ["6", "Needed to explain why the shift fails even though email looks 'high efficiency'.", "Added marginal ROI (truth and model). Average email ROI is high but a pro-rata move sends about 87% of the money to digital, whose marginal ROI is below TV's."],
])

# ================================================================== 4
H("4. Data", 1)
para("All data are synthetic. Nothing was adapted from Robyn or Meridian. The generator (mmm/generator.py) is deterministic given a seed.")
H("4.1 Generator configuration (defaults)", 2)
cfg = GenConfig()
rows = [[f.name, str(getattr(cfg, f.name))] for f in dataclasses.fields(cfg) if f.name != "truth"]
rows += [[f"truth[{k}]", f"share={v.share}, decay (daily)={v.decay}, sat_mult={v.sat_mult}"] for k, v in cfg.truth.items()]
table(["Parameter", "Value"], rows)
para("Scenario A ('flighted') uses tv_flighting=True: TV weekly spend is built from blocks of 2 to 4 weeks at intensity levels {0.15, 0.5, 1.0, 1.6, 2.3} times a log-normal(0, 0.15) jitter, normalised to the mean. "
     "Scenario B ('smooth') uses tv_flighting=False: weekly spend is simply log-normal(0, 0.15), i.e. a steady always-on schedule with about 15% week-to-week variation. Digital and email budgets in both: monthly = mean x (1 + 0.04 sin(2 pi (month - 3)/12)) x log-normal(0, 0.35), normalised to the mean.")
H("4.2 Files produced (vendor shape)", 2)
table(["File", "Columns", "Rows", "Grain"], [
    ["data/tv_media_weekly.csv", "week_commencing (Monday, YYYY-MM-DD), spend_usd_k", "210", "weekly, Mon-Sun, includes the weeks straddling the window edges"],
    ["data/digital_monthly.csv", "month (1st of month), spend_usd_k", "48", "calendar month"],
    ["data/email_monthly.csv", "month, spend_usd_k", "48", "calendar month"],
    ["data/sales_monthly.csv", "month, sales_usd_k", "48", "calendar month"],
    ["data/scenario_smooth/*.csv", "same four files for scenario B", "same", "same"],
    ["data/vendor_specs/*.txt", "three free-text vendor specifications read by the LLM", "3 files", "text"],
])
for f, cols in (("tv_media_weekly.csv", None), ("sales_monthly.csv", None)):
    df = pd.read_csv(ROOT / "data" / f).head(5)
    para(f"First five rows of data/{f}:", italic=True)
    table(list(df.columns), df.round(2).values.tolist())
H("4.3 Ground truth built in", 2)
table(["Truth", "Scenario A", "Scenario B"], [
    ["True share of window sales (TV / digital / email)", " / ".join(P(FL["true_shares"][c]) for c in CH), " / ".join(P(SM["true_shares"][c]) for c in CH)],
    ["True average ROI, $ per $ (TV / digital / email)", " / ".join(f"{FL['true_roi'][c]:.2f}" for c in CH), " / ".join(f"{SM['true_roi'][c]:.2f}" for c in CH)],
    ["True marginal ROI at +10% spend (TV / digital / email)", " / ".join(f"{FL['true_marginal_roi'][c]:.2f}" for c in CH), " / ".join(f"{SM['true_marginal_roi'][c]:.2f}" for c in CH)],
    ["True effect of moving 15% of TV to digital + email", SP(FL["true_delta"], 3), SP(SM["true_delta"], 3)],
])
para("The true effect is negative because the pro-rata split sends about 87% of the moved dollars to digital, whose true marginal ROI (about 1.7) is below TV's (about 2.4 to 2.6); only the 13% that goes to email, with a high marginal ROI (3.75), earns more than TV.")
H("4.4 Relation to the case exhibits", 2)
table(["Case exhibit", "How my data relates"], [
    ["Exhibit 1: TV weekly (Mon-Sun); digital/email and sales monthly", "Reproduced exactly: TV file weekly with Monday week_commencing; the other three monthly on the 1st."],
    ["Exhibit 2: TV 22%, digital 19%, email 11% ('high efficiency')", "Not copied. My truth is 18 / 14 / 6% so I can score estimates. The memo's 'email is high efficiency' is mirrored by email's high AVERAGE ROI (about 10), but its marginal ROI is much lower (3.75) and a pro-rata move sends it only 13% of the money."],
])
H("4.5 Limitations of the data", 2)
bullets(["The truth and the severity of TV flighting are my design choices; findings validate a method and a mechanism, not the real brand.",
         "Only three channels, no price, promotion, competitor, HCP or reimbursement effects; low correlation between channels by construction (real plans are more collinear).",
         "Even daily spread inside weeks and months; real delivery is uneven.",
         "No restatements, missing weeks, currency changes or vendor format changes.",
         "48 monthly observations only; adstock is daily in truth but monthly in the model.",
         "Noise is Gaussian and independent; real sales have autocorrelated shocks."])

# ================================================================== 5
H("5. Evaluation", 1)
H("5.1 Metrics and tests used", 2)
table(["Metric", "Definition", "Why"], [
    ["Contribution error (points)", "modelled share of sales minus true share", "Direct accuracy against the answer key"],
    ["Bias / RMSE over worlds", "mean and root-mean-square of the error over simulated worlds", "Separates systematic bias from noise"],
    ["Paired difference (naive - correct)", "per world, same data except the calendar; mean and SD", "Isolates the effect of the calendar alone"],
    ["Interval coverage", "share of worlds in which the 90% interval contains the truth", "Tests whether stated confidence is honest (nominal 90%)"],
    ["Decision metrics", "median change in sales from the 15% move; P(change > 0); share of worlds with a confident gain (5th percentile > 0)", "What the client actually acted on"],
    ["Unit and integration tests", "33 pytest tests (5.7)", "Guard invariants and catch regressions"],
    ["Validation and LLM verification outcomes", "pass/fail per check; VERIFIED / ADVISORY / REJECTED / CONTRADICTED per claim", "Operational safeguards"],
])
for label, res in (("5.2 Scenario A: heavily flighted TV (seed 7)", FL), ("5.3 Scenario B: steady TV (seed 7)", SM)):
    H(label, 2)
    para("Channel contributions (share of window sales, 90% bootstrap interval):", italic=True)
    contrib_table(res)
    para("Average and marginal return per dollar:", italic=True)
    roi_table(res)
    para("Sales impact of moving 15% of TV into digital + email:", italic=True)
    realloc_table(res)
    para(f"Robustness over {res['sweep']['n_seeds']} re-simulated worlds:", italic=True)
    sweep_table(res)
H("5.4 What the two scenarios say", 2)
bullets([
    ("Scenario A (pulsed TV). ", f"The calendar error is second-order: the naive-minus-correct difference in channel share has mean {FL['sweep']['channels']['tv']['paired_diff_mean']*100:+.1f} pts and SD {FL['sweep']['channels']['tv']['paired_diff_sd']*100:.1f} pts for TV (versus a mean CI width of about {FL['sweep']['channels']['tv']['correct']['mean_width']*100:.0f} pts). Both versions over-credit TV and under-credit digital by similar amounts, a shared model bias. Both say the shift loses sales."),
    ("Scenario B (steady TV). ", f"The naive calendar injects spurious month-to-month swings into TV (a month with five Mondays gets five weeks of spend, a month with four gets four). The model cannot connect those swings to sales and shrinks TV's credit: TV share bias {SM['sweep']['channels']['tv']['naive']['bias']*100:+.1f} pts naive versus {SM['sweep']['channels']['tv']['correct']['bias']*100:+.1f} pts correct, and the naive version recommends the shift (mean median impact {SP(SM['sweep']['realloc']['naive']['mean_median_delta'])}, confident gain in {P(SM['sweep']['realloc']['naive']['pct_seeds_confidently_positive'], 0)} of worlds) while the truth is negative in every world. Correct calendar: {SP(SM['sweep']['realloc']['correct']['mean_median_delta'])}, never a confident gain."),
    ("Caveat in scenario B. ", f"With steady TV the correct series itself has little variation, so TV is weakly identified (single-run 90% interval for TV share {ci(SM['fits']['correct']['channels']['tv']['lo'], SM['fits']['correct']['channels']['tv']['hi'])}%, P(gain) {P(SM['fits']['correct']['realloc']['p_positive'], 0)}). The correct pipeline's honest answer there is 'cannot tell', not 'the shift is bad'."),
    ("Answer to the case question. ", "Does the calendar mismatch change the recommendation already acted on? It can: where TV phasing is steady it creates a pro-shift signal that disappears once weeks are apportioned. Does the 15% shift still hold? Not on this evidence: the correct calendar never produced a confident gain in any simulated world, and the true effect was negative in all of them. Confidence: high that it is not demonstrated; low on the exact size."),
])
H("5.5 Sensitivity to the scenario (10 worlds each, point fits)", 2)
table(["Scenario", "Bias naive (TV/Dig/Email, pts)", "Bias correct", "Mean naive-correct (pts)", "SD naive-correct (pts)", "Mean impact naive / correct / true"],
      [[o["scenario"], " / ".join(f"{x:+.1f}" for x in o["bias_naive_pts"]), " / ".join(f"{x:+.1f}" for x in o["bias_correct_pts"]),
        " / ".join(f"{x:+.1f}" for x in o["paired_mean_pts"]), " / ".join(f"{x:.1f}" for x in o["paired_sd_pts"]),
        f"{o['delta_naive_pct']:+.2f}% / {o['delta_correct_pct']:+.2f}% / {o['delta_true_pct']:+.2f}%"] for o in SEN], size=8.5)
para("Reading: the calendar effect is largest when TV has no real flighting (naive TV share bias -8.8 pts, SD of the paired difference 7.0 pts). With matched saturation the model's bias shrinks (TV +2 to +3 pts), showing most of the shared error in scenario A is saturation misspecification and not the calendar.")
H("5.6 Uncertainty and how far to trust the intervals", 2)
bullets([f"Single-run intervals are bootstrap 90% intervals with {FL['n_boot']} refits.",
         f"Measured coverage: scenario A TV {P(FL['sweep']['channels']['tv']['naive']['coverage90'], 0)} (naive) and {P(FL['sweep']['channels']['tv']['correct']['coverage90'], 0)} (correct) against a nominal 90%; scenario B TV {P(SM['sweep']['channels']['tv']['naive']['coverage90'], 0)} and {P(SM['sweep']['channels']['tv']['correct']['coverage90'], 0)}. Intervals are therefore optimistic in A, honest in B (correct) and poor for naive.",
         "Source of under-coverage in A: model misspecification (fixed saturation scale; monthly instead of daily adstock), which a residual bootstrap cannot see.",
         "Direction of the decision metric is more reliable than any interval: across all worlds in both scenarios the true effect of the shift was negative."])
H("5.7 Automated tests (33)", 2)
inv = []
for f in sorted((ROOT / "tests").glob("test_*.py")):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
            inv.append([f.name, n.name, (ast.get_docstring(n) or n.name.replace("test_", "").replace("_", " "))])
table(["File", "Test", "What it asserts"], inv, size=8)
para(f"Result: {len(inv)} tests collected, all passing (uv run pytest). Coverage includes: straddling-week split 300/400, naive vs week-ending anchor, leap-February conservation, truth shares within 5% of configuration, grain of published files, seed reproducibility, zero-move counterfactual equals zero, "
     "the validator catching Tuesday-start weeks, week gaps, period-end dates, 28-day fiscal-style dates, missing months, mismatched month sets, short coverage and duplicates, a failed validation blocking the pipeline, the drift check, "
     "adstock arithmetic, non-negative coefficients, bootstrap determinism, spend conservation under reallocation, R-squared above 0.9, the LLM verifier rejecting an invented quote, catching a quoted-but-misread claim, ignoring whitespace/case in quote matching, refusing to act on unverified claims, flagging a spec that lies about the data and escalating any contradiction to human review.")
H("5.8 Validation gate results on the delivered files", 2)
para("Scenario A refresh:", italic=True)
validation_table(FL)
para("Scenario B refresh (the drift line differs because TV phasing differs):", italic=True)
table(["Status", "Check", "Detail"], [[c["status"], c["name"], c["detail"]] for c in SM["validation"] if "drift" in c["name"].lower()], size=8.5)
H("5.9 Mid-session update", 2)
para("No mid-session update was received, so none is reflected. [Author note: describe the update and its effect on this solution here if one was issued.] "
     "The nearest equivalent is the change of direction in decision-log step 2 (Section 3.4): after the first full run showed a negligible calendar effect, I added scenario B and the sensitivity script, which changed the main message from 'the calendar is second-order' to 'it depends on TV phasing, and for steady TV it manufactures the recommendation'. "
     "The pipeline is parameterised (seed, bootstrap count, reallocation fraction, scenario, spec directory, LLM backend) so a changed brief can be re-run with one command.")

# ================================================================== 6
H("6. Tech stack", 1)
libs = ["numpy", "pandas", "scipy", "matplotlib", "pytest", "openai", "anthropic", "python-dotenv", "python-pptx", "python-docx"]
ver = []
for l in libs:
    try:
        ver.append([l, metadata.version(l)])
    except Exception:
        ver.append([l, "n/a"])
table(["Layer", "Choice", "Version"], [["Language", "Python", sys.version.split()[0]], ["Package / env manager", "uv (pyproject.toml, uv.lock)", "-"]] + [[("Numerics" if l in ("numpy", "pandas", "scipy") else "Plotting" if l == "matplotlib" else "Testing" if l == "pytest" else "LLM client" if l in ("openai", "anthropic", "python-dotenv") else "Collateral generation"), l, v] for l, v in ver])
bullets(["Own implementations: geometric adstock (scipy.signal.lfilter), exponential saturation, NNLS with Frisch-Waugh controls, residual bootstrap, apportioning, validators, HTML renderer (inline SVG, no JavaScript).",
         "Infrastructure: local execution on Windows 11 only. No servers, databases or cloud services. Secrets in a git-ignored .env file; the project folder is not a git repository.",
         f"Run time: the full pipeline for one scenario including the sweep takes a few minutes on a laptop CPU (not formally benchmarked); the 33 tests take about 1 to 3 seconds."])
H("6.1 Every LLM used", 2)
table(["Provider", "Model (id as used)", "Role", "Parameters", "Status"], [
    ["Groq (free tier)", "openai/gpt-oss-120b (Groq-served id; no finer version pin available from the API)", "Spec-claim extraction", "temperature 0, JSON mode (response_format json_object), single call per run", f"Used live for the reported runs and live adversarial test"],
    ["OpenAI", "gpt-4o-mini (configured default)", "Same", "same", "Backend implemented. Key returned HTTP 429 'no credits remaining', so not used"],
    ["Anthropic", "claude-sonnet-5-5 (configured default, env override MMM_LLM_MODEL)", "Same", "max_tokens 3000", "Backend implemented; no key available, not exercised"],
    ["Offline mock", "MockLLM (faithful and flawed modes, in mmm/spec_llm.py)", "Deterministic stand-in", "none", "Used by all 33 tests, no network"],
    ["Groq (earlier attempt)", "llama-3.3-70b-versatile", "Same", "-", "Returned HTTP 404 (not available to the key); abandoned"],
])

# ================================================================== 7
H("7. Use of LLMs", 1)
H("7.1 Where the LLM sits", 2)
para("Only in step 4 (spec reading). It never touches the numbers, the aggregation or the model. Input: the three vendor specification texts (data/vendor_specs/). Output: JSON claims. Everything downstream is code.")
H("7.2 Why an LLM rather than rules or code", 2)
bullets(["Vendor specifications are free text and their wording differs by vendor; the risky statements ('a week may straddle two months', 'Late invoices may restate prior weeks', 'no day-count normalisation is applied') have no fixed syntax. Regex would need rewriting per vendor and would miss paraphrases.",
         "A new vendor or a revised spec version can be screened in seconds, producing a diffable list of claims.",
         "Why not trust it: a wrong calendar assumption is exactly the failure this case is about. So the LLM is only a reader; two independent code-based gates decide what is accepted."])
H("7.3 Prompt and output contract", 2)
mono(PROMPT.replace("{fields}", "<FIELDS JSON>").replace("{specs}", "<SPEC TEXTS, each under '### SOURCE: <name>'>"))
table(["Field", "Allowed values"], [[k, ", ".join(v)] for k, v in FIELDS.items()])
para("Sources covered: " + ", ".join(f"{k} (file {v[0]}, date column {v[1]})" for k, v in SOURCES.items()) + ". Output is parsed from the first '{' to the last '}'; claims with missing keys or unknown fields are dropped.")
H("7.4 Grounding and evaluation protocol", 2)
numbered([
    ("Gate 1, grounding. ", "The quote must be at least 8 characters and appear verbatim in that source's spec after normalising whitespace and case and trimming a trailing full stop. Otherwise REJECTED_UNGROUNDED and no data test is run."),
    ("Gate 2, data test. ", "A deterministic test on the delivered file (table below). If it disagrees the claim is CONTRADICTED_BY_DATA."),
    ("Claims with no test. ", "Risk statements such as restatements or day-count normalisation are ADVISORY and listed for a human."),
    ("Action control. ", "derive_actions() lets only VERIFIED claims change behaviour: apportioning is enabled only if TV grain = weekly AND a week-start day is verified AND digital, email and sales are verified monthly. Any contradiction sets needs_human_review and lists the conflicts."),
])
table(["Claim field", "Deterministic data test"], [
    ["grain = weekly", "all consecutive date gaps equal 7 days"], ["grain = monthly", "all dates on the 1st and gaps between 28 and 31 days"],
    ["week_start_day = X", "every date's weekday name equals X"], ["date_semantics = week_start / week_end", "every date is a Monday / a Sunday"],
    ["date_semantics = month_start / month_end", "every date is the 1st / a month end"], ["calendar = calendar_month", "all dates on the 1st"],
    ["calendar = broadcast", "at least one week straddles a month boundary (needs apportioning)"], ["risk = weeks_straddle_months", "count of weeks whose last day falls in a different month than the first"]])
H("7.5 Results", 2)
claims_table(FL)
bullets([f"Live run ({FL['spec_check']['llm']}): {FL['spec_check']['tally']}.",
         "Adversarial live test (not in the repo's automated tests because it needs the network): I edited the TV spec to say the date is 'the Sunday on which the buying week ends'. The model reported date_semantics = week_end faithfully; the data test found 0% of dates are Sundays, so the claim was CONTRADICTED_BY_DATA and the run raised a human-review flag. Outcome with that spec: 13 verified, 1 contradicted, 2 advisory.",
         "Offline flawed mock (automated): injects an invented quote 'Weeks run Sunday to Saturday.' (rejected by Gate 1) and two real-quote misreads, week_end and month_end (caught by Gate 2). All three are asserted in tests/test_spec_llm.py.",
         "Spec-lies-about-data test (automated): the file ships Tuesday-start weeks while the spec says Monday; the week_start_day = Monday claim is contradicted and apportioning is not triggered."])
H("7.6 Known failure modes", 2)
table(["Failure mode", "Mitigation in the build", "Residual risk / not covered"], [
    ["Invented or paraphrased quote", "Gate 1 verbatim match (conservative: paraphrases are also rejected)", "None for acceptance; may reject a correct claim"],
    ["Correct quote, wrong value", "Gate 2 data test where a test exists", "Claims with no test (restatements, day-count) rely on human review"],
    ["Omission of an important risk", "None automated", "Main gap: recall was not measured because I did not build a labelled claim set. Proposed: label 20 vendor specs, measure recall of risk claims, and add a checklist of mandatory fields that must be extracted or explicitly marked absent"],
    ["Spec and data agree but both are semantically wrong", "None", "Tests check the shape of dates, not their meaning (e.g. a 'Monday' that is really a posting date)"],
    ["Prompt injection inside a vendor file", "Output restricted to constrained JSON; only verified claims act", "Not tested adversarially"],
    ["Non-determinism and model drift", "temperature 0; pinned model id in the run record", "Only one live model tested; provider may change the served model"],
    ["Data egress of confidential specs", "Only spec text is sent, never numbers", "Needs an enterprise endpoint with zero retention for real specs (Section 8)"],
    ["Cost and latency", "One call per refresh", "Not measured"],
])

# ================================================================== 8
H("8. Limitations and next steps", 1)
H("8.1 What would change for a real client deployment", 2)
table(["Area", "Limitation now", "Change for production"], [
    ["Data", "Synthetic; truth designed by me", "Ingest real vendor feeds; request daily or weekly digital, email and sales; confirm how the client pipeline mapped weeks to months (Monday, Sunday, 4-4-5)"],
    ["Model", "Small custom MMM; fixed saturation; monthly adstock; 48 points", "Bayesian MMM (Meridian or Robyn) with priors, estimated saturation, promotions, price, competitor and seasonality controls; calibrate to geo or lift experiments; report marginal ROI and budget-optimiser output"],
    ["Uncertainty", "Bootstrap under-covers (TV 25% in scenario A)", "Posterior predictive checks, rolling-origin holdout, coverage monitoring; present results as ranges with the coverage caveat"],
    ["Phasing", "Even daily spread", "Use delivered daily or flight-level data; else test sensitivity to front-loaded or back-loaded phasing"],
    ["Restatements", "Not simulated", "Version the weekly file; re-run on restated weeks; alert on changes to past weeks"],
    ["LLM", "Recall unmeasured; one live model", "Labelled claim set; mandatory-field checklist; two-model agreement for high-impact claims; stored prompts and outputs"],
    ["Decision", "One shift tested", "Optimise the split between digital and email by marginal ROI instead of pro-rata; test staged moves with holdout geographies"],
])
H("8.2 Data privacy", 2)
bullets(["The model uses aggregated spend and sales by week or month. No patient-level, HCP-level or prescriber-level data is needed or used; keep it that way and document it in the data protection impact assessment.",
         "Vendor specifications and contracts can be commercially confidential. Before sending real specs to any LLM use an enterprise endpoint with zero data retention and a data processing agreement, or a self-hosted model; redact prices, names and contract terms where they do not affect calendar or grain.",
         "Sales for a pharmaceutical brand may be market-sensitive: restrict outputs to the account team and avoid pasting figures into consumer AI tools.",
         "Free-tier endpoints (used here for testing) may retain prompts and must not be used with real specs."])
H("8.3 Security", 2)
bullets(["Secrets: move API keys to a secret manager; never commit .env. The Groq key used in this build was pasted into a chat and should be rotated.",
         "Least-privilege access to raw vendor files; read-only mounts for the pipeline; no write access to source feeds.",
         "Pin dependency versions (uv.lock) and scan them; pin and record the LLM model id and prompt hash for every run.",
         "Log every LLM request and response and every verdict for audit; treat spec text as untrusted input (prompt-injection hygiene)."])
H("8.4 Monitoring", 2)
bullets(["Run the validation gate on every refresh and fail closed; page the owner on any error.",
         "Track the calendar-drift statistic per refresh; a change signals a vendor mapping change.",
         "Re-run the LLM reader whenever a spec version changes and diff the claim set; require human sign-off on any new or contradicted claim.",
         "Monitor coefficient and contribution drift between refreshes, interval coverage on held-out months, and the share of spend per channel against plan.",
         "Alert when weekly TV variation falls (steady TV is the scenario in which the calendar error is most damaging)."])
H("8.5 Immediate next steps for this case (before the Q3 readout)", 2)
numbered(["Re-run the quarterly refresh with TV apportioned by day and compare to the numbers behind the memo.",
          "Compute the coefficient of variation of the client's weekly TV spend: if low, treat scenario B as the relevant world.",
          "Ask the vendor how weeks were mapped to months in the original build and for daily phasing.",
          "Present the shift as under review, not data-backed; show the range of outcomes and the coverage caveat.",
          "Deploy the validation gate and LLM spec reader on the next refresh."])

# ================================================================== 9
H("9. Submission index", 1)
H("9.1 Files", 2)
table(["File", "What it is", "How to run / open"], [
    ["run_pipeline.py", "End-to-end run: generate, validate (gate), LLM spec check, fit naive and correct, sweep, HTML report, JSON", "uv run python run_pipeline.py --sweep 12 --llm groq   (add --scenario smooth for scenario B; --llm mock for offline)"],
    ["run_sensitivity.py", "Four-scenario sensitivity study (10 worlds each)", "uv run python run_sensitivity.py  -> outputs/sensitivity.json"],
    ["mmm/generator.py", "Daily-truth generator, vendor-file writer, true reallocation effect and true marginal ROI", "imported"],
    ["mmm/aggregate.py", "Naive (start/end anchor) and apportioned weekly-to-monthly aggregation", "imported"],
    ["mmm/model.py", "Adstock + saturation MMM, NNLS, bootstrap, counterfactual, marginal ROI", "imported"],
    ["mmm/validate.py", "Grain and calendar validation checks", "imported"],
    ["mmm/spec_llm.py", "LLM spec reader (Groq, OpenAI, Anthropic, mock), grounding and data verification, action rules", "via run_pipeline.py --llm ..."],
    ["mmm/pipeline.py, mmm/experiment.py, mmm/report.py", "Pipeline glue, multi-world sweep, HTML renderer", "imported"],
    ["tests/ (conftest.py + 5 test files)", "33 pytest tests", "uv run pytest"],
    ["data/*.csv, data/scenario_smooth/*.csv", "Generated vendor files for scenario A and B", "written by run_pipeline.py"],
    ["data/vendor_specs/*.txt", "TV, digital/email and sales vendor specifications (LLM input)", "read by run_pipeline.py"],
    ["outputs/report.html (+ build_report.py, mmm/report_combined.py)", "Combined before-and-after HTML view of both TV scenarios (tabs): contributions, ROI, reallocation, drift, sweep, validation and LLM claims", "open in a browser; regenerate with uv run python build_report.py"],
    ["outputs/report_flighted.html, outputs/report_smooth.html", "Single-scenario HTML pages written by run_pipeline.py", "open in a browser"],
    ["outputs/results.json, results_smooth.json, sensitivity.json", "All numbers behind this document, the report and the slides", "written by the scripts"],
    ["outputs/slides.pptx, build_slides.py", "8-slide storytelling deck, white and green, with speaker notes", "uv run python build_slides.py"],
    ["outputs/Solution_Document.docx, build_doc.py", "This document, generated from the result files", "uv run python build_doc.py"],
    [".env (not submitted), pyproject.toml, uv.lock", "Secrets (GROQ_API_KEY) and pinned dependencies", "create .env with GROQ_API_KEY=... for live LLM runs"],
])
H("9.2 Reproduction steps", 2)
mono("# 1. install uv, then from the project folder (dependencies install automatically):\n"
     "uv run pytest                                          # 33 tests, no network\n"
     "uv run python run_pipeline.py --sweep 12 --llm mock   # scenario A, offline\n"
     "uv run python run_pipeline.py --sweep 12 --llm mock --scenario smooth\n"
     "uv run python run_sensitivity.py\n"
     "uv run python build_slides.py && uv run python build_doc.py\n"
     "# live LLM: put GROQ_API_KEY in .env and use --llm groq   (OPENAI_ENV_FILE=<path to .env> with --llm openai)")
para("All runs are deterministic for a given seed (main seed 7; sweep seeds 0 to 11); LLM output is the only non-deterministic element and does not affect the numerical results, only the claims table.")
H("9.3 Glossary", 2)
table(["Term", "Meaning"], [
    ["MMM", "Marketing mix model: statistical model of each channel's contribution to sales"],
    ["Broadcast / media calendar", "Weeks Monday to Sunday grouped 4-4-5; does not align with calendar months"],
    ["Grain", "Time resolution of a dataset (daily, weekly, monthly)"],
    ["Apportioning", "Spreading a week's spend over its days and summing by calendar month"],
    ["Adstock", "Carry-over: a channel's effect persists and decays after the spend"],
    ["Saturation", "Diminishing returns on additional spend"],
    ["Average vs marginal ROI", "Sales per dollar over all spend vs sales from one additional dollar"],
    ["Lift", "Extra effect above what would have happened anyway"],
    ["Bootstrap interval", "Range of an estimate from refitting on resampled residuals"],
    ["Coverage", "How often a nominal interval contains the true value"],
    ["Ground truth", "The known true effect built into the synthetic data"],
])

out = OUT / "Solution_Document_full.docx"
try:
    doc.save(out)
except PermissionError:  # file is open in Word: keep the old copy, write a new one beside it
    out = OUT / "Solution_Document_full_alt.docx"
    doc.save(out)
print("saved", out)
