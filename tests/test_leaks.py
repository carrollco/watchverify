"""The answer key never reaches the model under test. Canaries are planted in every hidden place (the expert's
seconds, the self-check, the transcript and notes, the source path, a candidate file named after its planted
mistake); a recording transport captures everything the checker sends (requests, upload names), and the test fails
if any canary appears. No network: canned responses, tiny ffmpeg test videos."""
import asyncio, json, subprocess
from pathlib import Path
from watchverify import media
from watchverify.budget import Budget
from watchverify.ledger import Ledger
from watchverify.meta_client import MetaClient
from watchverify.verify import verify_video

CANARY_NUMBERS = ["1.234567", "2.345678", "1.777777", "2.987654", "3.456789", "3.111111",
                  "4.135791", "5.246802", "6.357913", "7.468024"]     # the last four: labels, boundaries, plans


class Recorder:
    """Captures what would be sent; answers with canned JSON: step 0 seen, step 1 not seen (so a second look runs)."""
    def __init__(self):
        self.sent: list[str] = []

    async def upload(self, path, key, name):
        self.sent.append(f"upload name={name}")
        return "file-1"

    async def responses_create(self, key, **kw):
        self.sent.append(json.dumps(kw))
        name = kw["text"]["format"]["name"]
        if name == "video_verification":
            out = {"same_task": True, "extra_actions": [], "notes": "", "checks": [
                {"reference_step": 0, "status": "observed", "observed_start_s": 0.2, "observed_end_s": 1.0, "evidence": "e", "cannot_see": "none"},
                {"reference_step": 1, "status": "not_observed", "observed_start_s": -1, "observed_end_s": -1, "evidence": "e", "cannot_see": "none"}]}
        else:
            out = {"status": "not_observed", "observed_start_s": -1, "observed_end_s": -1, "evidence": "e"}
        return {"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 10},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(out)}]}]}

    async def segment(self, key, **kw):
        self.sent.append(json.dumps(kw)); return {"boxes": []}

    async def transcribe(self, key, wav, settings):
        return {"turns": []}


def tiny_video(path: Path, seconds: int = 4) -> Path:
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=5",
                    "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_no_canary_reaches_the_model(tmp_path):
    secret_dir = tmp_path / "CANARY_SRC_DIR"; secret_dir.mkdir()
    expert = tiny_video(secret_dir / "expert-CANARY.mp4")
    candidate = tiny_video(secret_dir / "omit1-CANARY_TRUTH.mp4")
    reference = {
        "task": "pry open a cover", "objects_seen": ["CANARY_OBJECTS"], "speech_heard": "CANARY_SPEECH",
        "audio_notes": "CANARY_AUDIO", "uncertainty": "CANARY_UNCERTAINTY", "track": ["CANARY_TRACK"],
        "_source": {"video": str(expert)},
        "steps": [
            {"index": 0, "start_s": 1.234567, "end_s": 2.345678, "evidence_s": 1.777777, "self_check": "CANARY_SELF",
             "action": "pry left corner", "objects": ["pry tool"], "observable_checkpoint": "gap at left corner",
             "pass_condition": "gap", "cannot_see": "clips", "checkpoint_visibility": "clear"},
            {"index": 1, "start_s": 2.987654, "end_s": 3.456789, "evidence_s": 3.111111, "self_check": "observed",
             "action": "pry right corner", "objects": ["pry tool"], "observable_checkpoint": "gap at right corner",
             "pass_condition": "gap", "cannot_see": "clips", "checkpoint_visibility": "clear"}]}
    rec = Recorder()
    run_dir = tmp_path / "runs" / "leak"; run_dir.mkdir(parents=True)
    # the grading's other hidden files sit in the run folder, where later code could pick them up
    (run_dir / "labels.json").write_text(json.dumps({"made_by": "human:CANARY_LABELER", "steps": [
        {"index": 0, "start_s": 4.135791, "end_s": 5.246802, "visible": True, "is_step": True}]}))
    (run_dir / "reference.boundaries.json").write_text(json.dumps([{"after_step": 0, "window": [6.357913, 7.468024],
        "first_ends_s": 6.357913, "second_begins_s": 7.468024, "evidence": "CANARY_BOUNDARY_EVIDENCE", "clean": True}]))
    (run_dir / "plans.json").write_text(json.dumps({"plans": [{"name": "omit1", "truth": {"kind": "CANARY_TRUTH_KIND"},
        "pieces": [[4.135791, 5.246802]]}]}))
    ledger = Ledger(run_dir / "ledger.jsonl")
    client = MetaClient(rec, ledger, Budget(ledger, 1.0))
    v = asyncio.run(verify_video(client, reference, candidate, run_dir, "verify-omit1-CANARY_KEY"))
    assert any("second_look" in s for s in rec.sent), "the second look ran, so its request was checked too"
    sent = "\n".join(rec.sent)
    assert "CANARY" not in sent, [line for line in sent.splitlines() if "CANARY" in line][:3]
    for n in CANARY_NUMBERS:
        assert n not in sent, f"the expert's seconds leaked: {n}"
    assert "omit" not in sent.lower() and "swap" not in sent.lower()
    assert v["checks"][1]["second_look"]["status"] == "not_observed"
