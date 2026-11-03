from pathlib import Path

import pandas as pd

from mmm import spec_llm as sl

SPEC_DIR = Path(__file__).resolve().parents[1] / "data" / "vendor_specs"


def run(kind, data_dir):
    return sl.run_spec_check(sl.get_llm(kind), SPEC_DIR, data_dir)


def by(res, **kw):
    return [v for v in res["verdicts"] if all(v[k] == x for k, x in kw.items())]


def test_faithful_reader_has_no_rejections_and_triggers_apportioning(data_dir):
    res = run("mock", data_dir)
    assert "REJECTED_UNGROUNDED" not in res["tally"] and "CONTRADICTED_BY_DATA" not in res["tally"]
    assert res["actions"]["apportion_tv_weekly_to_monthly"] is True


def test_invented_quote_is_rejected(data_dir):
    bad = by(run("mock-flawed", data_dir), value="Sunday")
    assert bad and bad[0]["final"] == "REJECTED_UNGROUNDED"


def test_misread_but_quoted_claim_is_caught_by_data(data_dir):
    res = run("mock-flawed", data_dir)
    for value in ("week_end", "month_end"):
        c = by(res, field="date_semantics", value=value)[0]
        assert c["grounded"] and c["final"] == "CONTRADICTED_BY_DATA"


def test_unverified_claims_cannot_drive_actions(data_dir):
    specs = sl.load_specs(SPEC_DIR)
    dates = {"tv_media_weekly": pd.read_csv(data_dir / "tv_media_weekly.csv")["week_commencing"]}
    claims = [sl.Claim("tv_media_weekly", "grain", "weekly", "totally made up sentence here")]
    verdicts = sl.verify_claims(claims, specs, dates)
    assert not sl.derive_actions(verdicts)["apportion_tv_weekly_to_monthly"]


def test_quote_matching_ignores_whitespace_and_case():
    specs = {"s": "Weeks always run   Monday\nto Sunday."}
    assert sl.is_grounded(sl.Claim("s", "grain", "weekly", "weeks always run monday to sunday"), specs)


def test_spec_that_lies_about_data_is_flagged(data_dir, tmp_path):
    """Spec says Monday, file ships Tuesdays -> even a faithful reader's claim is contradicted."""
    df = pd.read_csv(data_dir / "tv_media_weekly.csv", parse_dates=["week_commencing"])
    df["week_commencing"] += pd.Timedelta(days=1)
    for f in data_dir.glob("*.csv"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    df.to_csv(tmp_path / "tv_media_weekly.csv", index=False, date_format="%Y-%m-%d")
    res = sl.run_spec_check(sl.get_llm("mock"), SPEC_DIR, tmp_path)
    assert by(res, field="week_start_day", value="Monday")[0]["final"] == "CONTRADICTED_BY_DATA"
    assert not res["actions"]["apportion_tv_weekly_to_monthly"]


def test_any_contradiction_escalates_to_human_review(data_dir):
    res = run("mock-flawed", data_dir)
    assert res["actions"]["needs_human_review"] and res["actions"]["conflicts"]
    assert not run("mock", data_dir)["actions"]["needs_human_review"]
