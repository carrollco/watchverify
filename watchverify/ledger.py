"""Append-only cost ledger: one JSON line per Meta call, so every run states what it cost."""
import json, time
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class Entry:
    key: str                       # what this call was for, e.g. "extract.procedure"
    model: str
    endpoint: str                  # responses, files, sam, transcribe, images
    cost_usd: float
    latency_s: float
    units: dict = field(default_factory=dict)   # tokens, frames, seconds, images
    note: str = ""
    ts: float = field(default_factory=time.time)
    live: bool = True              # False for a replayed response: logged, never counted (it cost nothing)


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, e: Entry) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(asdict(e)) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def total(self) -> float:
        return round(sum(e["cost_usd"] for e in self.entries() if e.get("live", True)), 6)

    def summary(self) -> str:
        es = self.entries()
        lines = [f"{e['key']:28} {e['model']:26} {e['endpoint']:10} {e['latency_s']:6.1f}s  ${e['cost_usd']:.4f}"
                 f"{'' if e.get('live', True) else ' (replay, not counted)'}  {json.dumps(e['units'])}" for e in es]
        live = [e for e in es if e.get("live", True)]
        lines.append(f"TOTAL ${self.total():.4f} over {len(live)} live calls" + (f", {len(es) - len(live)} replayed" if len(live) < len(es) else ""))
        return "\n".join(lines)
