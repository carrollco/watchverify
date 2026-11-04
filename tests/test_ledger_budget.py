import pytest
from watchverify.ledger import Ledger, Entry
from watchverify.budget import Budget, BudgetExceeded
from watchverify import pricing


def test_token_cost_matches_docs_rates():
    usage = {"input_tokens": 1_000_000, "input_tokens_details": {"cached_tokens": 200_000}, "output_tokens": 100_000}
    # 800k uncached at 1.25 + 200k cached at 0.15 + 100k out at 4.25 = 1.00 + 0.03 + 0.425
    assert round(pricing.token_cost("muse-spark-1.3", usage), 6) == 1.455


def test_sam_minimum_frames_and_transcribe_rounding():
    assert pricing.sam_video_cost(10) == pricing.sam_video_cost(50) == 0.01
    assert pricing.sam_video_cost(300) == 0.06
    assert round(pricing.transcribe_cost(20.9), 6) == round(20 / 3600 * 0.18, 6)


def test_ledger_and_budget(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    b = Budget(led, ceiling_usd=0.10)
    b.check(0.05, "first")
    led.add(Entry("first", "muse-spark-1.3", "responses", 0.05, 1.0, {"input": 1}))
    assert led.total() == 0.05 and b.remaining == 0.05
    b.check(0.05, "second")                 # exactly at the ceiling is allowed
    with pytest.raises(BudgetExceeded):
        b.check(0.0501, "third")
    assert "TOTAL $0.0500 over 1 live calls" in led.summary()


def test_event_cap_spans_every_run(tmp_path):
    import json
    runs = tmp_path / "runs"
    for name, cost in (("a", 0.30), ("b", 0.25)):
        Ledger(runs / name / "ledger.jsonl").add(Entry("x", "muse-spark-1.3", "responses", cost, 1.0))
    (runs / "event.json").write_text(json.dumps({"cap_usd": 1.00, "spent_elsewhere_usd": 0.40}))
    from watchverify.budget import event_spent
    assert event_spent(runs) == 0.95
    b = Budget(Ledger(runs / "c" / "ledger.jsonl"), ceiling_usd=5.0, runs_root=runs)
    b.check(0.05, "fits")                     # 0.95 + 0.05 = the cap exactly
    with pytest.raises(BudgetExceeded, match="event cap"):
        b.check(0.06, "too much")


def test_the_event_cap_reaches_runs_at_any_depth(tmp_path):
    import json, pytest
    from watchverify.budget import event_root, event_spent
    from watchverify.meta_client import make_client
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "event.json").write_text(json.dumps({"cap_usd": 1.0}))
    deep = tmp_path / "runs" / "holdout" / "bench-x"; deep.mkdir(parents=True)
    assert event_root(deep) == tmp_path / "runs"
    (deep / "ledger.jsonl").write_text(json.dumps({"key": "k", "cost_usd": 0.4}) + "\n")
    shallow = tmp_path / "runs" / "dev"; shallow.mkdir()
    (shallow / "ledger.jsonl").write_text(json.dumps({"key": "k", "cost_usd": 0.5}) + "\n")
    assert event_spent(tmp_path / "runs") == pytest.approx(0.9)       # the held-out run's spend counts
    with pytest.raises(RuntimeError):
        make_client(tmp_path / "elsewhere" / "run", 1.0)              # no event.json above: no live client


def test_calls_running_at_once_cannot_spend_the_same_money(tmp_path):
    import asyncio, pytest
    from watchverify.budget import Budget, BudgetExceeded
    from watchverify.ledger import Ledger
    b = Budget(Ledger(tmp_path / "ledger.jsonl"), 1.0)

    async def call(started, release):
        with b.reserve(0.4, "call"):
            started.set(); await release.wait()

    async def main():
        rel = asyncio.Event(); s1, s2 = asyncio.Event(), asyncio.Event()
        t1 = asyncio.create_task(call(s1, rel)); t2 = asyncio.create_task(call(s2, rel))
        await s1.wait(); await s2.wait()
        with pytest.raises(BudgetExceeded):          # 0.4 + 0.4 in flight + 0.4 would pass 1.0
            with b.reserve(0.4, "third"):
                pass
        rel.set(); await t1; await t2
        assert b.pending == 0
    asyncio.run(main())
