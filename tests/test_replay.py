"""Committed grading evidence re-scores to the same result without the video, the network or a key, and a changed
answer changes the result. A fake live transport saves raw responses the way LiveTransport does."""
import asyncio, json, subprocess
import pytest
from pathlib import Path
from watchverify import media
from watchverify.budget import Budget
from watchverify.ledger import Ledger
from watchverify.meta_client import MetaClient, ReplayTransport
from watchverify.replay import ReplayMedia
from watchverify.verify import verify_video

REF = {"task": "pry open a cover", "steps": [
    {"index": 0, "start_s": 0.5, "end_s": 1.5, "action": "pry left corner", "objects": ["pry tool"],
     "observable_checkpoint": "gap at left corner", "pass_condition": "gap", "cannot_see": "none", "checkpoint_visibility": "clear"},
    {"index": 1, "start_s": 2.0, "end_s": 3.5, "action": "pry right corner", "objects": ["pry tool"],
     "observable_checkpoint": "gap at right corner", "pass_condition": "gap", "cannot_see": "none", "checkpoint_visibility": "clear"}]}


class SavingFake:
    """Answers like the model (step 0 seen, step 1 not, the second look agrees) and saves like LiveTransport."""
    def __init__(self, raw: Path):
        self.raw = raw; raw.mkdir(parents=True, exist_ok=True)

    def _save(self, key, d):
        (self.raw / f"{key}.json").write_text(json.dumps(d))

    async def upload(self, path, key, name):
        self._save(key, {"id": f"file-{key}"}); return f"file-{key}"

    async def responses_create(self, key, **kw):
        if kw["text"]["format"]["name"] == "video_verification":
            out = {"same_task": True, "extra_actions": [], "notes": "", "checks": [
                {"reference_step": 0, "status": "observed", "observed_start_s": 0.4, "observed_end_s": 1.4, "evidence": "e", "cannot_see": "none"},
                {"reference_step": 1, "status": "not_observed", "observed_start_s": -1, "observed_end_s": -1, "evidence": "e", "cannot_see": "none"}]}
        else:
            out = {"status": "not_observed", "observed_start_s": -1, "observed_end_s": -1, "evidence": "e"}
        d = {"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 10},
             "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(out)}]}]}
        self._save(key, d); return d


def test_replay_rebuilds_the_check_and_notices_a_changed_answer(tmp_path):
    video = tmp_path / "cand.mp4"
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5", "-t", "4",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    live_dir = tmp_path / "live"; raw = live_dir / "raw"
    ledger = Ledger(live_dir / "ledger.jsonl")
    live = asyncio.run(verify_video(MetaClient(SavingFake(raw), ledger, Budget(ledger, 1.0)), REF, video, live_dir, "verify-x"))
    assert live["verdict"] == "fail" and live["_source"]["duration_s"] > 3.9

    def replay():
        d = tmp_path / "replay"; d.mkdir(exist_ok=True)
        lg = Ledger(d / "ledger.jsonl")
        return asyncio.run(verify_video(MetaClient(ReplayTransport(raw), lg, Budget(lg, 1.0)), REF, d / "gone.mp4", d,
                                        "verify-x", reference_video=d / "no-expert-video",
                                        m=ReplayMedia(live["_source"]["duration_s"], None)))
    again = replay()
    strip = lambda v: [(c["reference_step"], c["status"], c.get("out_of_order")) for c in v["checks"]]
    assert strip(again) == strip(live) and again["verdict"] == live["verdict"]
    f = raw / "verify-x.look.step1.json"; d = json.loads(f.read_text())
    d["output"][0]["content"][0]["text"] = json.dumps({"status": "observed", "observed_start_s": 0.5, "observed_end_s": 1.5, "evidence": "e"})
    f.write_text(json.dumps(d))
    assert replay()["verdict"] != live["verdict"]           # the committed answers decide the result


def test_export_then_replay_matches_and_each_input_can_be_swapped(tmp_path, monkeypatch):
    """A whole source through the bench code with the fake model: export, replay as exported (every row matches),
    then with the self-check marks swapped for the neutral file (the step the self-check missed becomes gradable)."""
    from watchverify import bench, schema
    from watchverify.replay import export_evidence, replay_evidence
    run_dir = tmp_path / "runs" / "bench-src"; raw = run_dir / "raw"
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5", "-t", "4",
                    "-pix_fmt", "yuv420p", str(run_dir.parent.mkdir(parents=True) or run_dir.mkdir() or run_dir / "clip.mp4")], check=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    client = MetaClient(SavingFake(raw), ledger, Budget(ledger, 1.0))
    ref = json.loads(json.dumps(REF))
    asyncio.run(verify_video(client, ref, run_dir / "clip.mp4", run_dir, "reference.selfcheck", run_dir / "clip.mp4"))
    ref = schema.annotate_self_check(ref, json.loads((run_dir / "reference.selfcheck.json").read_text()))
    assert [st["self_check"] for st in ref["steps"]] == ["observed", "not_observed"]
    (run_dir / "reference.procedure.json").write_text(json.dumps(ref))
    monkeypatch.setattr(bench, "make_client", lambda *a, **kw: client)
    rows = asyncio.run(bench.run_variants("src", tmp_path / "runs", 1.0))
    assert {r["name"]: r["outcome"] for r in rows}["omit1"] == "untestable"
    ev = tmp_path / "evidence" / "src"
    summary = export_evidence(run_dir, ev, cuts="midpoint")
    assert summary["planted"] == 4 and summary["checked"] == 4
    r = replay_evidence(ev)
    assert r["as_exported"] and r["checks"] == 5 and r["matches"] == 5
    assert r["totals"]["omit"]["untestable"] == 1 and r["totals"]["correct"]["flagged"] == 1
    w = replay_evidence(ev, ("marks",))
    assert not w["as_exported"] and w["totals"]["omit"].get("untestable", 0) == 0
    assert w["totals"]["omit"]["graded"] == 2 and w["totals"]["correct"]["false_alarm"] == 1     # the softening, shown
    for off in (("marks",), ("timing", "selection")):                # each with-and-without row of bench-score replays
        o = replay_evidence(ev, off=off)
        assert not o["as_exported"] and o["totals"] == bench.tally(bench.rescore_results(tmp_path / "runs", off=off))
    with pytest.raises(ValueError, match="unknown switches"):
        replay_evidence(ev, off=("confrim",))


