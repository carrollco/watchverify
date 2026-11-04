"""The accuracy test's pure parts: window choice, cut points, variant list, scoring. No network."""
from watchverify.bench import choose_window, segments, variant_plans, score


def proc(*spans, vis=None):
    return {"steps": [{"index": i, "start_s": a, "end_s": b, "checkpoint_visibility": (vis or {}).get(i, "clear")}
                      for i, (a, b) in enumerate(spans)]}


def test_window_prefers_clear_steps_within_span():
    p = proc((0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 120), vis={0: "subtle"})
    a, b, picked = choose_window(p, duration=130, max_steps=4)     # [0..3] has a subtle step, [1..4] does not
    assert picked == [1, 2, 3, 4] and (a, b) == (4.0, 26.0)
    assert choose_window(proc((0, 100), (100, 200)), duration=200) is None


def test_segments_cut_at_midpoints_and_cover_the_clip():
    s = segments(proc((1, 4), (6, 9), (9, 14)), duration=15)
    assert s == [(0.0, 5.0), (5.0, 9.0), (9.0, 15)]


def test_variant_plans_and_truth():
    names = [p["name"] for p in variant_plans(3)]
    assert names == ["omit0", "omit1", "omit2", "swap01", "swap12"]
    assert variant_plans(3)[3]["order"] == [1, 0, 2]


def test_score_judges_the_planted_step_only():
    def v(verdict, checks, m=(), o=()):
        return {"verdict": verdict, "missing_steps": list(m), "out_of_order_steps": list(o), "checks": checks}
    c = lambda i, st="observed", **kw: dict({"reference_step": i, "status": st}, **kw)
    ref = {"steps": [{"index": 0, "self_check": "observed"}, {"index": 1, "self_check": "observed"},
                     {"index": 2, "self_check": "not_observed"}]}
    omit = {"kind": "omit", "steps": [1]}
    assert score(omit, v("fail", [c(0), c(1, "not_observed"), c(2)], m=[1]), ref)["outcome"] == "caught"
    assert score(omit, v("review", [c(0), c(1), c(2, "unclear")]), ref)["outcome"] == "missed"   # review elsewhere
    assert score(omit, v("review", [c(0), c(1, shortened=True), c(2)]), ref)["outcome"] == "flagged"
    assert score({"kind": "omit", "steps": [2]}, v("pass", [c(0), c(1), c(2)]), ref)["outcome"] == "untestable"
    swap = {"kind": "swap", "steps": [0, 1]}
    assert score(swap, v("fail", [c(0, out_of_order=True), c(1, out_of_order=True), c(2)], o=[0, 1]), ref)["outcome"] == "caught"
    assert score(swap, v("pass", [c(0), c(1), c(2)]), ref)["outcome"] == "missed"
    assert score({"kind": "correct", "steps": []}, v("fail", [], m=[0]))["outcome"] == "false_alarm"


def test_refined_layout_drops_the_in_between_stretches_around_a_planted_mistake():
    from watchverify.bench import refined_layout, layout_pieces, plan_is_clean
    p = proc((1, 4), (6, 9), (10, 14), (15, 19))
    b = lambda i, e, s: {"after_step": i, "first_ends_s": e, "second_begins_s": s, "fps": 4.0, "clean": 0 <= e < s}
    cores, gaps, clean = refined_layout(p, 20, [b(0, 4.5, 6.5), b(1, 10.25, 9.75), b(2, 14.5, 15.5)])
    assert clean == [True, False, True]
    assert gaps == [(4.625, 6.375), (9.5, 9.5), (14.625, 15.375)]            # boundary 1 not clean: midpoint 9.5
    assert cores == [(0.0, 4.625), (6.375, 9.5), (9.5, 14.625), (15.375, 20)]
    assert layout_pieces([0, 1, 2, 3], cores, gaps) == [(0.0, 20)]             # the expert's order: the whole clip
    assert layout_pieces([1, 2, 3], cores, gaps) == [(6.375, 20)]              # step 0 and the move after it gone
    assert layout_pieces([0, 1, 3, 2], cores, gaps) == [(0.0, 9.5), (15.375, 20), (9.5, 14.625)]   # swap 2,3: gap 2 gone
    assert layout_pieces([0, 1, 2], cores, gaps) == [(0.0, 14.625)]
    plans = {pl["name"]: pl for pl in variant_plans(4)}
    assert plan_is_clean(plans["omit0"], clean) and plan_is_clean(plans["omit3"], clean)
    assert not plan_is_clean(plans["omit1"], clean) and not plan_is_clean(plans["omit2"], clean)
    assert not plan_is_clean(plans["swap01"], clean) and not plan_is_clean(plans["swap23"], clean)
    # a boundary that would leave a step under half a second of working time is not clean
    cores, gaps, clean = refined_layout(p, 20, [b(0, 8.8, 9.2), b(1, 9.3, 9.6), b(2, 14.5, 15.5)])
    assert clean[:2] == [False, False] and all(y - x >= 0.5 for x, y in cores)


