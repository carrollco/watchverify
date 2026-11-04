"""The code rules added on day one: second-look windows and merging, self-check, cut-short steps, SAM frame
times, step tracks, speech turns, replayed ledger entries. Pure functions; no network."""
from watchverify import schema
from watchverify.ground import frame_time, step_tracks, attach_turns, phrases_to_track
from watchverify.verify import search_window, merge_second_look
from watchverify.ledger import Ledger, Entry


def chk(i, st, a=-1, b=-1):
    return {"reference_step": i, "status": st, "observed_start_s": a, "observed_end_s": b, "evidence": "e", "cannot_see": "none"}


def ref(*spans, **extra):
    return {"steps": [dict({"index": i, "start_s": a, "end_s": b}, **extra.get(str(i), {})) for i, (a, b) in enumerate(spans)]}


def test_search_window_sits_between_observed_neighbors():
    checks = [chk(0, "observed", 0, 4), chk(1, "not_observed"), chk(2, "observed", 9, 12)]
    assert search_window(checks, 1, duration=20) == (3.5, 9.5)
    # no later neighbor: search to the end; a tiny gap is widened to the minimum length
    assert search_window([chk(0, "observed", 0, 19.5), chk(1, "not_observed")], 1, duration=20) == (18.5, 20.0)


def test_second_look_overrides_only_when_it_sees_something():
    c = chk(1, "not_observed"); c["seen_status"] = "not_observed"
    merge_second_look(c, {"status": "observed", "observed_start_s": 1.0, "observed_end_s": 2.5, "evidence": "tool at seam"}, 10.0)
    assert (c["status"], c["seen_status"], c["observed_start_s"], c["observed_end_s"]) == ("observed", "observed", 11.0, 12.5)
    assert c["second_look"]["first_pass"]["status"] == "not_observed"
    d = chk(2, "not_observed"); d["seen_status"] = "not_observed"
    merge_second_look(d, {"status": "not_observed", "observed_start_s": -1, "observed_end_s": -1, "evidence": "nothing"}, 3.0)
    assert d["status"] == "not_observed" and "second_look" in d


def test_self_check_turns_missing_into_unclear_and_rescore_is_repeatable():
    r = ref((0, 3), (3, 11), (12, 15))
    schema.annotate_self_check(r, {"checks": [chk(0, "not_observed"), chk(1, "observed", 3, 11), chk(2, "observed", 12, 15)]})
    assert [s["self_check"] for s in r["steps"]] == ["not_observed", "observed", "observed"]
    v = schema.apply_order_rules(r, {"checks": [chk(0, "not_observed"), chk(1, "observed", 3, 11), chk(2, "not_observed")]})
    assert v["missing_steps"] == [2] and v["unclear_steps"] == [0] and v["verdict"] == "fail"
    assert "expert's own video" in v["checks"][0]["status_reason"]
    # rules start from seen_status, so applying them again (rescore) gives the same answer
    assert schema.apply_order_rules(r, v)["missing_steps"] == [2]
    r["steps"][0]["self_check"] = "observed"            # a new reference: step 0 is now checkable
    assert schema.apply_order_rules(r, v)["missing_steps"] == [0, 2]


def test_narration_only_step_is_never_missing():
    r = ref((0, 3), (3, 11), **{"0": {"checkpoint_visibility": "narration_only"}})
    v = schema.apply_order_rules(r, {"checks": [chk(0, "not_observed"), chk(1, "observed", 3, 11)]})
    assert v["checks"][0]["status"] == "unclear" and v["verdict"] == "review"


def test_cut_short_step_needs_review():
    r = ref((0, 5), (5, 15))
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 5), chk(1, "observed", 6, 9)]})
    assert v["shortened_steps"] == [1] and v["verdict"] == "review"
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 5), chk(1, "observed", 6, 11)]})
    assert v["shortened_steps"] == [] and v["verdict"] == "pass"


def test_sam_frames_count_from_zero():
    assert frame_time(0, 5) == 0.0 and frame_time(67, 5) == 13.4 and frame_time(None, 5) is None


def test_step_tracks_and_turns():
    steps = [{"start_s": 0.0, "end_s": 2.0}, {"start_s": 2.0, "end_s": 4.0}]
    boxes = [{"frame": f, "t": f / 5, "confidence": 0.7} for f in range(0, 8)]          # 0.0 to 1.4 s
    tr = step_tracks(steps, {"pry tool": boxes, "cover": []}, fps=5)
    assert tr[0]["pry tool"]["frames"] == 8 and tr[0]["pry tool"]["window_frames"] == 10
    assert tr[1]["pry tool"]["frames"] == 0 and tr[0]["cover"]["first_s"] is None
    turns = [{"startMs": 0, "endMs": 1500, "transcript": "a"}, {"startMs": 1800, "endMs": 2600, "transcript": "b"}]
    assert [[t["text"] for t in s] for s in attach_turns(steps, turns)] == [["a", "b"], ["b"]]


def test_phrases_prefer_extractor_choice_then_most_named():
    assert phrases_to_track({"track": ["pry tool", "Pry tool", "cover"], "steps": []}) == ["pry tool", "cover"]
    steps = [{"objects": ["laptop", "pry tool"]}, {"objects": ["pry tool", "screw"]}]
    assert phrases_to_track({"steps": steps}, limit=2)[0] == "pry tool"


