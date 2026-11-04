"""The README's offline re-score commands run with no key and no network, with a rule switched off too."""
import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    env = {k: v for k, v in os.environ.items() if k != "MODEL_API_KEY"}
    return subprocess.run([sys.executable, "-m", "watchverify.cli", "bench-replay", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)


def test_replay_with_a_rule_off_needs_no_key():
    r = run("evidence/checker-v2", "--off", "timing")
    assert r.returncode == 0, r.stderr[-500:]
    assert "rules off (timing)" in r.stdout


def test_exam_evidence_replays_and_matches():
    r = run("bench/holdout-evidence")
    assert r.returncode == 0, r.stderr[-500:]
    assert "64 match the claimed results" in r.stdout