def test_boundary_request_sends_time_labeled_frames(tmp_path):
    import asyncio, json, subprocess
    from watchverify import media
    from watchverify.bench import refine_boundaries
    clip = tmp_path / "clip.mp4"
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-t", "12",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    sent = []

    class Fake:
        async def structured(self, key, name, schema, instructions, content, **kw):
            sent.append(content)
            labels = [c["text"] for c in content if c["type"] == "input_text" and c["text"].startswith("t=")]
            return {"first_ends_s": float(labels[3][2:-2]), "second_begins_s": float(labels[6][2:-2]), "evidence": "e"}, {}
    ref = proc((1, 4), (6, 9), (10, 11))
    for st in ref["steps"]:
        st.update(action=f"a{st['index']}", objects=[], observable_checkpoint="c")
    res = asyncio.run(refine_boundaries(Fake(), ref, clip, tmp_path))
    assert len(res) == 2 and all(r["clean"] for r in res)
    first = sent[0]
    assert sum(c["type"] == "input_image" for c in first) == res[0]["frames"] >= 20   # 8 s window at 4 fps
    assert res[0]["window"] == [2.0, 8.0] and res[0]["fps"] == 4.0
    assert json.loads((tmp_path / "reference.boundaries.json").read_text()) == res
    assert json.loads((tmp_path / "boundary-frames" / "b1.json").read_text()) == res[1]     # each saved as it lands


def test_unclean_boundary_gets_one_wider_look(tmp_path):
    import asyncio, subprocess
    from watchverify import media
    from watchverify.bench import refine_boundaries
    clip = tmp_path / "clip.mp4"
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-t", "12",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    keys = []

    class Fake:
        async def structured(self, key, name, schema, instructions, content, **kw):
            keys.append(key)
            return ({"first_ends_s": -1, "second_begins_s": 7.0, "evidence": "e"} if not key.endswith(".wide") else
                    {"first_ends_s": 5.0, "second_begins_s": 6.5, "evidence": "e"}), {}
    ref = proc((1, 4), (6, 9))
    res = asyncio.run(refine_boundaries(Fake(), ref, clip, tmp_path))
    assert keys == ["boundary0", "boundary0.wide"] and res[0]["clean"] and res[0]["window"] == [0.5, 9.5]
    assert res[0]["narrow"]["first_ends_s"] == -1
    asyncio.run(refine_boundaries(Fake(), ref, clip, tmp_path))
    assert len(keys) == 2                                    # saved: a rerun asks nothing


def test_results_page_module_imports():
    import pytest
    import watchverify.bench_report, watchverify.cli      # syntax errors in modules no other test imports
    with pytest.raises(SystemExit) as ex:                  # builds every subcommand's options, then prints help
        watchverify.cli.main(["bench-score", "--help"])
    assert ex.value.code == 0


def _source(root, n=3, marks=None, checks=None, pre=""):
    """A saved source for rescoring: an n-step reference (self-check marks per step) and the saved checks named."""
    import json
    from watchverify import schema
    d = root / "bench-src"; d.mkdir(parents=True)
    ref = {"task": "t", "steps": [{"index": i, "start_s": 2.0 * i, "end_s": 2.0 * i + 1.5, "checkpoint_visibility": "clear", "action": f"act{i}",
                                   "self_check": (marks or {}).get(i, "observed")} for i in range(n)]}
    (d / "reference.procedure.json").write_text(json.dumps(ref))
    chk = lambda i, st: {"reference_step": i, "status": st, "observed_start_s": 2.0 * i, "observed_end_s": 2.0 * i + 1.5,
                         "evidence": "e", "cannot_see": "none"}
    def check(missing=()):
        return {"checks": [chk(i, "not_observed" if i in missing else "observed") for i in range(n)]}
    for name, missing in (checks or {}).items():
        f = d / ("reference.selfcheck.json" if name == "selfcheck" else f"{pre}verify-{name}.json")
        f.write_text(json.dumps(schema.apply_order_rules(ref, check(missing))))     # saved as verify_video leaves them
    return d


