"""Builds outputs/Solution_Document.docx (compact version) from the pipeline outputs.
(build_doc_full.py builds the long, exhaustive variant.)
Run:  uv run python build_doc.py   (after both run_pipeline.py scenarios and run_sensitivity.py)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

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
rn_f, rc_f = FL["fits"]["naive"]["realloc"], FL["fits"]["correct"]["realloc"]
rn_s, rc_s = SM["fits"]["naive"]["realloc"], SM["fits"]["correct"]["realloc"]
sw_f, sw_s = FL["sweep"], SM["sweep"]

doc = Document()
st = doc.styles["Normal"]
st.font.name, st.font.size = "Calibri", Pt(10.5)
for lvl, size in ((1, 16), (2, 12.5)):
    h = doc.styles[f"Heading {lvl}"]
    h.font.name, h.font.size, h.font.color.rgb, h.font.bold = "Calibri", Pt(size), GREEN, True
for s in doc.sections:
    s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Pt(64)


def shade(cell, hex_):
    pr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hex_)
    pr.append(sh)


def para(t, lead=None, style=None):
    p = doc.add_paragraph(style=style)
    if lead:
        p.add_run(lead).bold = True
    p.add_run(t)
    p.paragraph_format.space_after = Pt(4)


def bullets(items):
    for it in items:
        para(it[1], lead=it[0], style="List Bullet") if isinstance(it, tuple) else para(it, style="List Bullet")


def table(header, rows):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size, r.font.color.rgb = True, Pt(9.5), RGBColor(255, 255, 255)
        shade(c, "1B7F4B")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(9.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ---------------------------------------------------------------- title
t = doc.add_paragraph()
r = t.add_run("The Two Calendars: Solution Document")
r.bold, r.font.size, r.font.color.rgb = True, Pt(22), GREEN
para("Case 3 · Pharma (diabetes) · Marketing mix modelling · FDE associate submission")

# ---------------------------------------------------------------- 1
doc.add_heading("1. Solution overview", 1)
para("The client's MMM joins TV spend reported by Monday-to-Sunday media weeks with digital, email and sales reported by calendar month. "
     "If weeks are assigned to months naively, TV spend lands in the wrong month. The Brand Director has already acted on a recommendation to move 15% of TV spend to digital and email, so the question is whether that error changes it.")
para("I built a reproducible pipeline: a synthetic data generator with a known true effect per channel, naive and day-level (apportioned) aggregation, "
     "an adstock-and-saturation MMM with a 300-fit bootstrap, a validation gate for grain and calendar, and an LLM that reads vendor specifications with every claim verified against the delivered files.")
para(f"Main result: the 15% shift is not supported by the data. When TV spend is steady the calendar error manufactures the recommendation: the naive calendar reports a sales gain of {SP(rn_s['median'])} "
     f"(P(gain) {P(rn_s['p_positive'], 0)}) against a truth of {SP(SM['true_delta'])}, and showed a confident gain in {P(sw_s['realloc']['naive']['pct_seeds_confidently_positive'], 0)} of {sw_s['n_seeds']} simulated worlds versus 0% for the correct calendar. "
     f"When TV is heavily pulsed the calendar is second-order and both versions say the shift loses sales ({SP(rn_f['median'])} naive, {SP(rc_f['median'])} correct, truth {SP(FL['true_delta'])}). "
     f"Confidence is high that the shift is not demonstrated and low on its exact size, because the bootstrap intervals covered the true TV share only {P(sw_f['channels']['tv']['correct']['coverage90'], 0)} of the time in the pulsed world.")

# ---------------------------------------------------------------- 2
doc.add_heading("2. Approach and methodology", 1)
steps = [
    ("Generate data with a known truth. ", "Simulate daily spend and sales, then publish them in vendor grain (TV weekly, the rest monthly). Needed so every estimate can be scored against a true value, including the true effect of the 15% shift."),
    ("Reproduce the error. ", "Naive: a whole week goes to the month of its Monday. Correct: each week's spend is split over its 7 days and summed by calendar month; total spend is conserved."),
    ("Validate every refresh. ", "Twenty checks on grain and calendar (week starts Monday, 7-day spacing, month-start dates, no missing months, window coverage, spend conservation, calendar-drift warning). Errors block the model fit."),
    ("Read vendor specs with an LLM and verify. ", "The LLM extracts calendar and grain claims; a claim acts only if its quote appears verbatim in the spec and a test on the delivered file agrees."),
    ("Fit an MMM on both versions. ", "Per-day sales = intercept + trend + two seasonal harmonics + sum of beta x saturation(adstock(spend)); geometric adstock over a decay grid, exponential saturation with a fixed scale, non-negative betas by NNLS."),
    ("Quantify uncertainty. ", "Residual bootstrap, 300 refits per version, re-running the decay search each time; 90% intervals."),
    ("Answer the business question. ", "Counterfactual: cut TV by 15% and add the money to digital and email pro-rata to current spend; report the change in total sales, its interval and P(change > 0), and compare with the truth from the generator."),
    ("Test robustness. ", f"Repeat over {sw_f['n_seeds']} re-simulated worlds per scenario and four sensitivity scenarios, to separate systematic bias from noise."),
]
for i, (a, b) in enumerate(steps, 1):
    para(b, lead=f"{i}. {a}")

# ---------------------------------------------------------------- 3
doc.add_heading("3. How I arrived at it", 1)
para("Alternatives considered and rejected:", lead="")
bullets([
    ("Meridian, Robyn or PyMC. ", "Heavier installs and slower iteration here, and I needed control of adstock and the bootstrap so the two runs differ only in the calendar. Recommended for a real deployment."),
    ("Weekly model. ", "Sales are monthly; splitting them into weeks would invent data."),
    ("Estimating saturation. ", "48 points and three channels cannot identify it, so its scale is fixed (a stated misspecification)."),
    ("Regex-only spec parsing or letting the LLM decide. ", "Regex is brittle across vendors; an unchecked LLM adds risk to the very failure being fixed. The LLM reads, code verifies."),
    ("Adapting Robyn or Meridian sample data. ", "They have no known true effects for the counterfactual; the case allows synthetic data."),
])
para("Key assumptions:", lead="")
bullets([
    "Spend is spread evenly across the days of a week and of a month.",
    "The naive pipeline anchors a week to the month of its Monday (a week-ending variant is implemented too).",
    "Moved TV dollars go to digital and email pro-rata to current spend.",
    "The true effects (TV 18%, digital 14%, email 6%) are my design and are not calibrated to Exhibit 2 (22 / 19 / 11%), which is the client's model output and not a ground truth.",
])
para("I ran two TV phasings (pulsed and steady) after a first run showed little calendar effect, and I report both; I also reduced digital budget seasonality once (0.15 to 0.04) because it was collinear with the model's seasonal controls. "
     "No Clarification Desk answers were provided, so none are relied on. [Author note: add any desk answers here.]", lead="Changes of direction. ")

# ---------------------------------------------------------------- 4
doc.add_heading("4. Data", 1)
para("All data are synthetic, generated at daily grain (seed 7) and published in vendor shape. Nothing was adapted from Robyn or Meridian.")
table(["Item", "Specification"], [
    ["Span", "210 vendor weeks (Mon 2021-12-27 to Sun 2026-01-04); modelled window Jan 2022 to Dec 2025 = 48 calendar months"],
    ["TV", "Weekly spend, mean $480k/week, spread evenly over 7 days. Scenario A (pulsed): on/off flights of 2 to 4 weeks at 0.15x to 2.3x. Scenario B (steady): about 15% week-to-week variation"],
    ["Digital / email", "Monthly budgets, mean $1,650k and $250k, log-normal noise (sd 0.35), spread evenly over the month's days"],
    ["Baseline", "$820k/day, +4%/yr trend, ±10% seasonality; 2% noise on monthly sales"],
    ["True response", "Daily geometric adstock (TV 0.95, digital 0.85, email 0.70) then 1 - exp(-adstock/s)"],
    ["True share of sales", "TV 18%, digital 14%, email 6% (betas calibrated so realised shares match; tested within 5%)"],
    ["True effect of the 15% shift", f"{SP(FL['true_delta'])} (A) and {SP(SM['true_delta'])} (B), from re-running the true daily process"],
    ["Files", "tv_media_weekly.csv (week_commencing, spend_usd_k), digital_monthly.csv, email_monthly.csv, sales_monthly.csv, plus three vendor spec texts"],
])
para("Limitations: truth and flighting severity are my design; low channel correlation by construction; no promotions, price or competitors; no restatements; even daily spread; only 48 observations; adstock is daily in truth but monthly in the model.")

# ---------------------------------------------------------------- 5
doc.add_heading("5. Evaluation", 1)
para("Metrics: contribution error against truth, bias and RMSE over worlds, the paired naive-minus-correct difference (isolates the calendar), 90% interval coverage, and decision metrics (median sales impact, P(impact > 0), share of worlds with a confident gain).")
table(["Result (seed 7)", "A: pulsed TV", "B: steady TV"], [
    ["True effect of the shift", SP(FL["true_delta"]), SP(SM["true_delta"])],
    ["Naive: impact (median) [90% CI] / P(>0)", f"{SP(rn_f['median'])} {ci(rn_f['lo'], rn_f['hi'], 2)} / {P(rn_f['p_positive'], 0)}", f"{SP(rn_s['median'])} {ci(rn_s['lo'], rn_s['hi'], 2)} / {P(rn_s['p_positive'], 0)}"],
    ["Correct: impact (median) [90% CI] / P(>0)", f"{SP(rc_f['median'])} {ci(rc_f['lo'], rc_f['hi'], 2)} / {P(rc_f['p_positive'], 0)}", f"{SP(rc_s['median'])} {ci(rc_s['lo'], rc_s['hi'], 2)} / {P(rc_s['p_positive'], 0)}"],
    ["TV share: truth / naive / correct", f"{P(FL['true_shares']['tv'])} / {P(FL['fits']['naive']['channels']['tv']['share'])} / {P(FL['fits']['correct']['channels']['tv']['share'])}", f"{P(SM['true_shares']['tv'])} / {P(SM['fits']['naive']['channels']['tv']['share'])} / {P(SM['fits']['correct']['channels']['tv']['share'])}"],
    ["Digital share: truth / naive / correct", f"{P(FL['true_shares']['digital'])} / {P(FL['fits']['naive']['channels']['digital']['share'])} / {P(FL['fits']['correct']['channels']['digital']['share'])}", f"{P(SM['true_shares']['digital'])} / {P(SM['fits']['naive']['channels']['digital']['share'])} / {P(SM['fits']['correct']['channels']['digital']['share'])}"],
    ["Marginal ROI TV / digital / email: truth", " / ".join(f"{FL['true_marginal_roi'][c]:.2f}" for c in CH), " / ".join(f"{SM['true_marginal_roi'][c]:.2f}" for c in CH)],
    ["Marginal ROI: correct calendar", " / ".join(f"{FL['fits']['correct']['marginal_roi'][c]:.2f}" for c in CH), " / ".join(f"{SM['fits']['correct']['marginal_roi'][c]:.2f}" for c in CH)],
])
table([f"{sw_f['n_seeds']} simulated worlds", "A: naive / correct", "B: naive / correct"], [
    ["TV share bias (points)", f"{sw_f['channels']['tv']['naive']['bias']*100:+.1f} / {sw_f['channels']['tv']['correct']['bias']*100:+.1f}", f"{sw_s['channels']['tv']['naive']['bias']*100:+.1f} / {sw_s['channels']['tv']['correct']['bias']*100:+.1f}"],
    ["SD of naive - correct TV share (points)", f"{sw_f['channels']['tv']['paired_diff_sd']*100:.1f}", f"{sw_s['channels']['tv']['paired_diff_sd']*100:.1f}"],
    ["90% interval covers true TV share", f"{P(sw_f['channels']['tv']['naive']['coverage90'], 0)} / {P(sw_f['channels']['tv']['correct']['coverage90'], 0)}", f"{P(sw_s['channels']['tv']['naive']['coverage90'], 0)} / {P(sw_s['channels']['tv']['correct']['coverage90'], 0)}"],
    ["Mean modelled impact of the shift", f"{SP(sw_f['realloc']['naive']['mean_median_delta'])} / {SP(sw_f['realloc']['correct']['mean_median_delta'])}", f"{SP(sw_s['realloc']['naive']['mean_median_delta'])} / {SP(sw_s['realloc']['correct']['mean_median_delta'])}"],
    ["Worlds showing a confident gain", f"{P(sw_f['realloc']['naive']['pct_seeds_confidently_positive'], 0)} / {P(sw_f['realloc']['correct']['pct_seeds_confidently_positive'], 0)}", f"{P(sw_s['realloc']['naive']['pct_seeds_confidently_positive'], 0)} / {P(sw_s['realloc']['correct']['pct_seeds_confidently_positive'], 0)}"],
    ["True effect negative in", f"{P(sw_f['realloc']['true_delta_sign_negative_share'], 0)} of worlds", f"{P(sw_s['realloc']['true_delta_sign_negative_share'], 0)} of worlds"],
])
bullets([
    ("Reading. ", f"With pulsed TV the calendar shifts a channel's share by only about ±2 points with no consistent sign, and both versions over-credit TV and under-credit digital by similar amounts (a shared misspecification). "
                  f"With steady TV, a month with five Mondays gets five weeks of spend and one with four gets four; the model blames TV for sales noise, so TV looks weak (share bias {sw_s['channels']['tv']['naive']['bias']*100:+.1f} pts) and the shift looks attractive."),
    ("Why the shift fails. ", "The pro-rata split sends about 87% of the moved money to digital, whose true marginal ROI (about 1.7) is below TV's (about 2.4 to 2.6). Email's average ROI looks high but only 13% of the money reaches it."),
    ("Sensitivity (10 worlds each). ", f"The calendar effect is largest with unflighted TV (SD of the paired TV difference {SEN[1]['paired_sd_pts'][0]:.1f} pts versus {SEN[0]['paired_sd_pts'][0]:.1f} pts in the default). With matched saturation the shared model bias shrinks (TV bias +{SEN[2]['bias_correct_pts'][0]:.1f} pts)."),
    ("Validation and tests. ", f"{sum(c['status']=='PASS' for c in FL['validation'])} of {len(FL['validation'])} checks pass and one is an intended warning (median monthly drift 11.8%, worst 66.8% at a window edge). 33 pytest tests pass, covering apportioning, the generator, every validator failure mode, the model and the LLM verifier."),
    ("Mid-session update. ", "None was received, so none is reflected. [Author note: describe it and its effect here if one was issued.] The pipeline is parameterised (seed, scenario, bootstrap size, LLM backend) so a changed brief re-runs with one command."),
])

# ---------------------------------------------------------------- 6
doc.add_heading("6. Tech stack", 1)
table(["Layer", "Choice"], [
    ["Language / env", f"Python {sys.version.split()[0]}, uv (pyproject.toml, uv.lock)"],
    ["Numerics and modelling", "numpy, pandas, scipy (NNLS, lfilter); own adstock, saturation, bootstrap and validators"],
    ["Testing", "pytest (33 tests)"],
    ["Reporting and collaterals", "HTML with inline SVG (no JavaScript), matplotlib, python-pptx, python-docx"],
    ["LLM clients", "openai SDK (OpenAI-compatible endpoints), python-dotenv; anthropic SDK backend implemented"],
    ["Infrastructure", "Local run on Windows 11; no servers or cloud services; secrets in a git-ignored .env"],
])
table(["LLM provider", "Model", "Use", "Status"], [
    ["Groq (free tier)", "openai/gpt-oss-120b (temperature 0, JSON mode)", "Spec-claim extraction", "Used live for the reported runs"],
    ["OpenAI", "gpt-4o-mini (default)", "Same", "Implemented; key returned HTTP 429 'no credits remaining', not used"],
    ["Anthropic", "claude-sonnet-5-5 (default)", "Same", "Implemented; no key available, not exercised"],
    ["Offline mock", "MockLLM (faithful and flawed modes)", "Deterministic tests", "Used in all 33 tests"],
])

# ---------------------------------------------------------------- 7
doc.add_heading("7. Use of LLMs", 1)
bullets([
    ("Where. ", "Only in spec reading: the LLM turns the three vendor specification texts into {source, field, value, quote} claims. It never touches numbers, aggregation or the model."),
    ("Why an LLM. ", "Specs are free text and differ by vendor; risky statements ('a week may straddle two months', 'Late invoices may restate prior weeks', 'no day-count normalisation is applied') have no fixed syntax. Regex would need rewriting per vendor."),
    ("Grounding. ", "Gate 1: the quote must appear verbatim in the spec (whitespace and case normalised), otherwise REJECTED_UNGROUNDED. Gate 2: a deterministic test on the delivered file (7-day gaps, weekday, day-of-month, straddling weeks) must agree, otherwise CONTRADICTED_BY_DATA. Only VERIFIED claims can change behaviour; any contradiction raises a human-review flag."),
    ("Evaluation. ", f"Live run ({FL['spec_check']['llm']}): {FL['spec_check']['tally'].get('VERIFIED', 0)} claims verified, {FL['spec_check']['tally'].get('ADVISORY', 0)} advisory (restatements; day-count normalisation, both need a human), none rejected. "
                     "Adversarial live test: I changed the TV spec to say the date is the Sunday the week ends; the model repeated it faithfully and the data test caught it (0% of dates are Sundays). "
                     "An offline flawed mock injects an invented quote and two misreads; all three are caught and asserted in tests."),
    ("Known failure modes. ", "Omissions are not detected and recall was not measured (no labelled claim set); claims with no data test rely on a human; spec and data can agree and both be semantically wrong; prompt injection was not tested; only one live model was tested."),
])

# ---------------------------------------------------------------- 8
doc.add_heading("8. Limitations and next steps", 1)
bullets([
    ("Real deployment. ", "Replace synthetic files with the vendor feeds, request daily or weekly digital, email and sales, and confirm how the client's pipeline mapped weeks to months. Move to a Bayesian MMM (Meridian or Robyn) with priors, estimated saturation, promotion and price controls, and lift-test calibration; report marginal ROI; optimise the digital/email split by marginal ROI instead of pro-rata."),
    ("Uncertainty. ", "The bootstrap under-covers in the pulsed world; add posterior predictive checks and rolling holdouts."),
    ("Data privacy. ", "The model uses aggregated spend and sales only, no patient- or HCP-level data. Vendor specs can be confidential: use an enterprise LLM endpoint with zero retention (or a self-hosted model) before sending real specs; free tiers must not be used with them."),
    ("Security. ", "Keep keys in a secret manager (the Groq key used here was pasted into a chat and should be rotated), least-privilege access to raw files, pinned dependencies and model ids, and an audit log of LLM inputs, outputs and verdicts."),
    ("Monitoring. ", "Run the validation gate on every refresh and fail closed; track the drift statistic and weekly TV variation (steady TV is the most exposed case); re-run the LLM reader when a spec changes and diff its claims; monitor coefficient drift and interval coverage on holdout months; version weekly files because late invoices can restate weeks."),
    ("Before the Q3 readout. ", "Re-run the refresh with TV apportioned by day, check how steady the client's weekly TV is, ask the vendor how weeks were mapped to months, and present the shift as under review, not data-backed."),
])

# ---------------------------------------------------------------- 9
doc.add_heading("9. Submission index", 1)
table(["File", "What it is", "How to run"], [
    ["run_pipeline.py", "End to end: generate, validate, LLM spec check, fit both versions, sweep, reports, JSON", "uv run python run_pipeline.py --sweep 12 --llm groq  (add --scenario smooth; --llm mock for offline)"],
    ["run_sensitivity.py", "Four-scenario sensitivity study", "uv run python run_sensitivity.py"],
    ["mmm/ (generator, aggregate, model, validate, spec_llm, pipeline, experiment, report, report_combined)", "The data generator, aggregation, MMM, validation, LLM reader and verifier, experiments and HTML rendering", "imported by the scripts"],
    ["tests/ (conftest + 5 files)", "33 pytest tests", "uv run pytest"],
    ["data/ (csv, scenario_smooth/, vendor_specs/)", "Generated vendor files for both scenarios and the three spec texts", "written by run_pipeline.py"],
    ["outputs/report.html", "Before-and-after HTML view of both scenarios (tabs)", "open in a browser; uv run python build_report.py"],
    ["outputs/results*.json, sensitivity.json", "All numbers behind the report, slides and this document", "written by the scripts"],
    ["outputs/slides.pptx", "8-slide storytelling deck (white and green, speaker notes)", "uv run python build_slides.py"],
    ["outputs/Solution_Document.docx", "This document", "uv run python build_doc.py (build_doc_full.py builds a longer variant)"],
])

out = OUT / "Solution_Document.docx"
try:
    doc.save(out)
except PermissionError:  # open in Word: write beside it instead
    out = OUT / "Solution_Document_new.docx"
    doc.save(out)
print("saved", out)
