import copy

from agent.engine.models import Status
from agent.engine.validate_dplan import validate_dplan
from tests.conftest import example_ctx


def fails(rep):
    return {c.rule_id for c in rep.failures}


def test_ex42_passes_known_rules(ex42, rb):
    rep = validate_dplan(ex42, example_ctx("042"), rb)
    assert rep.ok, [c.message for c in rep.failures]
    assert rep.statuses("SCHEMA") == {Status.PASS}
    assert rep.statuses("C2") == {Status.PASS}
    assert rep.statuses("C14") == {Status.PASS}          # D1 funding_for D2 with real gap
    assert rep.statuses("C12_FLOW") == {Status.PASS}
    # unknown official codes are flagged, never assumed
    assert rep.statuses("C3") == {Status.NOT_IMPLEMENTED}


def test_ex43_detects_orphan_c2_and_posture(ex43, rb):
    rep = validate_dplan(ex43, example_ctx("043", expected_team_id="TEAM_043"), rb)
    f = fails(rep)
    assert "C1" in f                       # D3 -> I9 orphan
    assert "C2" in f                       # 2330 SELL 3000 vs formula 2000
    assert "C12_FLOW" in f                 # reduce but net buy +2.65M
    assert "C12_CASH" in f                 # est cash 3.75% outside [8%, 15%]
    c12 = rep.by_rule("C12_CASH")[0]
    assert abs(float(c12.actual) - 0.0375) < 1e-9


def test_schema_rejects_extra_field_and_missing(ex42, rb):
    d = copy.deepcopy(ex42)
    d["extra"] = 1
    assert "SCHEMA" in fails(validate_dplan(d, example_ctx(), rb))
    d = copy.deepcopy(ex42)
    del d["agent_metadata"]["code_version"]
    assert "SCHEMA" in fails(validate_dplan(d, example_ctx(), rb))


def test_id_rules(ex42, rb):
    d = copy.deepcopy(ex42)
    d["sources"][1]["source_id"] = "S3"                 # skip S2
    d["observations"][1]["source_ref"] = ["S3"]
    assert "ID_SEQUENCE" in fails(validate_dplan(d, example_ctx(), rb))
    d = copy.deepcopy(ex42)
    d["sources"][0]["source_id"] = "S01"
    assert {"ID_FORMAT", "SCHEMA"} & fails(validate_dplan(d, example_ctx(), rb))


def test_coverage_missing_holding(ex42, rb):
    d = copy.deepcopy(ex42)
    d["no_trade_decisions"] = d["no_trade_decisions"][:1]          # 2412 not covered
    assert "COVERAGE" in fails(validate_dplan(d, example_ctx(), rb))


def test_coverage_duplicate(ex42, rb):
    d = copy.deepcopy(ex42)
    d["no_trade_decisions"].append({"ticker": "2330", "reason_refs": ["I3"]})
    assert "COVERAGE" in fails(validate_dplan(d, example_ctx(), rb))


def test_c13_oversell(ex42, rb):
    ctx = example_ctx(prev_holdings={"2330": 1000, "2317": 40000, "2412": 30000})
    rep = validate_dplan(ex42, ctx, rb)
    assert "C13" in fails(rep)


def test_c14_without_gap_fails(ex42, rb):
    # plenty of cash -> no funding gap -> funding_for is contradicted by numbers
    rep = validate_dplan(ex42, example_ctx(prev_cash=9_000_000), rb)
    assert "C14" in fails(rep)


def test_c14_pointing_to_sell_fails(ex42, rb):
    d = copy.deepcopy(ex42)
    d["decisions"][0]["funding_for"] = ["D1"]
    assert "C14" in fails(validate_dplan(d, example_ctx(), rb))


def test_c6_cutoff_and_submission(ex42, rb):
    d = copy.deepcopy(ex42)
    d["agent_metadata"]["run_completed_at"] = "2026-10-27T08:56:00+08:00"
    f = fails(validate_dplan(d, example_ctx(submission_time="2026-10-27T08:57:00+08:00"), rb))
    assert "C6_CUTOFF" in f and "C6" in f
    f = fails(validate_dplan(ex42, example_ctx(submission_time="2026-10-26T19:00:00+08:00"), rb))
    assert "C6" in f                                   # before the window opens


def test_filename_and_team(ex42, rb):
    f = fails(validate_dplan(ex42, example_ctx(filename="D-Plan_TEAM_042_2026-10-28.json",
                                               expected_team_id="TEAM_999"), rb))
    assert {"FILENAME", "TEAM_ID"} <= f


def test_non_universe_ticker(ex42, rb):
    d = copy.deepcopy(ex42)
    d["decisions"][1]["ticker"] = "0050"
    d["orders"][1]["ticker"] = "0050"
    ctx = example_ctx()
    ctx.closes_prev["0050"] = 42.5
    assert "R_UNIVERSE" in fails(validate_dplan(d, ctx, rb))


def test_action_inconsistent(ex42, rb):
    d = copy.deepcopy(ex42)
    d["decisions"][1]["action"] = "ADD"                # 2891 not held
    assert "ACTION" in fails(validate_dplan(d, example_ctx(), rb))


def test_c9_weight_breach_detected(ex42, rb):
    d = copy.deepcopy(ex42)
    d["decisions"][1]["target_weight"] = 0.12          # > 10%, schema allows <= 0.25
    d["orders"][1]["shares"] = 288000                  # floor(0.12*102e6/42.5/1000)*1000
    rep = validate_dplan(d, example_ctx(), rb)
    assert any(c.rule_id.startswith("C9:R_OTHER_CAP") and c.status == Status.FAIL for c in rep.checks)


def test_no_context_marks_unknown(ex42, rb):
    rep = validate_dplan(ex42, None, rb)
    assert rep.statuses("C2") == {Status.UNKNOWN}