def test_every_plan_has_a_row_and_each_exclusion_says_who_decided(tmp_path):
    from watchverify.bench import rescore_results, full_rows_problems, tally, MODEL_UNDER_TEST
    _source(tmp_path, marks={2: "not_observed"},
            checks={"selfcheck": [2], "omit0": [0], "omit2": [], "swap01": [], "correct": []})   # omit1, swap12 never checked
    rows = rescore_results(tmp_path)
    assert full_rows_problems(rows, {"src": 3}) == []
    by = {r["name"]: r for r in rows}
    assert by["omit0"]["outcome"] == "caught" and by["omit0"]["graded"]
    assert by["omit1"]["outcome"] == "not_checked" and not by["omit1"]["graded"] and by["omit1"]["excluded_by"] == "code"
    assert by["omit2"]["outcome"] == "untestable" and by["omit2"]["excluded_by"] == MODEL_UNDER_TEST
    assert not by["selfcheck"]["graded"] and "calibration" in by["selfcheck"]["why"]
    t = tally(rows)["omit"]
    assert (t["planted"], t["graded"]) == (3, 1)
    # the same saved checks without the self-check marks: the planted step 2 is graded, and missed
    by = {r["name"]: r for r in rescore_results(tmp_path, off=("marks",))}
    assert by["omit2"]["graded"] and by["omit2"]["outcome"] == "missed"
    assert full_rows_problems(rows[:-1], {"src": 3})                       # a lost row is caught


def test_softenings_switch_off_one_at_a_time():
    from watchverify import schema
    ref = {"steps": [{"index": 0, "start_s": 0, "end_s": 1, "self_check": "not_observed", "checkpoint_visibility": "clear"},
                     {"index": 1, "start_s": 2, "end_s": 3, "self_check": "observed", "checkpoint_visibility": "narration_only"}]}
    v = lambda: {"checks": [{"reference_step": i, "status": "not_observed", "observed_start_s": -1, "observed_end_s": -1,
                             "evidence": "e", "cannot_see": "none"} for i in (0, 1)]}
    assert schema.apply_order_rules(ref, v())["missing_steps"] == []
    assert schema.apply_order_rules(ref, v(), use_marks=False)["missing_steps"] == [0]
    assert schema.apply_order_rules(ref, v(), use_narration=False)["missing_steps"] == [1]
    import pytest
    from watchverify.bench import rescore_results
    with pytest.raises(ValueError):
        rescore_results("nowhere", off=("timnig",))                     # a misspelled switch is refused, not ignored


def test_review_on_an_untouched_step_is_counted():
    v = {"verdict": "review", "missing_steps": [], "out_of_order_steps": [],
         "checks": [{"reference_step": 0, "status": "not_observed"}, {"reference_step": 1, "status": "observed"},
                    {"reference_step": 2, "status": "unclear"}]}
    s = score({"kind": "omit", "steps": [0]}, dict(v, missing_steps=[0]))
    assert s["outcome"] == "caught" and s["extras"] == [] and s["extras_review"] == [2]


def test_one_failed_check_does_not_lose_the_source(tmp_path, monkeypatch):
    import asyncio, json, subprocess
    from watchverify import bench, media
    d = _source(tmp_path, checks={"selfcheck": []})
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-t", "6",
                    "-pix_fmt", "yuv420p", str(d / "clip.mp4")], check=True)

    async def fake_verify(client, ref, video, run_dir, name, *a, **kw):
        if name.endswith("omit1"):
            raise RuntimeError("upload refused")
        steps = [0, 1] if name.endswith("omit2") else [0, 1, 2]       # a reply missing the planted step: scoring raises
        v = {"checks": [{"reference_step": i, "status": "observed", "observed_start_s": 2.0 * i, "observed_end_s": 2.0 * i + 1,
                         "evidence": "e", "cannot_see": "none"} for i in steps]}
        return bench.schema.apply_order_rules(ref, v)
    monkeypatch.setattr(bench, "make_client", lambda *a, **kw: None)
    monkeypatch.setattr(bench, "verify_video", fake_verify)
    rows = asyncio.run(bench.run_variants("src", tmp_path, 0.0))
    assert bench.full_rows_problems(rows, {"src": 3}) == []
    by = {r["name"]: r for r in rows}
    assert by["omit1"]["outcome"] == "error" and "upload refused" in by["omit1"]["error"] and not by["omit1"]["graded"]
    assert by["omit2"]["outcome"] == "error" and not by["omit2"]["graded"]
    assert by["omit0"]["outcome"] == "missed" and json.loads((d / "bench-results.json").read_text())


