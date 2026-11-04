"""The held-out path end to end: bench.run_variants with person-confirmed label cuts, SAM timing included. Canaries
sit in the labels (the cut points and the labeler), the model's own seconds and the run folder's names; a recording
transport captures every request and upload name, and the test fails if any canary, a planted mistake's name or the
cut method reaches the model. No network: canned responses, tiny ffmpeg test videos."""
import asyncio, json
from watchverify import bench
from watchverify.budget import Budget
from watchverify.ledger import Ledger
from watchverify.meta_client import MetaClient
from test_leaks import Recorder, tiny_video

HIDDEN = ["1.234567", "2.345678", "1.777777", "4.987654", "6.456789", "5.111111",   # the model's reference seconds
          "3.135791", "4.246802", "7.358024"]                                        # the labels' cut points


def boxes(a, b, x, fps=5):
    return [dict(frame=f, t=f / fps, object_id="0", left=x - 5, top=50, right=x + 5, bottom=60, confidence=0.7)
            for f in range(int(a * fps), int(b * fps))]


class TwoStepRecorder(Recorder):
    """Like Recorder, counting SAM timing calls, so the SAM upload and request are known to be checked too."""
    sam_calls = 0

    async def segment(self, key, **kw):          # key is the ledger's name for the call; it is never sent
        self.sam_calls += 1
        self.sent.append(json.dumps(kw))
        return {"boxes": []}


def make_source(tmp_path, steps):
    run_dir = tmp_path / "runs" / "bench-CANARY_SID"; run_dir.mkdir(parents=True)
    tiny_video(run_dir / "clip.mp4", seconds=8)
    ref = {"task": "pry open a cover", "objects_seen": [], "track": ["pry tool"], "_source": {"video": "CANARY_SRC"},
           "steps": [dict(index=i, start_s=a, end_s=b, evidence_s=e, self_check="observed", action=f"pry corner {i}",
                          objects=["pry tool"], observable_checkpoint="gap", pass_condition="gap", cannot_see="clips",
                          checkpoint_visibility="clear") for i, (a, b, e) in enumerate(steps["ref"])]}
    (run_dir / "reference.procedure.json").write_text(json.dumps(ref))
    (run_dir / "reference.selfcheck.json").write_text(json.dumps({"verdict": "pass", "checks": [], "missing_steps": [], "out_of_order_steps": [], "unclear_steps": []}))
    (run_dir / "labels.json").write_text(json.dumps({"made_by": "human:CANARY_LABELER", "prelabeled_by": "CANARY_PRE",
        "steps": [dict(index=i, start_s=a, end_s=b, visible=True, is_step=True) for i, (a, b) in enumerate(steps["labels"])]}))
    (run_dir / "reference.grounding.json").write_text(json.dumps({"track_fps": 5, "width": 160, "phrases": ["pry tool"],
        "tracks": {"pry tool": boxes(0, 3, 30) + boxes(4, 8, 130)}}))
    return run_dir


def run(tmp_path, monkeypatch, steps, rec):
    run_dir = make_source(tmp_path, steps)
    ledger = Ledger(run_dir / "ledger.jsonl")
    monkeypatch.setattr(bench, "make_client", lambda d, budget: MetaClient(rec, ledger, Budget(ledger, 1.0)))
    return asyncio.run(bench.run_variants("CANARY_SID", run_dir.parent, 1.0, cuts="labels", checker="v2"))


def test_labels_path_sends_no_answer_key(tmp_path, monkeypatch):
    rec = TwoStepRecorder()
    rows = run(tmp_path, monkeypatch, {"ref": [(1.234567, 2.345678, 1.777777), (4.987654, 6.456789, 5.111111)],
                                       "labels": [(0.5, 3.135791), (4.246802, 7.358024)]}, rec)
    assert {r["name"] for r in rows} >= {"omit0", "omit1", "swap01", "correct"}
    assert not [r for r in rows if r["outcome"] == "error"], [r.get("error") for r in rows if r["outcome"] == "error"]
    assert rec.sam_calls >= 4, "the SAM timing call ran for every clip, so its requests and uploads were checked"
    sent = "\n".join(rec.sent)
    assert "CANARY" not in sent, [line[:200] for line in sent.splitlines() if "CANARY" in line][:3]
    for n in HIDDEN:
        assert n not in sent, f"a hidden second leaked: {n}"
    low = sent.lower()
    assert "omit" not in low and "swap" not in low and "labels" not in low and "holdout" not in low


def test_removing_a_one_step_clips_only_step_is_not_graded_and_costs_nothing(tmp_path, monkeypatch):
    rec = TwoStepRecorder()
    rows = run(tmp_path, monkeypatch, {"ref": [(1.234567, 6.456789, 5.111111)], "labels": [(0.5, 7.358024)]}, rec)
    omit0 = next(r for r in rows if r["name"] == "omit0")
    assert omit0["outcome"] == "no_footage" and not omit0["graded"] and omit0["excluded_by"] == "code"
    assert not (tmp_path / "runs" / "bench-CANARY_SID" / "variants-labels" / "omit0.mp4").exists()
    assert not (tmp_path / "runs" / "bench-CANARY_SID" / "labels-v2-verify-omit0.json").exists()
