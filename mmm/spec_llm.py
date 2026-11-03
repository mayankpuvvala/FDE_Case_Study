"""LLM reads vendor file specs -> structured calendar/grain claims -> we VERIFY every claim.

The LLM is a reader, never the authority. Each claim must pass two independent gates:
  1. GROUNDING  - the claim's `quote` must appear verbatim in the spec (catches invented text).
  2. DATA TEST  - a deterministic test on the actual delivered file must agree
                  (catches a spec that is wrong/stale, or a claim the LLM misread).
Only claims passing both are VERIFIED and allowed to drive pipeline behaviour.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

FIELDS = {
    "grain": ["weekly", "monthly", "daily", "other"],
    "week_start_day": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "date_semantics": ["week_start", "week_end", "month_start", "month_end", "unknown"],
    "calendar": ["broadcast", "calendar_month", "fiscal", "unknown"],
    "risk": ["weeks_straddle_months", "restatements_possible", "values_not_day_normalised", "other"],
}

SOURCES = {  # source -> (data file, date column, spec file)
    "tv_media_weekly": ("tv_media_weekly.csv", "week_commencing", "tv_media_weekly_spec.txt"),
    "digital_monthly": ("digital_monthly.csv", "month", "digital_email_monthly_spec.txt"),
    "email_monthly": ("email_monthly.csv", "month", "digital_email_monthly_spec.txt"),
    "sales_monthly": ("sales_monthly.csv", "month", "sales_monthly_spec.txt"),
}

PROMPT = """You are reviewing data-vendor file specifications for a marketing-mix model.
For EACH source below, extract the calendar and grain assumptions as JSON claims.

Allowed fields and values: {fields}

Rules:
- Return ONLY JSON: {{"claims": [{{"source": str, "field": str, "value": str, "quote": str}}]}}
- `quote` MUST be copied verbatim from that source's spec text. Do not paraphrase.
- Only state what the spec says. If it is silent, omit the claim; never guess.
- Use field "risk" for anything that could silently misalign weekly/monthly/daily data.

SPECS:
{specs}
"""


@dataclass
class Claim:
    source: str
    field: str
    value: str
    quote: str


@dataclass
class Verdict:
    claim: Claim
    grounded: bool
    data_check: str   # confirmed | contradicted | not_testable
    detail: str
    final: str        # VERIFIED | REJECTED_UNGROUNDED | CONTRADICTED_BY_DATA | ADVISORY


# ---------------------------------------------------------------- backends
class MockLLM:
    """Offline stand-in (no API key needed). `flawed` injects the two failure modes we must catch."""
    name = "mock"

    def __init__(self, flawed: bool = False):
        self.flawed = flawed
        self.name = "mock-flawed" if flawed else "mock-faithful"

    def complete(self, prompt: str) -> str:
        c = [
            ("tv_media_weekly", "grain", "weekly", "Spend is reported by media-buying week."),
            ("tv_media_weekly", "week_start_day", "Monday", "the Monday on which the buying week commences"),
            ("tv_media_weekly", "date_semantics", "week_start", "the Monday on which the buying week commences"),
            ("tv_media_weekly", "calendar", "broadcast", "follow the broadcast calendar"),
            ("tv_media_weekly", "risk", "weeks_straddle_months", "a week may straddle two months"),
            ("tv_media_weekly", "risk", "restatements_possible", "Late invoices may restate prior weeks."),
            ("digital_monthly", "grain", "monthly", "one row per calendar month"),
            ("digital_monthly", "date_semantics", "month_start", "first day of the calendar month"),
            ("digital_monthly", "calendar", "calendar_month", "one row per calendar month"),
            ("email_monthly", "grain", "monthly", "one row per calendar month"),
            ("email_monthly", "date_semantics", "month_start", "first day of the calendar month"),
            ("sales_monthly", "grain", "monthly", "aggregated by calendar month"),
            ("sales_monthly", "date_semantics", "month_start", "first day of the calendar month"),
            ("sales_monthly", "calendar", "calendar_month", "aggregated by calendar month"),
            ("sales_monthly", "risk", "values_not_day_normalised", "no day-count normalisation is applied"),
        ]
        if self.flawed:
            c += [
                # failure mode 1: invented text -> must fail GROUNDING
                ("tv_media_weekly", "week_start_day", "Sunday", "Weeks run Sunday to Saturday."),
                # failure mode 2: real quote, misread -> must fail the DATA TEST
                ("tv_media_weekly", "date_semantics", "week_end", "the Monday on which the buying week commences"),
                ("digital_monthly", "date_semantics", "month_end", "first day of the calendar month"),
            ]
        return json.dumps({"claims": [dict(zip(("source", "field", "value", "quote"), x)) for x in c]})


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("MMM_LLM_MODEL", "claude-sonnet-5-5")
        self.name = f"anthropic:{self.model}"

    def complete(self, prompt: str) -> str:
        r = self.client.messages.create(model=self.model, max_tokens=3000,
                                        messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text")


def _read_var(path: str | Path, var: str) -> str | None:
    """Read ONE variable from a foreign .env file without loading the others."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith(var + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