def _labels(d, made_by="human:owner", visible=(True, True, True)):
    import json
    (d / "labels.json").write_text(json.dumps({"made_by": made_by, "prelabeled_by": "model:prelabeler (from stills)", "steps": [
        {"index": i, "start_s": 2.0 * i + 0.2, "end_s": 2.0 * i + 1.6, "visible": vis} for i, vis in enumerate(visible)]}))


def test_held_out_grading_refuses_model_drawn_truth_before_any_call(tmp_path, monkeypatch):
    import asyncio, json, pytest, subprocess
    from watchverify import bench, media
    repo = tmp_path / "repo"; (repo / "bench").mkdir(parents=True)
    video = tmp_path / "downloaded.webm"; video.write_bytes(b"pretend video bytes")
    (repo / "bench" / "holdout.json").write_text(json.dumps({"picked": ["How to open X"], "downloads": []}))
    bench.register_download(repo / "bench" / "holdout.json", "How to open X", "src", video)
    with pytest.raises(ValueError):
        bench.register_download(repo / "bench" / "holdout.json", "Not drawn", "y", video)
    d = _source(repo / "runs" / "any-name-at-all", checks={"selfcheck": []})      # the folder name means nothing
    (d / "source.json").write_text(json.dumps({"sid": "src", "sha256": bench.sha256_file(video)}))
    assert bench.is_holdout(d)
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-t", "6",
                    "-pix_fmt", "yuv420p", str(d / "clip.mp4")], check=True)

    def no_client(*a, **kw):
        raise AssertionError("a model client was made before the refusal")
    monkeypatch.setattr(bench, "make_client", no_client)
    root = d.parent
    for cuts in ("midpoint", "refined", "labels"):                   # labels.json not there yet
        with pytest.raises(PermissionError):
            asyncio.run(bench.run_variants("src", root, 1.0, cuts=cuts))
        with pytest.raises(PermissionError):
            bench.rescore_results(root, cuts=cuts)
    with pytest.raises(PermissionError):
        asyncio.run(bench.boundaries_for("src", root, 1.0))
    _labels(d, made_by="model:muse-spark-1.3")                       # a model's labels are not a person's
    with pytest.raises(PermissionError):
        bench.rescore_results(root, cuts="labels")
    _labels(d)                                                       # a person's, but not committed yet
    with pytest.raises(PermissionError):
        bench.rescore_results(root, cuts="labels")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "bench" / "holdout-labels").mkdir()
    (repo / "bench" / "holdout-labels" / "src.json").write_text((d / "labels.json").read_text())
    git("add", "bench"); git("commit", "-qm", "labels")
    assert bench.independence_problems(d, "labels") == []
    rows = bench.rescore_results(root, cuts="labels")                 # person-confirmed and committed: allowed
    assert bench.full_rows_problems(rows, {"src": 3}) == []
    _labels(d, visible=(True, False, True))                          # changed after the commit: refused again
    with pytest.raises(PermissionError):
        bench.rescore_results(root, cuts="labels")
    # an unregistered source is development work, even in a folder called holdout
    dev = _source(tmp_path / "holdout", checks={"selfcheck": []})
    assert not bench.is_holdout(dev) and bench.rescore_results(tmp_path / "holdout", cuts="midpoint")


