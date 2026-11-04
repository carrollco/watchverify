"""The run page's --only option: shows just the named checks, in order, and costs only their calls."""
import json
from pathlib import Path
import pytest
from watchverify.report import write_report

STEP = {"index": 0, "action": "pry open corner", "start_s": 0.0, "end_s": 2.0, "objects": ["pry tool"],
        "observable_checkpoint": "gap at corner", "visibility": "clear", "pass_condition": "gap visible",
        "cannot_see": "force used", "tools": ["pry tool"], "narration": ""}


def check(verdict):
    return {"verdict": verdict, "checks": [{"reference_step": 0, "status": "observed", "observed_start_s": 0.5,
            "observed_end_s": 1.5, "evidence": "tool at corner", "cannot_see": "force"}], "extra_actions": []}


def ledger_line(key, cost):
    return json.dumps({"key": key, "model": "m", "endpoint": "responses", "cost_usd": cost, "latency_s": 1,
                       "units": {}, "note": "", "ts": 0, "live": True})


def make_run(tmp_path: Path) -> Path:
    (tmp_path / "reference.procedure.json").write_text(json.dumps({"task": "open a case", "steps": [STEP]}))
    (tmp_path / "verify-a.json").write_text(json.dumps(check("pass")))
    (tmp_path / "verify-b.json").write_text(json.dumps(check("fail")))
    (tmp_path / "ledger.jsonl").write_text("\n".join([ledger_line("reference.procedure", 0.10),
                                                      ledger_line("verify-a.first", 0.02),
                                                      ledger_line("verify-b.first", 0.40)]) + "\n")
    return tmp_path


def test_only_shows_named_checks_and_their_cost(tmp_path):
    run = make_run(tmp_path)
    page = write_report(run, only=["verify-a"], out=run / "demo.html").read_text()
    assert "verify-a" in page and "verify-b" not in page
    assert "$0.120" in page and "2 calls" in page


def test_without_only_everything_is_shown(tmp_path):
    run = make_run(tmp_path)
    page = write_report(run).read_text()
    assert "verify-a" in page and "verify-b" in page and "$0.520" in page


def test_unknown_name_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        write_report(make_run(tmp_path), only=["verify-z"])