def test_replayed_entries_are_logged_but_not_counted(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.add(Entry("a", "sam-3.1", "sam", 0.02, 1.0))
    led.add(Entry("a", "sam-3.1", "sam", 0.02, 0.0, live=False))
    assert led.total() == 0.02 and "1 replayed" in led.summary()


def test_step_seen_only_on_second_look_needs_review():
    r = ref((0, 5), (5, 10))
    c = chk(1, "not_observed"); c["seen_status"] = "not_observed"
    merge_second_look(c, {"status": "observed", "observed_start_s": 0.5, "observed_end_s": 4.5, "evidence": "x"}, 5.0)
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 5), c]})
    assert v["disputed_steps"] == [1] and v["verdict"] == "review" and v["missing_steps"] == []


def test_checker_never_sees_the_experts_seconds():
    from watchverify.verify import _spec
    ref = {"task": "t", "_source": {}, "steps": [{"index": 0, "start_s": 1, "end_s": 2, "evidence_s": 1.5, "self_check": "observed",
                                                  "action": "pry", "checkpoint_visibility": "clear"}]}
    st = _spec(ref)["steps"][0]
    assert st == {"index": 0, "action": "pry", "checkpoint_visibility": "clear"} and "_source" not in _spec(ref)


def test_another_listed_moment_sends_a_swap_to_review_never_clears_it():
    r = ref((0, 3), (4, 7), (8, 11))
    m = lambda a, b: {"start_s": a, "end_s": b}
    wrong_pick = chk(1, "observed", 9, 10); wrong_pick["other_moments"] = [m(4.5, 6)]   # the Acer case
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 3), wrong_pick, chk(2, "observed", 8.5, 11)]})
    assert v["out_of_order_steps"] == [] and v["verdict"] == "review" and "other_moment" in v["checks"][1]["reasons"]
    # a real swap: no listed moment keeps the reference order, so it still reads out of order
    real = chk(1, "observed", 9, 10); real["other_moments"] = [m(9.5, 10)]
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 3), real, chk(2, "observed", 5, 8)]})
    assert v["out_of_order_steps"] == [1, 2] and v["verdict"] == "fail"
    # a listed moment that is another step's own moment is not admissible (brickpress swap34, v2)
    lent = chk(2, "observed", 14, 16); lent["other_moments"] = [m(8, 10)]
    v = schema.apply_order_rules(ref((0, 3), (4, 7), (8, 11), (12, 15)), {"checks": [
        chk(0, "observed", 0, 3), chk(1, "observed", 8, 10), lent, chk(3, "observed", 10.5, 13)]})
    assert v["out_of_order_steps"] == [2, 3] and v["verdict"] == "fail"
    # without the rule, the clearest moments decide alone
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 3), wrong_pick, chk(2, "observed", 8.5, 11)]}, use_moments=False)
    assert v["out_of_order_steps"] == [1, 2]


def test_done_differently_counts_for_order_and_asks_a_person():
    r = ref((0, 3), (4, 7), (8, 11))
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 0, 3), chk(1, "done_differently", 4, 6), chk(2, "observed", 8, 11)]})
    assert v["verdict"] == "review" and v["different_steps"] == [1] and v["missing_steps"] == []
    v = schema.apply_order_rules(r, {"checks": [chk(0, "observed", 5, 7), chk(1, "done_differently", 0, 3), chk(2, "observed", 8, 11)]})
    assert v["out_of_order_steps"] == [0, 1] and v["verdict"] == "fail"           # present, so its place in order counts


def _state(c):
    if c["status"] == "not_observed":
        return "missing"
    if c.get("out_of_order"):
        return "order"
    if c["status"] in ("unclear", "done_differently") or c.get("shortened") or c.get("disputed"):
        return "review"
    return "ok"


def test_a_rule_fed_by_another_model_output_only_moves_toward_review():
    """The direction rule: a rule whose input is a model output other than the check
    itself (self-check marks, narration-only, SAM timing, other listed moments) may leave a step as it was or send it
    to review; it may never clear a missing, out-of-order or review call. Seeded random checks, every rule in turn."""
    import copy, random
    rng = random.Random(20261028)
    for _ in range(3000):
        n = rng.randint(2, 6)
        r = {"steps": [{"index": i, "start_s": 3.0 * i, "end_s": 3.0 * i + rng.uniform(1, 3),
                        "self_check": rng.choice(["observed", "observed", "not_observed"]),
                        "checkpoint_visibility": rng.choice(["clear", "subtle", "narration_only"])} for i in range(n)]}
        checks = []
        for i in range(n):
            a = rng.uniform(0, 20)
            c = chk(i, rng.choice(["observed", "observed", "not_observed", "unclear", "done_differently"]), a, a + rng.uniform(0.2, 3))
            c["other_moments"] = [{"start_s": (x := rng.uniform(0, 20)), "end_s": x + 1} for _ in range(rng.randint(0, 2))]
            if rng.random() < 0.5:
                c["confirm_look"] = {"status": rng.choice(["observed", "not_observed", "unclear", "done_differently"])}
            if rng.random() < 0.7:
                c["measured"] = {"measurable": rng.random() < 0.8, "ref_seconds": rng.uniform(1, 3), "seconds": rng.choice([0, rng.uniform(0, 3)]),
                                 "began_s": rng.choice([None, rng.uniform(0, 20)]), "ref_began_s": rng.choice([None, 3.0 * i])}
            checks.append(c)
        for rule in schema.SOFTENINGS:
            on = schema.apply_order_rules(r, {"checks": copy.deepcopy(checks)})
            off = schema.apply_order_rules(r, {"checks": copy.deepcopy(checks)}, **{f"use_{rule}": False})
            for a_, b_ in zip(on["checks"], off["checks"]):
                assert _state(a_) in (_state(b_), "review"), (rule, _state(b_), "->", _state(a_), a_)
            assert on["verdict"] in (off["verdict"], "review"), (rule, off["verdict"], on["verdict"])
