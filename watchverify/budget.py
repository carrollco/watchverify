"""Dollar ceilings. Meta has no hard spend cap (alert only), so the caps live here: a per-run ceiling, and an
event-wide cap over every run's ledger under the same runs/ folder, read from runs/event.json:
{"cap_usd": 140, "spent_elsewhere_usd": 0.282, "note": "..."} (spend logged outside runs/, such as early probes)."""
import contextlib, json
from pathlib import Path
from .ledger import Ledger


class BudgetExceeded(RuntimeError):
    pass


def event_config(runs_root: Path) -> dict:
    p = Path(runs_root) / "event.json"
    return json.loads(p.read_text()) if p.exists() else {}


def event_root(run_dir: Path) -> Path | None:
    """The nearest folder at or above a run's folder that holds event.json: one cap over every run beneath it,
    however deep (runs/holdout/bench-x counts against runs/event.json)."""
    for d in [Path(run_dir), *Path(run_dir).parents]:
        if (d / "event.json").exists():
            return d
    return None


def event_spent(runs_root: Path) -> float:
    """Live spend across every run's ledger at any depth under runs_root, plus spend recorded outside it."""
    total = sum(Ledger(p).total() for p in Path(runs_root).rglob("ledger.jsonl"))
    return round(total + float(event_config(runs_root).get("spent_elsewhere_usd", 0)), 6)


class Budget:
    def __init__(self, ledger: Ledger, ceiling_usd: float, runs_root: Path | None = None):
        self.ledger = ledger
        self.ceiling = float(ceiling_usd)
        self.runs_root = Path(runs_root) if runs_root else None
        cap = event_config(self.runs_root).get("cap_usd") if self.runs_root else None
        self.event_cap = float(cap) if cap is not None else None
        self.pending = 0.0           # worst cases of calls checked but not yet logged (concurrent calls)

    @property
    def spent(self) -> float:
        return self.ledger.total()

    @property
    def remaining(self) -> float:
        return round(self.ceiling - self.spent, 6)

    def check(self, estimate_usd: float, what: str) -> None:
        """Refuse before the call if the worst-case estimate would pass the run ceiling or the event cap."""
        if self.spent + self.pending + estimate_usd > self.ceiling:
            raise BudgetExceeded(
                f"{what}: spent ${self.spent:.4f} + in flight ${self.pending:.4f} + worst case ${estimate_usd:.4f} "
                f"would pass the ceiling ${self.ceiling:.2f}")
        if self.event_cap is not None:
            total = event_spent(self.runs_root) + self.pending
            if total + estimate_usd > self.event_cap:
                raise BudgetExceeded(
                    f"{what}: event spend ${total:.4f} + worst case ${estimate_usd:.4f} would pass the event cap ${self.event_cap:.2f}")

    @contextlib.contextmanager
    def reserve(self, estimate_usd: float, what: str):
        """Check, then hold the worst case until the call is logged, so calls running at once cannot each pass the
        check on the same remaining money."""
        self.check(estimate_usd, what)
        self.pending += estimate_usd
        try:
            yield
        finally:
            self.pending -= estimate_usd
