"""Fixes from the audit of 2026-11-03: a cut that misses the reference's own window is not graded; the
model-seconds rule can be switched off; the SAM order rule is off unless asked for."""
from watchverify.bench import uncovered_steps
from watchverify import schema


def ref(*windows):
    return {"steps": [{"index": i, "start_s": a, "end_s": b, "evidence_s": ev} for i, (a, b, ev) in enumerate(windows)]}


def test_cut_outside_the_reference_window_is_not_graded():
    # brickpress omit10's shape: the reference has the step at 60 to 64 s (evidence 63 s), the cut at 47 to 60.6 s
    r = ref((40.0, 46.0, 43.0), (60.0, 64.0, 63.0))
    # removing step 1 drops 46.9 to the clip's end at 60.6; the evidence frame at 63 s stays
    assert uncovered_steps(r, [(38.0, 46.9), (47.1, 60.6)]) == {1: {"omit": "cut_misses_step"}}


def test_evidence_frame_outside_the_cut_is_not_graded_even_with_overlap():
    # brickpress omit5's shape: window 18.5 to 23.5, evidence 22.0; the removed stretch runs 17.6 to 21.6
    r = ref((10.0, 17.0, 14.0), (18.5, 23.5, 22.0), (24.0, 30.0, 27.0))
    assert uncovered_steps(r, [(9.0, 17.6), (17.7, 21.5), (21.6, 30.0)])[1]["omit"] == "cut_misses_step"


def test_removal_counts_the_in_between_stretches():
    # acer15 omit4's shape: the step's working time is short, but a removal drops the gaps on both sides too
    r = ref((14.5, 17.5, 16.0), (18.5, 20.5, 19.6), (21.0, 23.0, 22.0))
    assert "omit" not in uncovered_steps(r, [(14.0, 17.0), (19.5, 19.75), (21.0, 23.0)]).get(1, {})


def test_a_cut_that_holds_the_step_is_graded():
    assert uncovered_steps(ref((10.0, 14.0, 12.0), (15.0, 19.0, 16.5)), [(9.5, 14.2), (14.6, 19.5)]) == {}


def test_switches():
    assert schema.rules_for(())["use_sam_order"] is False
    assert schema.rules_for(("+sam_order",))["use_sam_order"] is True
    assert schema.rules_for(("span",))["use_span"] is False and schema.rules_for(())["use_span"] is True


def check(observed_end):
    return {"verdict": "pass", "checks": [{"reference_step": 0, "status": "observed", "observed_start_s": 0.0,
                                           "observed_end_s": observed_end, "evidence": "", "cannot_see": ""}]}


def test_span_rule_fires_only_when_switched_on():
    r = {"steps": [{"index": 0, "start_s": 0.0, "end_s": 10.0, "action": "x"}]}
    on = schema.apply_order_rules(r, check(2.0))
    off = schema.apply_order_rules(r, check(2.0), use_span=False)
    assert "model_seconds_shortened" in on["checks"][0]["reasons"]
    assert "model_seconds_shortened" not in off["checks"][0]["reasons"]