def test_replay_refuses_names_that_could_leave_the_evidence_folder(tmp_path):
    """Someone else's evidence names the checks; a name with a separator or a leading dot would make replay read
    and write files where that person chose (found by the security review of 2026-10-28)."""
    import pytest
    from watchverify.meta_client import safe_name
    from watchverify.replay import replay_evidence
    ev = tmp_path / "evil"; (ev / "raw").mkdir(parents=True); (ev / "neutral").mkdir()
    for f in ("marks.json", "neutral/no-marks.json"):
        (ev / f).write_text(json.dumps({"steps": {}}))
    for f in ("narration.json", "neutral/no-narration.json"):
        (ev / f).write_text(json.dumps({"steps": []}))
    for f in ("selection.json", "neutral/all-clean.json"):
        (ev / f).write_text(json.dumps({"made_by": "code", "clean": None}))
    for f in ("reference.grounding.json", "neutral/no-grounding.json"):
        (ev / f).write_text("{}")
    (ev / "reference.procedure.json").write_text(json.dumps(REF))
    (ev / "plans.json").write_text(json.dumps({"source": "s", "cuts": "midpoint", "plans": [
        {"name": "omit1", "order": [0], "truth": {"kind": "omit", "steps": [1]}, "checked": True,
         "check": "../../escaped/pwned", "duration_s": 4.0, "track_frames": None, "claimed": {"outcome": "caught"}}]}))
    with pytest.raises(ValueError):
        replay_evidence(ev)
    assert not (tmp_path / "escaped").exists()
    for bad in ("../x", "a/b", ".hidden", "", "x\\y", "a\nb"):
        with pytest.raises(ValueError):
            safe_name(bad)
    assert safe_name("refined-v2-verify-omit3.look.step2") == "refined-v2-verify-omit3.look.step2"


def test_confirm_looks_are_asked_for_placed_steps_and_replay(tmp_path):
    """A confirm look at the stretch where the check placed step 0 (the fake model never sees it there): step 0 goes
    to review; the check rebuilds the same from its saved answers."""
    video = tmp_path / "cand.mp4"
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5", "-t", "4",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    live_dir = tmp_path / "live"; raw = live_dir / "raw"
    ledger = Ledger(live_dir / "ledger.jsonl")
    live = asyncio.run(verify_video(MetaClient(SavingFake(raw), ledger, Budget(ledger, 1.0)), REF, video, live_dir,
                                    "verify-x", confirm=True))
    assert (raw / "verify-x.confirm.step0.json").exists() and not (raw / "verify-x.confirm.step1.json").exists()
    c0 = live["checks"][0]
    assert c0["confirm_look"]["status"] == "not_observed" and "confirm_not_seen" in c0["reasons"] and c0["disputed"]
    d = tmp_path / "replay"; d.mkdir()
    lg = Ledger(d / "ledger.jsonl")
    again = asyncio.run(verify_video(MetaClient(ReplayTransport(raw), lg, Budget(lg, 1.0)), REF, d / "gone.mp4", d, "verify-x",
                                     reference_video=d / "no-expert-video", m=ReplayMedia(live["_source"]["duration_s"], None),
                                     confirm=True))
    assert [c.get("reasons") for c in again["checks"]] == [c.get("reasons") for c in live["checks"]]
