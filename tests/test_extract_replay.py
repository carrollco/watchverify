"""Replay of a real Spark response (fixture made from the 2026-10-26 probe, CC BY clip). No network."""
import asyncio, json
from pathlib import Path
from watchverify.meta_client import make_client
from watchverify.extract import extract
from watchverify import schema

FIX = Path(__file__).parent / "fixtures"


def test_extract_from_replay(tmp_path):
    client = make_client(tmp_path, ceiling_usd=1.0, replay_dir=FIX)
    video = tmp_path / "clip.mp4"; video.write_bytes(b"not a real video; replay ignores it")
    proc = asyncio.run(extract(client, video, tmp_path, "reference"))
    assert proc["task"].startswith("pry open laptop bottom cover")
    assert len(proc["steps"]) == 4 and proc["steps"][1]["objects"][0] == "blue plastic pry tool"
    assert schema.validate_procedure(proc) == []
    assert "corners are already lifted" in proc["speech_heard"].lower()
    led = client.ledger.entries()
    assert [e["endpoint"] for e in led] == ["files", "responses"]
    assert round(led[1]["cost_usd"], 4) == 0.0148          # 5,816 in, 1,767 out at the docs' rates
    assert (tmp_path / "reference.procedure.json").exists()


def test_strict_schema_shape():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values(): walk(v)
        elif s.get("type") == "array":
            walk(s["items"])
    walk(schema.PROCEDURE); walk(schema.VIDEO_VERIFICATION); walk(schema.SECOND_LOOK)


def test_order_rules_decide_verdict():
    ref = {"steps": [{"index": i} for i in range(3)]}
    def chk(i, st, t): return {"reference_step": i, "status": st, "observed_start_s": t, "observed_end_s": t + 1, "evidence": "", "cannot_see": "none"}
    ok = schema.apply_order_rules(ref, {"checks": [chk(0, "observed", 0), chk(1, "observed", 5), chk(2, "observed", 9)]})
    assert ok["verdict"] == "pass" and ok["out_of_order_steps"] == []
    swapped = schema.apply_order_rules(ref, {"checks": [chk(0, "observed", 0), chk(1, "observed", 9), chk(2, "observed", 5)]})
    assert swapped["verdict"] == "fail" and swapped["out_of_order_steps"] == [1, 2]
    omitted = schema.apply_order_rules(ref, {"checks": [chk(0, "observed", 0), chk(1, "not_observed", -1), chk(2, "observed", 5)]})
    assert omitted["verdict"] == "fail" and omitted["missing_steps"] == [1]
    unclear = schema.apply_order_rules(ref, {"checks": [chk(0, "observed", 0), chk(1, "unclear", -1), chk(2, "observed", 5)]})
    assert unclear["verdict"] == "review" and unclear["unclear_steps"] == [1]
