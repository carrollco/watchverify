"""Checker v3's act rule: a step placed in the video but seen only by its result goes to review. No network."""
from watchverify import bench, schema
from watchverify.verify import merge_second_look

REF = {"steps": [{"index": 0, "start_s": 0.0, "end_s": 4.0, "action": "lift cover"},
                 {"index": 1, "start_s": 4.0, "end_s": 8.0, "action": "lift battery"}]}


def checks(seen0=None, seen1="act", confirm0=None):
    cs = [{"reference_step": 0, "status": "observed", "observed_start_s": 0.0, "observed_end_s": 4.0,
           "evidence": "", "cannot_see": "none"},
          {"reference_step": 1, "status": "observed", "observed_start_s": 4.0, "observed_end_s": 8.0,
           "evidence": "", "cannot_see": "none"}]
    if seen0:
        cs[0]["seen_as"] = seen0
    if seen1:
        cs[1]["seen_as"] = seen1
    if confirm0:
        cs[0]["confirm_look"] = {"status": "observed", "seen_as": confirm0, "observed_start_s": 0.0,
                                 "observed_end_s": 2.0, "evidence": ""}
    return {"checks": cs}


def test_result_only_goes_to_review():
    v = schema.apply_order_rules(REF, checks(seen0="result_only"))
    assert v["verdict"] == "review" and v["disputed_steps"] == [0]
    assert "result_only" in v["checks"][0]["reasons"]


def test_switch_off_restores_pass():
    v = schema.apply_order_rules(REF, checks(seen0="result_only"), use_act=False)
    assert v["verdict"] == "pass"
    assert schema.rules_for(("act",))["use_act"] is False and schema.rules_for()["use_act"] is True


def test_v2_checks_without_seen_as_are_untouched():
    v = schema.apply_order_rules(REF, checks(seen0=None, seen1=None))
    assert v["verdict"] == "pass" and not any("result_only" in c["reasons"] for c in v["checks"])


def test_seen_acting_passes_and_confirm_look_result_only_reviews():
    assert schema.apply_order_rules(REF, checks(seen0="act"))["verdict"] == "pass"
    v = schema.apply_order_rules(REF, checks(seen0="act", confirm0="result_only"))
    assert v["verdict"] == "review" and v["disputed_steps"] == [0]


def test_not_observed_step_is_not_changed_by_the_rule():
    c = checks(seen0="not_seen")
    c["checks"][0].update(status="not_observed", observed_start_s=-1, observed_end_s=-1)
    v = schema.apply_order_rules(REF, c)
    assert v["verdict"] == "fail" and v["missing_steps"] == [0]


def test_second_look_carries_seen_as():
    c = {"reference_step": 0, "status": "not_observed", "seen_status": "not_observed", "observed_start_s": -1,
         "observed_end_s": -1, "evidence": "no"}
    merge_second_look(c, {"status": "observed", "seen_as": "result_only", "observed_start_s": 1.0,
                          "observed_end_s": 2.0, "evidence": "cover already off"}, 10.0)
    assert c["seen_as"] == "result_only" and c["observed_start_s"] == 11.0


def test_v3_schema_and_instructions():
    assert "seen_as" in schema.STEP_CHECK_ACT["required"] and "seen_as" not in schema.STEP_CHECK["required"]
    assert "seen_as" in schema.SECOND_LOOK_ACT["required"]
    assert schema.VIDEO_VERIFICATION_ACT["properties"]["checks"]["items"] is schema.STEP_CHECK_ACT
    assert "Judge a step by its result" not in schema.VERIFY_VIDEO_INSTRUCTIONS_ACT
    assert "Judge a step by its result" in schema.VERIFY_VIDEO_INSTRUCTIONS     # v2 unchanged, so its replay holds
    assert bench.checker_options("v3") == {"act": True} and bench.checker_options("v3c") == {"act": True}
    assert bench.checker_options("v2c") == {}
    assert bench.checker_options("v4") == {"effort": "high"}
    assert ("act",) in [a for a, _ in bench.ABLATIONS]
