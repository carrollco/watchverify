"""Check a candidate video against a reference Procedure: deviations with evidence, and what could not be checked.
(The first, text-only design compared two extracted procedures; dropped on 2026-10-26, removed 2026-10-28.)"""
import base64, json
from pathlib import Path
from . import media, schema, timing
from .ground import frame_time
from .meta_client import MetaClient, safe_name


def _strip(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


CHECKER_STEP_FIELDS = ("index", "action", "objects", "observable_checkpoint", "pass_condition", "cannot_see",
                       "checkpoint_visibility")


def _spec(reference: dict) -> dict:
    """The reference as the checker sees it, built from an allow-list: the task and each step's order, action,
    objects, checkpoint, pass condition, what the camera cannot see and its visibility. Nothing else reaches the
    model under test, so a field added later is hidden by default. Hidden on purpose: the expert's seconds (with
    them, a swap was read as in order, 2026-10-28), the self-check, the transcript and notes (which can carry
    timing), the source path. tests/test_leaks.py plants canaries in every hidden place."""
    return {"task": reference["task"],
            "steps": [{k: st[k] for k in CHECKER_STEP_FIELDS if k in st} for st in reference["steps"]]}


def _image(path: Path) -> dict:
    return {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()}


def reference_frames(reference: dict, run_dir: Path, name: str, reference_video: Path | None) -> dict[int, Path]:
    """One frame per reference step from the expert's video, at the second its checkpoint is best seen."""
    src = reference_video or reference.get("_source", {}).get("video")
    if not src or not Path(src).is_file():
        return {}
    d = Path(run_dir) / "frames"; d.mkdir(parents=True, exist_ok=True)
    out = {}
    for st in reference["steps"]:
        t = st.get("evidence_s", (st["start_s"] + st["end_s"]) / 2)
        out[st["index"]] = media.frame_at(Path(src), min(max(t, st["start_s"]), st["end_s"]),
                                          d / f"{name}-ref-step{st['index']}.jpg", width=512)
    return out


def search_window(checks: list[dict], step: int, duration: float, pad: float = 0.5, min_len: float = 2.0) -> tuple[float, float]:
    """Where a step should be in the candidate, by order: after the last observed earlier step ends and before
    the next observed later step starts. Pure; tested without the network."""
    obs = {c["reference_step"]: c for c in checks if c["status"] in schema.PRESENT}
    before = [obs[k]["observed_end_s"] for k in obs if k < step]
    after = [obs[k]["observed_start_s"] for k in obs if k > step]
    a = max(before) if before else 0.0
    b = min(after) if after else duration
    if b < a:            # neighbors themselves out of order: search the span between them either way
        a, b = b, a
    a, b = max(a - pad, 0.0), min(b + pad, duration)
    if b - a < min_len:
        mid = (a + b) / 2
        a, b = max(mid - min_len / 2, 0.0), min(mid + min_len / 2, duration)
    return round(a, 2), round(b, 2)


def merge_second_look(check: dict, look: dict, offset: float) -> dict:
    """The second look decides the status of a step the first pass called not observed; times are shifted from
    the window clip back to the candidate video. Pure; tested without the network."""
    first = {k: check[k] for k in ("status", "observed_start_s", "observed_end_s", "evidence")}
    check["second_look"] = dict(look, window_offset_s=offset, first_pass=first)
    if look["status"] != "not_observed":
        check["status"] = check["seen_status"] = look["status"]
        if "seen_as" in look:
            check["seen_as"] = look["seen_as"]
        if look["status"] in schema.PRESENT:
            check["observed_start_s"] = round(look["observed_start_s"] + offset, 2)
            check["observed_end_s"] = round(look["observed_end_s"] + offset, 2)
        check["evidence"] = f"second look: {look['evidence']} (first pass: {first['evidence']})"
    return check


async def second_look(client: MetaClient, step: dict, ref_frame: Path | None, video: Path, window: tuple[float, float],
                      run_dir: Path, key: str, m=media, act: bool = False,
                      effort: str = "medium") -> dict:
    clip = m.cut(Path(video), [window], Path(run_dir) / f"{key}.mp4")
    fid = await client.upload(clip, f"{key}.upload")
    text = ("STEP from the reference procedure:\n" + json.dumps(
        {k: step[k] for k in ("action", "objects", "observable_checkpoint", "pass_condition")}, indent=1) +
        (f"\n\nThe image shows this step in the expert's video." if ref_frame else "") +
        f"\n\nThe attached clip is {window[1] - window[0]:.1f} s long. Is the step's checkpoint visible in it?")
    content = [{"type": "input_text", "text": text}] + ([_image(ref_frame)] if ref_frame else []) + \
              [{"type": "input_file", "file_id": fid}]
    # 8000: 3 of 894 confirm looks spent all of 4000 on reasoning (p99 3423); the cap only bites on those
    look, _ = await client.structured(key, "second_look", schema.SECOND_LOOK_ACT if act else schema.SECOND_LOOK,
                                      schema.SECOND_LOOK_INSTRUCTIONS_ACT if act else schema.SECOND_LOOK_INSTRUCTIONS, content,
                                      effort=effort,
                                      max_output_tokens=8000, est_input_tokens=4000)
    return look


async def measure_timing(client: MetaClient, reference: dict, grounding: dict, video: Path, run_dir: Path,
                         name: str, m=media) -> dict | None:
    """Track the reference's tool in the candidate with SAM 3.1 and measure each step's seconds (timing.py).
    One SAM call, saved as <name>.timing.json and reused; None when the reference has no usable tool track."""
    saved = Path(run_dir) / f"{name}.timing.json"
    phrase = timing.tool_phrase(reference, grounding)
    if phrase is None:
        return None
    model = timing.fit(reference, grounding, phrase)
    if saved.exists():                   # the candidate's side as measured; the reference's side from the current fit
        meas = json.loads(saved.read_text())
        for k, st in meas["steps"].items():
            st.update({f: model["steps"][int(k)][f] for f in timing.REFERENCE_FIELDS})
        return meas
    small = m.resample(Path(video), Path(run_dir) / f"{name}.track{grounding['track_fps']}fps.mp4",
                       fps=grounding["track_fps"], width=grounding["width"])
    n_frames, _ = m.count_frames_and_secs(small)
    fid = await client.upload(small, f"{name}.track.upload")
    d = await client.segment_video(f"{name}.sam", fid, phrase, n_frames)
    boxes = [dict(b, t=frame_time(b["frame"], grounding["track_fps"])) for b in d.get("boxes", [])]
    meas = timing.measure(model, boxes, n_frames)
    saved.write_text(json.dumps(meas, indent=1))
    return meas


async def add_timing(client: MetaClient, reference: dict, grounding: dict, v: dict, video: Path, run_dir: Path,
                     name: str, m=media) -> dict:
    """Attach each step's measured seconds to its check; the rules then use them. No-op without a tool track."""
    meas = await measure_timing(client, reference, grounding, video, run_dir, name, m)
    if meas is None:
        return v
    timing.attach(v, meas)
    return schema.apply_order_rules(reference, v)


CONFIRM_MIN_S = 2.0      # the shortest stretch a confirm look is shown (the same floor as search_window's)


def confirm_window(c: dict, duration: float) -> tuple[float, float]:
    """The stretch a check claimed for a step, at least CONFIRM_MIN_S long, inside the video."""
    a, b = max(c["observed_start_s"], 0.0), min(max(c["observed_end_s"], c["observed_start_s"]), duration)
    if b - a < CONFIRM_MIN_S:
        mid = (a + b) / 2
        a, b = max(mid - CONFIRM_MIN_S / 2, 0.0), min(mid + CONFIRM_MIN_S / 2, duration)
    return round(a, 2), round(b, 2)


async def confirm_looks(client: MetaClient, reference: dict, v: dict, frames: dict, video: Path, run_dir: Path,
                        name: str, duration: float, m=media, act: bool = False,
                        effort: str = "medium") -> dict:
    """A second look at every step the check placed in the video, on the stretch it claimed. A removed step whose
    result shows in later frames is reported seen; that miss is invisible to the second look, which only revisits
    steps reported missing. schema.apply_order_rules sends a step the confirm look did not see to review."""
    steps = {st["index"]: st for st in reference["steps"]}
    for c in v["checks"]:
        if c["status"] not in schema.PRESENT or c["observed_start_s"] < 0:
            continue
        win = confirm_window(c, duration)
        look = await second_look(client, steps[c["reference_step"]], frames.get(c["reference_step"]), Path(video), win,
                                 run_dir, f"{name}.confirm.step{c['reference_step']}", m, act=act, effort=effort)
        c["confirm_look"] = dict(look, window=list(win))
    return v


async def verify_video(client: MetaClient, reference: dict, video: Path, run_dir: Path, name: str = "verify",
                       reference_video: Path | None = None, look_again: bool = True,
                       grounding: dict | None = None, m=media, confirm: bool = False, act: bool = False,
                       effort: str = "medium") -> dict:
    """The reference procedure is the spec; the candidate video is checked against it, step by step.
    The model reports observations (seen or not, when), given the expert's frame for each step; every step it
    reports not observed gets a second look at the stretch of video where it should be. Code applies the
    order rules and the verdict. m is the video toolkit: media (ffmpeg), or replay.ReplayMedia to rebuild a
    saved check from its raw responses without the video."""
    safe_name(name)                      # it names files in run_dir; replayed evidence supplies it
    frames = reference_frames(reference, run_dir, name, reference_video)
    fid = await client.upload(video, f"{name}.upload")
    prompt = ("REFERENCE procedure (steps in the expert's order; the candidate's timing is its own):\n" +
              json.dumps(_spec(reference), indent=1) + "\n\nCheck the attached video against every reference step.")
    content = [{"type": "input_text", "text": prompt}]
    for i, f in frames.items():
        content += [{"type": "input_text", "text": f"Reference step {i}, as it looks in the expert's video:"}, _image(f)]
    content.append({"type": "input_file", "file_id": fid})
    v, usage = await client.structured(f"{name}.checks", "video_verification",
                                       schema.VIDEO_VERIFICATION_ACT if act else schema.VIDEO_VERIFICATION,
                                       schema.VERIFY_VIDEO_INSTRUCTIONS_ACT if act else schema.VERIFY_VIDEO_INSTRUCTIONS, content,
                                       effort=effort,
                                       max_output_tokens=12000, est_input_tokens=9000 + 800 * len(frames))
    v = schema.apply_order_rules(reference, v)
    _, duration = m.count_frames_and_secs(Path(video))
    if look_again:
        steps = {st["index"]: st for st in reference["steps"]}
        for c in v["checks"]:
            if c["status"] != "not_observed":
                continue
            win = search_window(v["checks"], c["reference_step"], duration)
            look = await second_look(client, steps[c["reference_step"]], frames.get(c["reference_step"]), Path(video),
                                     win, run_dir, f"{name}.look.step{c['reference_step']}", m, act=act, effort=effort)
            merge_second_look(c, look, win[0])
        v = schema.apply_order_rules(reference, v)
    if confirm:
        v = await confirm_looks(client, reference, v, frames, video, run_dir, name, duration, m, act=act, effort=effort)
        v = schema.apply_order_rules(reference, v)
    if grounding:
        v = await add_timing(client, reference, grounding, v, video, run_dir, name, m)
    v["_source"] = dict(video=str(video), file_id=fid, usage=usage, duration_s=duration,
                        reference_frames={i: str(Path(f).relative_to(run_dir)) for i, f in frames.items()})
    Path(run_dir, f"{name}.json").write_text(json.dumps(v, indent=1))
    return v


async def self_check(client: MetaClient, reference: dict, reference_video: Path, run_dir: Path, name: str = "reference") -> dict:
    """Check the expert's own video against the procedure extracted from it, and mark each step with the result
    (schema.annotate_self_check). Costs one verification; run once per reference, before checking candidates."""
    v = await verify_video(client, reference, Path(reference_video), run_dir, f"{name}.selfcheck", Path(reference_video))
    return schema.annotate_self_check(reference, v)


def rescore(run_dir: Path, name: str = "reference") -> list[tuple[str, str]]:
    """Re-apply the code rules to every saved verification in the run, using the current reference. Free."""
    ref = json.loads((Path(run_dir) / f"{name}.procedure.json").read_text())
    out = []
    for p in sorted(Path(run_dir).glob("*.json")):
        d = json.loads(p.read_text())
        if isinstance(d, dict) and "checks" in d and "verdict" in d:
            d = schema.apply_order_rules(ref, d)
            p.write_text(json.dumps(d, indent=1)); out.append((p.stem, d["verdict"]))
    return out
