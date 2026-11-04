"""One path for every Meta Model API call: a transport (live or replay), a ledger entry per call, a
budget check before each call, max_output_tokens caps, raw responses saved per run. Tests use the
ReplayTransport and never touch the network or spend."""
import json, os, re, time
from pathlib import Path
from typing import Any, Protocol

from . import pricing
from .budget import Budget, event_root
from .ledger import Entry, Ledger

BASE_URL = "https://api.meta.ai/v1"
SPARK = "muse-spark-1.3"
SAM = "sam-3.1"
VOICE = "muse-voice-transcribe-1.0"


def neutral_name(data: bytes, suffix: str) -> str:
    """Uploads go out under a content hash, never a path: a file named after a planted mistake ("omit3.mp4") would
    carry the answer key to the model under test."""
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16] + suffix


def redact_request(kw: dict) -> dict:
    """The request as the model saw it, for the run's record, with inline images replaced by their hash."""
    import copy, hashlib
    k = copy.deepcopy(kw)
    for m in k.get("input", []):
        for c in m.get("content", []):
            if c.get("type") == "input_image" and str(c.get("image_url", "")).startswith("data:"):
                c["image_url"] = "sha256:" + hashlib.sha256(c["image_url"].encode()).hexdigest()[:16]
    return k


class Transport(Protocol):
    async def upload(self, path: Path, key: str, name: str) -> str: ...
    async def responses_create(self, key: str, **kw) -> dict: ...
    async def segment(self, key: str, **kw) -> dict: ...
    async def transcribe(self, key: str, wav: bytes, settings: dict) -> dict: ...


class LiveTransport:
    """Real calls. Saves every raw response under raw_dir/<key>.json so fixtures can be made from them."""

    def __init__(self, raw_dir: Path, api_key: str | None = None):
        from openai import AsyncOpenAI
        self.key = api_key or os.environ["MODEL_API_KEY"]
        self.client = AsyncOpenAI(base_url=BASE_URL, api_key=self.key, max_retries=1)
        self.raw_dir = Path(raw_dir); self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _save(self, key: str, data: Any) -> None:
        (self.raw_dir / f"{safe_name(key)}.json").write_text(json.dumps(data, indent=1, default=str))

    async def upload(self, path: Path, key: str, name: str) -> str:
        f = await self.client.files.create(file=(name, Path(path).read_bytes()), purpose="user_data")
        self._save(key, f.model_dump()); return f.id

    async def responses_create(self, key: str, **kw) -> dict:
        self._save(f"{key}.request", redact_request(kw))
        r = await self.client.responses.create(**kw)
        d = r.model_dump(); self._save(key, d); return d

    async def segment(self, key: str, **kw) -> dict:
        import meta_sam_parser as sam
        raw: list[str] = []
        stream = await self.client.responses.create(stream=True, **kw)

        async def tee():
            async for ev in stream:
                if getattr(ev, "type", "") == "response.output_text.delta":
                    raw.append(ev.delta)
                yield ev
        video = any(c.get("type") == "input_video" for m in kw["input"] for c in m.get("content", []))
        fmt = sam.video_segmentation_format() if video else sam.image_segmentation_format()
        parsed = sam.parse_responses_stream(tee(), fmt)
        fr = parsed.final_result
        result = await (fr() if callable(fr) else fr)
        records = []
        for rec in result.records:
            if getattr(rec, "kind", "") != "box":
                continue
            frame = getattr(rec, "frame", None)
            fidx = getattr(frame, "index", None)
            if fidx is None and frame is not None:
                m = re.search(r"\d+", str(frame)); fidx = int(m.group()) if m else None
            records.append(dict(object_id=rec.object_id, frame=fidx, left=rec.left, top=rec.top,
                                right=rec.right, bottom=rec.bottom, confidence=getattr(rec, "confidence", None)))
        d = dict(raw_text="".join(raw), boxes=records, outcome=str(result.outcome))
        self._save(key, d); return d

    async def transcribe(self, key: str, wav: bytes, settings: dict) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=180) as hc:
            resp = await hc.post(f"{BASE_URL}/asr/transcribe",
                                 headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"},
                                 files={"request": (None, json.dumps(settings), "application/json"),
                                        "audio": ("clip.wav", wav, "audio/wav")})
        d = resp.json(); d["_http"] = resp.status_code; self._save(key, d); return d


SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def safe_name(name: str) -> str:
    """A call key or check name becomes a file name; one that could leave its folder (a separator, a leading dot)
    is refused. Evidence folders come from other people, so replay must not write or read where they say."""
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        raise ValueError(f"unsafe name {name!r}: letters, digits, dot, dash and underscore only, starting with a letter or digit")
    return name


