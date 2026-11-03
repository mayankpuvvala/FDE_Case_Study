"""Builds outputs/slides.pptx: an 8-slide STORY (white + green) with speaker notes.
Run:  uv run python build_slides.py   (after run_pipeline.py for both scenarios)"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from mmm import aggregate as agg
from mmm.generator import GenConfig, generate

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
S = json.loads((OUT / "results_smooth.json").read_text())   # steady TV
FL = json.loads((OUT / "results.json").read_text())         # pulsed TV
GREEN, DARK, GREY, LIGHT, RED = "#1B7F4B", "#1F2A24", "#8A948E", "#E8F3EC", "#B42318"
rgb = lambda h: RGBColor.from_string(h.lstrip("#"))


# ------------------------------------------------------------------ charts
def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=DARK)


def chart_delta(res, path, xlim):
    fits = res["fits"]
    fig, ax = plt.subplots(figsize=(7.4, 3.3), dpi=200)
    for y, v, col in ((1, "naive", GREY), (0, "correct", GREEN)):
        d = fits[v]["realloc"]
        ax.errorbar(d["median"] * 100, y, xerr=[[(d["median"] - d["lo"]) * 100], [(d["hi"] - d["median"]) * 100]],
                    fmt="o", color=col, capsize=5, lw=3, ms=9)
        ax.text(xlim[1] - 0.05, y + 0.22, f"{d['median']*100:+.2f}%  ·  {d['p_positive']*100:.0f}% chance it helps",
                va="center", ha="right", color=DARK, fontsize=10)
    ax.plot(res["true_delta"] * 100, 0.5, "D", color=DARK, ms=10, label="Truth (answer key)", zorder=5)
    ax.axvline(0, color=DARK, lw=1.4)
    ax.set_yticks([1, 0], ["Naive calendar", "Correct calendar"], fontsize=11)
    ax.set_xlim(*xlim)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("Change in total sales from moving 15% of TV into digital + email (%)")
    ax.legend(frameon=False, loc="lower left")
    style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def drift(seed, flighting):
    ds = generate(GenConfig(seed=seed, tv_flighting=flighting))
    months = pd.DatetimeIndex(ds.sales_monthly.month_start)
    n = agg.align_to_months(agg.weekly_to_monthly_naive(ds.tv_weekly, "week_start", "spend"), months)
    c = agg.align_to_months(agg.weekly_to_monthly_apportioned(ds.tv_weekly, "week_start", "spend"), months)
    return months, ((n - c) / c * 100).values


def chart_drift(path, months, p):
    fig, ax = plt.subplots(figsize=(7.4, 3.3), dpi=200)
    ax.bar(range(len(p)), p, color=[GREEN if x >= 0 else GREY for x in p])
    ax.axhline(0, color=DARK, lw=1)
    ax.set_xticks(range(0, len(p), 6), [f"{months[i]:%b %y}" for i in range(0, len(p), 6)])
    ax.set_ylabel("TV spend booked to month:\nnaive vs correct (%)")
    style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ------------------------------------------------------------------ helpers
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def box(s, x, y, w, h, fill=None, shape=MSO_SHAPE.RECTANGLE):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.shadow.inherit = False
    sh.line.fill.background()
    if fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = rgb(fill)
    else:
        sh.fill.background()
    return sh


def text(s, x, y, w, h, content, size=18, bold=False, color=DARK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, it in enumerate(content if isinstance(content, list) else [content]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment, p.space_after = align, Pt(8)
        r = p.add_run()
        r.text = it
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, rgb(color), "Calibri"
    return tb


def slide(title, n, notes):
    s = prs.slides.add_slide(BLANK)
    box(s, 0, 0, 0.28, 7.5, GREEN)
    text(s, 0.7, 0.35, 12.0, 1.3, title, size=28, bold=True)
    text(s, 12.2, 7.0, 1, 0.4, str(n), size=11, color=GREY, align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes
    return s


def stat(s, x, y, big, small, w=3.6, h=1.5, color=GREEN):
    box(s, x, y, w, h, LIGHT)
    box(s, x, y, 0.08, h, color)
    text(s, x + 0.25, y + 0.08, w - 0.3, 0.8, big, size=30, bold=True, color=color)
    text(s, x + 0.25, y + 0.85, w - 0.35, 0.7, small, size=13)


# ------------------------------------------------------------------ numbers
sn, sc = S["fits"]["naive"]["realloc"], S["fits"]["correct"]["realloc"]
fn, fc = FL["fits"]["naive"]["realloc"], FL["fits"]["correct"]["realloc"]
ssw, fsw = S["sweep"], FL["sweep"]
s_tv_n, s_tv_c = S["fits"]["naive"]["channels"]["tv"]["share"], S["fits"]["correct"]["channels"]["tv"]["share"]
tmp = OUT / "_charts"
tmp.mkdir(exist_ok=True)
chart_delta(S, tmp / "delta_smooth.png", (-2.4, 2.6))
chart_delta(FL, tmp / "delta_flighted.png", (-2.4, 2.6))
m_s, p_s = drift(S["seed"], False)
chart_drift(tmp / "drift_smooth.png", m_s, p_s)
med_s = float(np.median(np.abs(p_s)))
_, p_f = drift(FL["seed"], True)
med_f = float(np.median(np.abs(p_f)))

# 1 ---------------------------------------------------------------- hook
s = prs.slides.add_slide(BLANK)
box(s, 0, 0, 13.333, 7.5, GREEN)
text(s, 0.9, 1.5, 11.5, 2.2, "The client moved 15% of TV into digital.\nWas the data ever asking for it?", size=44, bold=True, color="#FFFFFF")
box(s, 0.9, 4.1, 2.0, 0.07, "#FFFFFF")
text(s, 0.9, 4.4, 11.5, 1.2, "The Two Calendars · a marketing-mix-model case in diabetes", size=22, color="#E8F3EC")
text(s, 0.9, 6.4, 11.5, 0.6, "FDE associate · Q3 readout in 10 days", size=16, color="#E8F3EC")
s.notes_slide.notes_text_frame.text = (
    "Open with the stakes. The Brand Director told their VP this move was data-backed, and it has been implemented. "
    "Three weeks into the quarterly refresh, weekly totals look slightly off against the campaign calendar. "
    "Our job in 10 days: find out whether that small discrepancy could have changed the decision, and make sure it cannot happen again.")

# 2 ---------------------------------------------------------------- setup
s = slide("A weekly TV file and monthly everything-else: the two calendars disagree", 2,
          "Explain the two calendars simply. Media weeks run Monday to Sunday. Sales and digital come as calendar months. "
          "A week can straddle a month end. The shortcut is to drop the whole week into the month of its Monday. "
          "Example: $700k week from 29 Jan to 4 Feb. Correct is $300k January and $400k February. Naive is $700k January, $0 February. "
          "Total spend is the same; the timing is wrong, and the model learns from timing.")
text(s, 0.75, 1.9, 5.6, 4.5, ["TV is bought by media week, Monday to Sunday.",
                              "Digital, email and sales arrive by calendar month.",
                              "The shortcut puts a whole week into one month."], size=21)
box(s, 7.0, 1.9, 5.6, 4.3, LIGHT)
text(s, 7.3, 2.0, 5.0, 0.5, "One week, $700k  (29 Jan – 4 Feb)", size=16, bold=True, color=GREEN)
box(s, 7.3, 2.8, 2.0, 1.0, GREEN)
text(s, 7.3, 3.0, 2.0, 0.6, "Jan · 3 days", size=14, bold=True, color="#FFFFFF", align=PP_ALIGN.CENTER)
box(s, 9.3, 2.8, 2.7, 1.0, GREY)
text(s, 9.3, 3.0, 2.7, 0.6, "Feb · 4 days", size=14, bold=True, color="#FFFFFF", align=PP_ALIGN.CENTER)
text(s, 7.3, 4.1, 5.0, 1.9, ["Correct:  $300k to Jan, $400k to Feb", "Naive:  $700k to Jan, $0 to Feb"], size=18)

# 3 ---------------------------------------------------------------- method
s = slide("We built a world where we already know the answer, then asked the model to find it", 3,
          "We cannot check the client's model against reality, so we simulate. Four years of daily truth with a known effect per channel: "
          "TV 18 percent of sales, digital 14, email 6. We publish it the way vendors do, aggregate TV both ways, fit the same MMM, and compare to the answer key. "
          "We also know the true effect of the 15 percent move, because we can re-run the true daily process.")
steps = ["Daily truth\n(known effects)", "Published like vendors\nTV weekly · rest monthly", "Aggregate TV\nnaive vs correct", "Same MMM\non both", "Compare with\nanswer key"]
for i, t in enumerate(steps):
    x = 0.75 + i * 2.5
    box(s, x, 2.0, 2.25, 1.6, LIGHT if i % 2 == 0 else GREEN, MSO_SHAPE.PENTAGON if i < 4 else MSO_SHAPE.RECTANGLE)
    text(s, x + 0.1, 2.15, 2.0, 1.3, t, size=14, bold=True, color=DARK if i % 2 == 0 else "#FFFFFF", align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
stat(s, 0.75, 4.4, "48 months", "4 years of data, 210 vendor weeks", w=3.8)
stat(s, 4.75, 4.4, "18 · 14 · 6 %", "true share of sales: TV · digital · email", w=3.8)
stat(s, 8.75, 4.4, f"{S['true_delta']*100:+.1f}%", "true effect of the 15% shift on sales (it hurts)", w=3.8, color=RED)

# 4 ---------------------------------------------------------------- error
s = slide(f"Same budget, wrong months: a typical month is off by about {med_s:.0f}%", 4,
          f"This is the error reproduced. Each bar is one month of steady TV spend; naive minus correct as a percent of correct. "
          f"Total spend is identical, only the timing moves. Median absolute month deviation is {med_s:.0f} percent here and {med_f:.0f} percent in the pulsed world. "
          "Months with five Mondays get five weeks of spend, months with four get four, regardless of how many days they really contain.")
s.shapes.add_picture(str(tmp / "drift_smooth.png"), Inches(0.75), Inches(1.9), width=Inches(7.8))
stat(s, 9.0, 2.0, f"{med_s:.0f}%", "median monthly TV deviation, naive vs correct")
stat(s, 9.0, 3.8, "0%", "difference in total spend. Only timing moves.")
text(s, 9.0, 5.6, 3.8, 1, "Months with five Mondays look expensive; four-Monday months look cheap.", size=14, color=GREY)

# 5 ---------------------------------------------------------------- finding 1
s = slide("When TV runs steadily, the naive calendar manufactures the recommendation", 5,
          f"This is the core finding and it mirrors the client's situation. With steady weekly TV, the naive series has spurious month-to-month swings. "
          f"The model blames TV for sales noise it cannot explain, so TV looks weak: {s_tv_n*100:.1f} percent credited versus a true 18. "
          f"The naive model says the shift adds {sn['median']*100:.2f} percent of sales with a {sn['p_positive']*100:.0f} percent chance of helping. "
          f"The correct calendar says {sc['median']*100:.2f} percent and {sc['p_positive']*100:.0f} percent, which is indecision, as it should be. "
          f"The truth is {S['true_delta']*100:.2f} percent. Across {ssw['n_seeds']} re-simulated worlds the naive pipeline showed a confident win in "
          f"{ssw['realloc']['naive']['pct_seeds_confidently_positive']*100:.0f} percent of them, the correct pipeline in none, while the true effect was negative in all.")
s.shapes.add_picture(str(tmp / "delta_smooth.png"), Inches(0.6), Inches(1.9), width=Inches(7.9))
stat(s, 8.9, 1.9, f"{s_tv_n*100:.0f}% → {s_tv_c*100:.0f}%", "TV credit, naive → correct (truth: 18%)", w=3.9)
stat(s, 8.9, 3.6, f"{ssw['realloc']['naive']['pct_seeds_confidently_positive']*100:.0f}% vs 0%", f"of {ssw['n_seeds']} worlds showed a confident win: naive vs correct", w=3.9, color=RED)
text(s, 0.75, 5.8, 12, 1, "The fix does not prove the shift is bad. It removes a false signal that made it look good.", size=18, bold=True, color=GREEN)

# 6 ---------------------------------------------------------------- finding 2
s = slide("When TV is heavily pulsed, the calendar matters less. The shift still fails.", 6,
          f"Honesty slide. In a heavily flighted world, TV on-off pulses give the model so much real variation that the calendar error is second-order: "
          f"it moves a channel's share by roughly 2 points with no consistent sign. Both versions say the shift loses sales: naive {fn['median']*100:.2f}, correct {fc['median']*100:.2f}, truth {FL['true_delta']*100:.2f}. "
          f"The bigger risk here is overconfidence: the 90 percent intervals covered the true TV share only {fsw['channels']['tv']['correct']['coverage90']*100:.0f} percent of the time, "
          "because the model is simplified and the bootstrap only sees sampling noise. So the answer depends on how the client phases TV, which we can check from their file in minutes.")
s.shapes.add_picture(str(tmp / "delta_flighted.png"), Inches(0.6), Inches(1.9), width=Inches(7.9))
stat(s, 8.9, 1.9, f"{fc['median']*100:+.2f}%", "sales impact of the shift, correct calendar", w=3.9)
stat(s, 8.9, 3.6, f"{fsw['channels']['tv']['correct']['coverage90']*100:.0f}%", "of the time the 90% interval caught the true TV share. Treat intervals as optimistic.", w=3.9, color=RED)
text(s, 0.75, 5.8, 12, 1, "So the calendar is one risk, not the only one: model confidence is the other.", size=18, bold=True, color=GREEN)

# 7 ---------------------------------------------------------------- safeguard
s = slide("The safeguard: nothing reaches the model unchecked, including what the LLM reads", 7,
          f"Prevention. Twenty deterministic checks run on every refresh and any error blocks the fit. An LLM reads the vendor specs and extracts claims such as weeks start Monday. "
          f"It is a reader, not the authority: each claim needs its quote to appear word for word in the spec, and a test on the real file has to agree. "
          f"Live run with {S['spec_check']['llm']}: {S['spec_check']['tally']['VERIFIED']} verified, {S['spec_check']['tally']['ADVISORY']} advisory, none rejected. "
          "Then we gave it a spec that wrongly said the date is the Sunday the week ends. The model repeated it faithfully, and the data check caught it because 0 percent of dates were Sundays. Any conflict goes to a human.")
cols = [("1  Validate every refresh", ["Week starts Monday, 7-day spacing", "Month-start dates, no gaps", "Weeks cover the window", "Apportioning conserves spend", "Errors block the model"]),
        ("2  LLM reads the spec", ["Extracts calendar and grain claims", "Quote must exist word for word", "Real file must agree", "Only verified claims act", "Conflicts go to a human"])]
for i, (t, items) in enumerate(cols):
    x = 0.75 + i * 6.1
    box(s, x, 1.9, 5.8, 3.7, LIGHT)
    box(s, x, 1.9, 5.8, 0.08, GREEN)
    text(s, x + 0.25, 2.1, 5.3, 0.6, t, size=20, bold=True, color=GREEN)
    text(s, x + 0.25, 2.75, 5.3, 2.8, ["•  " + it for it in items], size=16)
text(s, 0.75, 5.95, 12, 1, "Live test: spec said “Sunday”, data said Monday. The LLM repeated the spec; the data check overruled it.", size=17, bold=True, color=GREEN)

# 8 ---------------------------------------------------------------- close
s = slide("What we tell the Brand Director before the Q3 readout", 8,
          "Close with actions. One: do not present the shift as data-backed; present it as under review. Two: re-run the refresh on apportioned data. "
          "Three: check how steady the client's weekly TV is. If it is steady, the naive calendar is the dangerous case and our smooth world is the relevant one. "
          "Four: ask the vendor for daily or weekly digital, email and sales so the grain gap is fixed at the source. "
          "Caveat to state aloud: all of this is synthetic; the design of the truth is ours.")
cols = [("Say", ["The shift is not supported by the data.", "Correct calendar: no confident gain in any world we tested.", "Position it as under review, not data-backed."]),
        ("Do this week", ["Re-run the refresh with apportioned TV.", "Check how steady weekly TV spend is.", "Ask the vendor how weeks were mapped to months."]),
        ("Build in", ["Validation gate on every refresh.", "LLM spec reader with verification.", "Request daily data at the source."])]
for i, (t, items) in enumerate(cols):
    x = 0.75 + i * 4.1
    box(s, x, 1.9, 3.85, 4.2, LIGHT)
    box(s, x, 1.9, 3.85, 0.08, GREEN)
    text(s, x + 0.2, 2.1, 3.5, 0.6, t, size=22, bold=True, color=GREEN)
    text(s, x + 0.2, 2.8, 3.5, 3.3, ["•  " + it for it in items], size=16)
text(s, 0.75, 6.3, 12, 0.7, "Caveat: synthetic data and a truth we designed. This validates the method, not the brand.", size=15, color=GREY)

prs.save(OUT / "slides.pptx")
print("saved", OUT / "slides.pptx", "slides:", len(prs.slides))
