"""Ground a Procedure in evidence: SAM 3.1 tracks the noun phrases the procedure names, Voice Transcribe
gives timed speech turns, and each step gets an evidence frame with the tracked boxes drawn on it.

SAM is billed per frame, so tracking runs on a low-frame-rate copy (5 fps by default: a 20 s clip is 100
frames, 2 cents per phrase). The boxes come back in that copy's pixels, which are also the evidence
frames' pixels, so nothing is rescaled."""
import asyncio, json
from pathlib import Path
from . import media
from .meta_client import MetaClient

COLORS = ["d62728", "1f77b4", "2ca02c", "ff7f0e", "9467bd", "8c564b"]   # one per tracked phrase
MIN_CONFIDENCE = 0.4


def phrases_to_track(procedure: dict, limit: int = 4) -> list[str]:
    """The extractor's own choice (`track`), else the most-named step objects. Deduplicated, in order."""
    chosen = list(procedure.get("track") or [])
    if not chosen:
        counts: dict[str, int] = {}
        for st in procedure["steps"]:
            for o in st["objects"]:
                counts[o] = counts.get(o, 0) + 1
        chosen = sorted(counts, key=lambda o: -counts[o])
    out: list[str] = []
    for ph in chosen:
        if ph.strip() and ph.lower() not in {x.lower() for x in out}:
            out.append(ph.strip())
    return out[:limit]


def frame_time(frame: int | None, fps: float) -> float | None:
    # SAM numbers video frames from 0 (2026-10-27: a box at frame 0 of a 100-frame track); frame k starts
    # at k / fps. SAM's confidence is one score per tracked object, not per frame.
    return None if frame is None else round(frame / fps, 3)


def step_tracks(steps: list[dict], tracks: dict[str, list[dict]], fps: float) -> list[dict]:
    """For each step, per tracked phrase: how many frames inside the step's window carry a confident box,
    the first and last such second, and the mean confidence. Pure; tested without the network."""
    out = []
    for st in steps:
        a, b = st["start_s"], st["end_s"]
        per = {}
        for phrase, boxes in tracks.items():
            hits = [x for x in boxes if x["t"] is not None and a <= x["t"] <= b
                    and (x.get("confidence") is None or x["confidence"] >= MIN_CONFIDENCE)]
            frames = sorted({x["frame"] for x in hits})
            confs = [x["confidence"] for x in hits if x.get("confidence") is not None]
            per[phrase] = dict(frames=len(frames), window_frames=max(int(round((b - a) * fps)), 1),
                               first_s=min((x["t"] for x in hits), default=None),
                               last_s=max((x["t"] for x in hits), default=None),
                               mean_confidence=round(sum(confs) / len(confs), 3) if confs else None)
        out.append(per)
    return out


def attach_turns(steps: list[dict], turns: list[dict]) -> list[list[dict]]:
    """Speech turns (startMs, endMs, transcript) that overlap each step's window."""
    out = []
    for st in steps:
        a, b = st["start_s"] * 1000, st["end_s"] * 1000
        out.append([dict(start_s=t["startMs"] / 1000, end_s=t["endMs"] / 1000, text=t["transcript"])
                    for t in turns if t["startMs"] < b and t["endMs"] > a])
    return out


def boxes_near(tracks: dict[str, list[dict]], t: float, fps: float, phrases: list[str]) -> list[tuple]:
    """The confident boxes of each phrase in the frame nearest t (within one frame), colored per phrase."""
    out = []
    for phrase, boxes in tracks.items():
        near = [x for x in boxes if x["t"] is not None and abs(x["t"] - t) <= 1 / fps
                and (x.get("confidence") is None or x["confidence"] >= MIN_CONFIDENCE)]
        if near:
            best_t = min(near, key=lambda x: abs(x["t"] - t))["t"]
            color = COLORS[phrases.index(phrase) % len(COLORS)]
            out += [(x["left"], x["top"], x["right"], x["bottom"], color) for x in near if x["t"] == best_t]
    return out


async def ground(client: MetaClient, procedure: dict, video: Path, run_dir: Path, name: str = "reference",
                 fps: int = 5, width: int = 640, max_phrases: int = 4, transcribe: bool = True) -> dict:
    run_dir = Path(run_dir); frames_dir = run_dir / "frames"; frames_dir.mkdir(parents=True, exist_ok=True)
    phrases = phrases_to_track(procedure, max_phrases)
    small = media.resample(Path(video), run_dir / f"{name}.track{fps}fps.mp4", fps=fps, width=width)
    n_frames, secs = media.count_frames_and_secs(small)
    fid = await client.upload(small, f"{name}.track.upload")

    async def track(i: int, phrase: str) -> tuple[str, list[dict]]:
        d = await client.segment_video(f"{name}.sam.{i}", fid, phrase, n_frames)
        return phrase, [dict(b, t=frame_time(b["frame"], fps)) for b in d.get("boxes", [])]
    tracks = dict(await asyncio.gather(*(track(i, ph) for i, ph in enumerate(phrases))))

    turns: list[dict] = []
    if transcribe and media.has_audio(Path(video)):
        wav = media.wav_16k(Path(video), run_dir / f"{name}.16k.wav")
        tr = await client.transcribe(f"{name}.transcribe", wav, secs)
        turns = tr.get("turns", [])

    steps = procedure["steps"]
    per_step = step_tracks(steps, tracks, fps)
    speech = attach_turns(steps, turns)
    out_steps = []
    for st, tr_, sp in zip(steps, per_step, speech):
        t = st.get("evidence_s", (st["start_s"] + st["end_s"]) / 2)
        t = min(max(t, st["start_s"]), st["end_s"])
        frame = media.frame_at(Path(video), t, frames_dir / f"{name}-step{st['index']}.jpg", width=width,
                               boxes=boxes_near(tracks, t, fps, phrases))
        out_steps.append(dict(index=st["index"], evidence_s=t, frame=str(frame.relative_to(run_dir)),
                              tracks=tr_, speech=sp))
    g = dict(video=str(video), seconds=secs, track_fps=fps, track_frames=n_frames, width=width,
             phrases=phrases, colors={ph: COLORS[i % len(COLORS)] for i, ph in enumerate(phrases)},
             tracks={ph: [{k: x[k] for k in ("frame", "t", "object_id", "left", "top", "right", "bottom", "confidence")}
                          for x in bs] for ph, bs in tracks.items()},
             turns=turns, steps=out_steps)
    (run_dir / f"{name}.grounding.json").write_text(json.dumps(g, indent=1))
    return g