class ReplayTransport:
    """Reads saved responses from fixtures_dir/<key>.json. No network, ever."""

    def __init__(self, fixtures_dir: Path):
        self.dir = Path(fixtures_dir)

    def _load(self, key: str) -> dict:
        p = self.dir / f"{safe_name(key)}.json"
        if not p.exists():
            raise FileNotFoundError(f"no replay fixture for {key} in {self.dir}")
        return json.loads(p.read_text())

    async def upload(self, path: Path, key: str, name: str) -> str:
        return self._load(key)["id"]

    async def responses_create(self, key: str, **kw) -> dict:
        return self._load(key)

    async def segment(self, key: str, **kw) -> dict:
        return self._load(key)

    async def transcribe(self, key: str, wav: bytes, settings: dict) -> dict:
        return self._load(key)


def output_text(resp: dict) -> str:
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c.get("text", "")
    return resp.get("output_text", "") or ""


class MetaClient:
    def __init__(self, transport: Transport, ledger: Ledger, budget: Budget):
        self.t = transport; self.ledger = ledger; self.budget = budget
        self.live = not isinstance(transport, ReplayTransport)

    def _log(self, e: Entry) -> None:
        e.live = self.live
        self.ledger.add(e)

    async def upload(self, path: Path, key: str) -> str:
        t0 = time.time()
        if not self.live:          # replay: the saved upload record answers; the video need not exist
            fid = await self.t.upload(path, key, "replay")
            self._log(Entry(key, "files", "files", 0.0, 0.0, {"bytes": None}))
            return fid
        fid = await self.t.upload(path, key, neutral_name(Path(path).read_bytes(), Path(path).suffix))
        self._log(Entry(key, "files", "files", 0.0, time.time() - t0, {"bytes": Path(path).stat().st_size}))
        return fid

    async def structured(self, key: str, schema_name: str, schema: dict, instructions: str, content: list[dict],
                         model: str = SPARK, effort: str = "medium", max_output_tokens: int = 4000,
                         est_input_tokens: int = 8000) -> tuple[dict, dict]:
        """One Responses call with strict structured output. Returns (parsed JSON, usage)."""
        with self.budget.reserve(pricing.max_token_cost(model, est_input_tokens, max_output_tokens), key):
            t0 = time.time()
            resp = await self.t.responses_create(
                key, model=model, reasoning={"effort": effort}, max_output_tokens=max_output_tokens,
                instructions=instructions,
                input=[{"type": "message", "role": "user", "content": content}],
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}})
            lat = time.time() - t0
            usage = resp.get("usage") or {}
            cost = pricing.token_cost(model, usage)
            self._log(Entry(key, model, "responses", round(cost, 6), round(lat, 2),
                            {"input": usage.get("input_tokens"), "output": usage.get("output_tokens"),
                             "reasoning": (usage.get("output_tokens_details") or {}).get("reasoning_tokens")},
                            note=str(resp.get("status"))))
        if resp.get("status") not in (None, "completed"):
            raise RuntimeError(f"{key}: response status {resp.get('status')} (raise max_output_tokens?)")
        return json.loads(output_text(resp)), usage

    async def segment_video(self, key: str, file_id: str, phrase: str, frames: int) -> dict:
        with self.budget.reserve(pricing.sam_video_cost(frames), key):
            t0 = time.time()
            d = await self.t.segment(key, model=SAM, metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
                                     input=[{"type": "message", "role": "user", "content": [
                                         {"type": "input_text", "text": phrase},
                                         {"type": "input_video", "file_id": file_id}]}])
            self._log(Entry(key, SAM, "sam", round(pricing.sam_video_cost(frames), 6), round(time.time() - t0, 2),
                            {"frames": frames, "boxes": len(d.get("boxes", [])), "phrase": phrase}))
        return d

    async def transcribe(self, key: str, wav_path: Path, seconds: float, mode: str = "ENDPOINTING") -> dict:
        with self.budget.reserve(pricing.transcribe_cost(seconds), key):
            t0 = time.time()
            d = await self.t.transcribe(key, Path(wav_path).read_bytes(),
                                        {"model": VOICE, "audioEncoding": "WAV", "mode": mode})
            self._log(Entry(key, VOICE, "transcribe", round(pricing.transcribe_cost(seconds), 6),
                            round(time.time() - t0, 2), {"seconds": seconds, "turns": len(d.get("turns", []))}))
        return d


def make_client(run_dir: Path, ceiling_usd: float, replay_dir: Path | None = None) -> MetaClient:
    run_dir = Path(run_dir); run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    root = event_root(run_dir)
    if root is None and not replay_dir:
        raise RuntimeError(f"no event.json at or above {run_dir}: a live client never runs without the event-wide cap")
    transport = ReplayTransport(replay_dir) if replay_dir else LiveTransport(run_dir / "raw")
    return MetaClient(transport, ledger, Budget(ledger, ceiling_usd, runs_root=root or run_dir.parent))