class OpenAICompatLLM:
    """OpenAI or Groq (OpenAI-compatible endpoint). JSON mode keeps parsing robust."""
    PROVIDERS = {
        "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
        "openai": (None, "OPENAI_API_KEY", "gpt-4o-mini"),
    }

    def __init__(self, provider: str, model: str | None = None):
        from dotenv import load_dotenv
        from openai import OpenAI
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        base, var, default = self.PROVIDERS[provider]
        key = os.environ.get(var)
        if not key and os.environ.get("OPENAI_ENV_FILE") and provider == "openai":
            key = _read_var(os.environ["OPENAI_ENV_FILE"], var)
        if not key:
            raise RuntimeError(f"{var} not set (put it in .env or the environment)")
        self.client = OpenAI(api_key=key, base_url=base)
        self.model = model or os.environ.get("MMM_LLM_MODEL") or default
        self.name = f"{provider}:{self.model}"

    def complete(self, prompt: str) -> str:
        r = self.client.chat.completions.create(
            model=self.model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}])
        return r.choices[0].message.content


def get_llm(kind: str = "auto"):
    if kind == "mock":
        return MockLLM()
    if kind == "mock-flawed":
        return MockLLM(flawed=True)
    if kind in ("groq", "openai"):
        return OpenAICompatLLM(kind)
    if kind == "anthropic" or (kind == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicLLM()
    return MockLLM()


# ---------------------------------------------------------------- extraction
def load_specs(spec_dir: Path) -> dict[str, str]:
    return {s: (Path(spec_dir) / sp).read_text(encoding="utf-8") for s, (_, _, sp) in SOURCES.items()}


def extract_claims(llm, specs: dict[str, str]) -> list[Claim]:
    block = "\n\n".join(f"### SOURCE: {s}\n{t}" for s, t in specs.items())
    raw = llm.complete(PROMPT.format(fields=json.dumps(FIELDS), specs=block))
    payload = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    out = []
    for c in payload.get("claims", []):
        if {"source", "field", "value", "quote"} <= c.keys() and c["field"] in FIELDS:
            out.append(Claim(c["source"], c["field"], str(c["value"]), str(c["quote"])))
    return out


# ---------------------------------------------------------------- verification
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower().rstrip(".")


def is_grounded(claim: Claim, specs: dict[str, str]) -> bool:
    return claim.source in specs and len(claim.quote) >= 8 and _norm(claim.quote) in _norm(specs[claim.source])


def _data_test(claim: Claim, dates: pd.Series) -> tuple[str, str]:
    d = pd.to_datetime(dates).sort_values()
    f, v = claim.field, claim.value
    if f == "grain":
        gaps = d.diff().dropna().dt.days
        if v == "weekly":
            ok = bool((gaps == 7).all())
            return ("confirmed" if ok else "contradicted"), f"all gaps 7 days: {ok}"
        if v == "monthly":
            ok = bool((d.dt.day == 1).all() and gaps.between(28, 31).all())
            return ("confirmed" if ok else "contradicted"), f"all on 1st, 28-31 day gaps: {ok}"
        return "not_testable", "no test for this grain"
    if f == "week_start_day":
        names = d.dt.day_name()
        ok = bool((names == v).all())
        return ("confirmed" if ok else "contradicted"), f"{(names == v).mean():.0%} of dates are {v}"
    if f == "date_semantics":
        rule = {"week_start": lambda x: x.dt.day_of_week == 0, "week_end": lambda x: x.dt.day_of_week == 6,
                "month_start": lambda x: x.dt.day == 1, "month_end": lambda x: x.dt.is_month_end}.get(v)
        if rule is None:
            return "not_testable", "unknown semantics"
        share = float(rule(d).mean())
        return ("confirmed" if share == 1 else "contradicted"), f"{share:.0%} of dates look like {v}"
    if f == "calendar":
        if v == "calendar_month":
            ok = bool((d.dt.day == 1).all())
            return ("confirmed" if ok else "contradicted"), f"dates on the 1st: {ok}"
        if v == "broadcast":
            straddle = int(((d + pd.Timedelta(days=6)).dt.month != d.dt.month).sum())
            return ("confirmed" if straddle > 0 else "contradicted"), f"{straddle} weeks straddle a month boundary"
        return "not_testable", "no test for this calendar"
    if f == "risk" and v == "weeks_straddle_months":
        straddle = int(((d + pd.Timedelta(days=6)).dt.month != d.dt.month).sum())
        return ("confirmed" if straddle > 0 else "contradicted"), f"{straddle} of {len(d)} weeks straddle months"
    return "not_testable", "needs human review"


def verify_claims(claims: list[Claim], specs: dict[str, str], dates: dict[str, pd.Series]) -> list[Verdict]:
    out = []
    for c in claims:
        if not is_grounded(c, specs):
            out.append(Verdict(c, False, "not_run", "quote not found verbatim in spec", "REJECTED_UNGROUNDED"))
            continue
        if c.source not in dates:
            out.append(Verdict(c, True, "not_testable", "no data file for source", "ADVISORY"))
            continue
        status, detail = _data_test(c, dates[c.source])
        final = {"confirmed": "VERIFIED", "contradicted": "CONTRADICTED_BY_DATA"}.get(status, "ADVISORY")
        out.append(Verdict(c, True, status, detail, final))
    return out


def derive_actions(verdicts: list[Verdict]) -> dict:
    """Only VERIFIED claims may change pipeline behaviour."""
    ok = {(v.claim.source, v.claim.field, v.claim.value) for v in verdicts if v.final == "VERIFIED"}
    # day-level apportioning needs BOTH the weekly grain and a verified week-start day
    weekly_tv = ("tv_media_weekly", "grain", "weekly") in ok and any(
        s == "tv_media_weekly" and f == "week_start_day" for s, f, _ in ok)
    monthly = all((s, "grain", "monthly") in ok for s in ("digital_monthly", "email_monthly", "sales_monthly"))
    conflicts = [f"{v.claim.source}.{v.claim.field}={v.claim.value}" for v in verdicts
                 if v.final == "CONTRADICTED_BY_DATA"]
    return {"needs_human_review": bool(conflicts),
            "conflicts": conflicts,  # spec and delivered file disagree: ask the vendor before trusting either
            "apportion_tv_weekly_to_monthly": weekly_tv and monthly,
            "reason": "TV verified weekly (Mon-Sun) while digital/email/sales verified monthly: "
                      "grains differ, so weeks must be apportioned across calendar months." if weekly_tv and monthly
                      else "grain mismatch not fully verified - human review required"}


def run_spec_check(llm, spec_dir: Path, data_dir: Path) -> dict:
    specs = load_specs(spec_dir)
    dates = {s: pd.read_csv(Path(data_dir) / f, usecols=[col])[col] for s, (f, col, _) in SOURCES.items()}
    verdicts = verify_claims(extract_claims(llm, specs), specs, dates)
    tally: dict[str, int] = {}
    for v in verdicts:
        tally[v.final] = tally.get(v.final, 0) + 1
    return {"llm": llm.name, "verdicts": [{**asdict(v.claim), "grounded": v.grounded, "data_check": v.data_check,
                                           "detail": v.detail, "final": v.final} for v in verdicts],
            "tally": tally, "actions": derive_actions(verdicts)}
