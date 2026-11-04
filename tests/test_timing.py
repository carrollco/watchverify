"""The SAM timing check on synthetic tracks: fit on the expert's positions, measure a candidate, and the rules that
combine the measurement with the model's reading. No network."""
from watchverify import schema, timing

FPS, W = 5, 640


def boxes_at(spans):
    """A tool box centered at (x, y) pixels for each (start_s, end_s, x, y) span, one per frame."""
    out = []
    for a, b, x, y in spans:
        for f in range(int(a * FPS), int(b * FPS)):
            out.append(dict(frame=f, t=f / FPS, object_id="0", left=x - 10, top=y - 10, right=x + 10, bottom=y + 10, confidence=0.7))
    return out


REF = {"steps": [{"index": 0, "start_s": 0, "end_s": 4}, {"index": 1, "start_s": 5, "end_s": 9},
                 {"index": 2, "start_s": 10, "end_s": 14}]}
GROUND = {"track_fps": FPS, "width": W, "phrases": ["pry tool"],
          "tracks": {"pry tool": boxes_at([(0, 4, 100, 300), (5, 9, 300, 50), (10, 14, 540, 300)])}}


def test_fit_marks_steps_at_distinct_places_measurable():
    m = timing.fit(REF, GROUND, "pry tool")
    assert all(m["steps"][k]["measurable"] for k in (0, 1, 2)) and m["steps"][1]["ref_seconds"] == 4.0


def test_measure_finds_a_skipped_place_and_the_order():
    m = timing.fit(REF, GROUND, "pry tool")
    cand = boxes_at([(0, 4, 100, 300), (4, 8, 540, 300)])           # step 1's place never visited; step 2 earlier
    got = timing.measure(m, cand, n_frames=40)
    assert got["steps"][1]["seconds"] == 0 and got["steps"][0]["seconds"] >= 3.5 and got["steps"][2]["began_s"] < 5


def test_rules_combine_measurement_and_model():
    m = timing.fit(REF, GROUND, "pry tool")
    meas = timing.measure(m, boxes_at([(0, 4, 100, 300), (4, 5, 300, 50), (5, 9, 540, 300)]), n_frames=45)
    chk = lambda i, st, a=-1, b=-1: {"reference_step": i, "status": st, "observed_start_s": a, "observed_end_s": b,
                                     "evidence": "", "cannot_see": "none"}
    v = timing.attach({"checks": [chk(0, "observed", 0, 4), chk(1, "observed", 4, 5), chk(2, "observed", 5, 9)]}, meas)
    v = schema.apply_order_rules(REF, v)
    assert v["shortened_steps"] == [1] and v["verdict"] == "review"     # 1 s measured against the expert's 4 s
    assert schema.apply_order_rules(REF, v, use_timing=False)["shortened_steps"] == [1]   # model seconds agree here
    v2 = timing.attach({"checks": [chk(0, "observed", 0, 4), chk(1, "not_observed"), chk(2, "observed", 5, 9)]},
                       timing.measure(m, boxes_at([(0, 4, 100, 300), (4, 8, 300, 50), (8, 12, 540, 300)]), n_frames=60))
    v2 = schema.apply_order_rules(REF, v2)
    assert v2["checks"][1]["status"] == "unclear" and v2["verdict"] == "review"   # tracking saw it, the model did not