def test_labels_cut_and_a_persons_visibility_call_decides_what_is_graded(tmp_path):
    from watchverify import bench
    d = _source(tmp_path, marks={0: "not_observed"},
                checks={"selfcheck": [0], "omit0": [], "omit1": [1], "omit2": [2], "swap01": [], "swap12": [], "correct": []})
    for f in list(d.glob("verify-*.json")):                          # the same checks under the labels method's names
        (d / f"labels-{f.name}").write_text(f.read_text())
    _labels(d, visible=(True, True, False))
    lab = bench.load_labels(d)
    cores, gaps, clean = bench.refined_layout(lab, 6.0, bench.labels_boundaries(lab))
    assert clean == [True, True] and gaps == [(1.6, 2.2), (3.6, 4.2)] and cores[0] == (0.0, 1.6) and cores[2] == (4.2, 6.0)
    by = {r["name"]: r for r in bench.rescore_results(tmp_path, cuts="midpoint")}
    assert by["omit0"]["outcome"] == "untestable"                    # midpoint: the self-check marks exclude step 0
    (d / "clip.mp4").write_bytes(b"")
    import watchverify.media as media
    orig = media.count_frames_and_secs
    media.count_frames_and_secs = lambda p: (0, 6.0)
    try:
        by = {r["name"]: r for r in bench.rescore_results(tmp_path, cuts="labels")}
        open_ = {r["name"]: r for r in bench.rescore_results(tmp_path, cuts="labels", off=("selection",))}
    finally:
        media.count_frames_and_secs = orig
    assert by["omit0"]["graded"] and by["omit0"]["outcome"] == "missed"     # labels: marks no longer exclude
    for n in ("omit2", "swap12"):
        assert by[n]["outcome"] == "not_visible" and by[n]["excluded_by"] == "human" and not by[n]["graded"]
    assert open_["omit2"]["graded"] and open_["omit2"]["outcome"] == "caught"   # the call switched off: graded


def test_a_removed_step_explained_away_is_its_own_outcome_and_scoring_never_rewrites_evidence(tmp_path):
    from watchverify.bench import rescore_results
    v = {"verdict": "review", "missing_steps": [], "out_of_order_steps": [],
         "checks": [{"reference_step": 0, "status": "done_differently"}, {"reference_step": 1, "status": "observed"}]}
    assert score({"kind": "omit", "steps": [0]}, v)["outcome"] == "explained_away"
    d = _source(tmp_path, checks={"selfcheck": [], "omit0": [0], "omit1": []})
    before = {f.name: f.read_bytes() for f in d.glob("*.json")}
    rescore_results(tmp_path); rescore_results(tmp_path, off=("marks",))
    assert {f.name: f.read_bytes() for f in d.glob("*.json")} == before


def test_a_held_out_page_builds_from_person_labels_and_counts_missed_steps(tmp_path):
    import json, subprocess
    from watchverify import bench, bench_report, media
    repo = tmp_path / "repo"; (repo / "bench").mkdir(parents=True)
    video = tmp_path / "v.webm"; video.write_bytes(b"bytes of a held-out video")
    (repo / "bench" / "holdout.json").write_text(json.dumps({"picked": ["How to open X"], "downloads": []}))
    bench.register_download(repo / "bench" / "holdout.json", "How to open X", "src", video, author="A", license="CC BY", url="u")
    root = repo / "runs" / "holdout"
    d = _source(root, checks={"selfcheck": [], "omit0": [0], "omit1": [], "omit2": [], "swap01": [], "swap12": [], "correct": []},
                pre="labels-")
    (d / "source.json").write_text(json.dumps({"sid": "src", "sha256": bench.sha256_file(video)}))
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15", "-t", "6",
                    "-pix_fmt", "yuv420p", str(d / "clip.mp4")], check=True)
    _labels(d, visible=(True, True, False))
    lab = json.loads((d / "labels.json").read_text()); lab["missed_steps"] = ["a screw at the back"]
    (d / "labels.json").write_text(json.dumps(lab))
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "bench" / "holdout-labels").mkdir(); (repo / "bench" / "holdout-labels" / "src.json").write_text(json.dumps(lab))
    git("add", "bench"); git("commit", "-qm", "labels")
    rows = bench.rescore_results(root, cuts="labels")
    assert bench.full_rows_problems(rows, {"src": 3}) == []
    by = {r["name"]: r for r in rows}
    assert by["never0"]["outcome"] == "never_extracted" and by["omit2"]["outcome"] == "not_visible"
    assert bench.tally(rows)["omit"]["planted"] == 4                  # the missed step counts among the planted removals
    out = bench_report.write(root, repo / "bench" / "holdout.json", tmp_path / "page.html", cuts="labels")
    page = out.read_text()
    assert "A person confirmed" in page and "human:owner" in page and "never extracted" in page
    a, b = bench.seeded_window("ab" * 32, 300.0)
    assert (a, b) == bench.seeded_window("ab" * 32, 300.0) and b - a == 60.0 and 0 <= a <= 240
    assert bench.seeded_window("ab" * 32, 40.0) == (0.0, 40.0)
