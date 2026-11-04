"""Accuracy test. For each source video: a scout extraction picks a stretch of consecutive, clearly visible steps;
that clip becomes the reference (extract, ground, self-check); planted mistakes are cut from it in code (each step
removed, each adjacent pair swapped), so the truth is known; every variant, and the expert's clip cut the same way
(the correct case), is checked and scored against that truth. Every plan gets a result row, graded or not, with
who decided (result_row), and each input other than the check itself can be switched off (SWITCHES).

Limits, stated: the cuts follow step boundaries the model drew (midpoint: the reference's seconds; refined: its
calls on stills), so on the development set the truth is the model's own; a swap leaves visible jumps (a cover back
on after it came off), which a real second performance would not; the correct case is the expert's own footage,
easier than another person's correct performance."""
import asyncio, hashlib, json, subprocess
from pathlib import Path
from . import media, schema
from .extract import extract
from .ground import ground
from .verify import _image, measure_timing, self_check, verify_video
from .meta_client import make_client
from . import timing


HOLDOUT_WINDOW_S = 60.0


def seeded_window(sha: str, duration: float, length: float = HOLDOUT_WINDOW_S) -> tuple[float, float]:
    """A held-out clip's stretch: a fixed length at an offset drawn from the source video's content hash, so neither
    the model under test (choose_window prefers the steps it rated clear) nor anyone tuning the checker picks the
    part of the video that becomes the exam."""
    import random
    length = min(length, duration)
    a = random.Random(sha).uniform(0.0, duration - length)
    return round(a, 2), round(a + length, 2)


def choose_window(proc: dict, duration: float, min_steps: int = 4, max_steps: int = 7,
                  min_s: float = 20.0, max_s: float = 75.0) -> tuple[float, float, list[int]] | None:
    """The run of consecutive steps with the most clearly visible ones (then the most steps) that fits the span."""
    steps = proc["steps"]; best = None
    for i in range(len(steps)):
        for j in range(i + min_steps - 1, min(i + max_steps, len(steps))):
            a, b = max(steps[i]["start_s"] - 1.0, 0.0), min(steps[j]["end_s"] + 1.0, duration)
            if not (min_s <= b - a <= max_s):
                continue
            run = steps[i:j + 1]
            score = (sum(s.get("checkpoint_visibility") == "clear" for s in run), len(run))
            if best is None or score > best[0]:
                best = (score, a, b, [s["index"] for s in run])
    return None if best is None else (round(best[1], 2), round(best[2], 2), best[3])


def segments(proc: dict, duration: float) -> list[tuple[float, float]]:
    """Split the clip into one segment per step, cutting at the midpoint between neighboring steps; the lead-in
    belongs to the first step and the tail to the last."""
    st = proc["steps"]
    cuts = [0.0] + [round((st[k - 1]["end_s"] + st[k]["start_s"]) / 2, 2) for k in range(1, len(st))] + [duration]
    return [(cuts[k], cuts[k + 1]) for k in range(len(st))]


BOUNDARY_FPS, BOUNDARY_PAD, BOUNDARY_FRAMES = 4.0, 2.0, 40
MIN_SEGMENT = 0.5


async def refine_boundaries(client, ref: dict, clip: Path, run_dir: Path) -> list[dict]:
    """Where each step's hand work really ends and the next begins, from dense stills of the expert's clip.
    The reference's seconds come from video the model samples coarsely, so a cut at their midpoint can leave a
    step's tail behind (a remnant), and a "removed" step is still partly in the clip. For each pair of
    neighboring steps, frames at up to 4 per second around the reference's boundary, each labeled with its time,
    go to the model, which names the last frame of the first step and the first of the next. The boundary is
    clean when the first ends before the next begins; the stretch between them is the move from one step's place
    to the next (refined_layout). When the model cannot separate them, one wider look at both steps whole
    (the narrow window's frame rate drops on long gaps). Saved per boundary and reused."""
    out = Path(run_dir) / "reference.boundaries.json"
    prior = {x["after_step"]: x for x in json.loads(out.read_text())} if out.exists() else {}
    _, dur = media.count_frames_and_secs(Path(clip))
    st = ref["steps"]
    brief = lambda x: {k: x[k] for k in ("action", "objects", "observable_checkpoint") if k in x}

    async def ask(i: int, a: float, b: float, key: str) -> dict:
        A, B = st[i], st[i + 1]
        fps = min(BOUNDARY_FPS, BOUNDARY_FRAMES / (b - a))
        frames = media.frames_between(Path(clip), a, b, fps, Path(run_dir) / "boundary-frames" / key)
        content = [{"type": "input_text", "text": f"STEP A:\n{json.dumps(brief(A))}\n\nSTEP B:\n{json.dumps(brief(B))}"
                                                 "\n\nFrames, in time order:"}]
        for t, f in frames:
            content += [{"type": "input_text", "text": f"t={t:.2f} s"}, _image(f)]
        r, _ = await client.structured(key, "boundary", schema.BOUNDARY, schema.BOUNDARY_INSTRUCTIONS,
                                       content, max_output_tokens=10000, est_input_tokens=1500 + 900 * len(frames))
        e, s_ = r["first_ends_s"], r["second_begins_s"]
        return dict(after_step=i, window=[round(a, 2), round(b, 2)], fps=fps, frames=len(frames), **r, clean=0 <= e < s_)

    async def one(i: int) -> dict:
        part = Path(run_dir) / "boundary-frames" / f"b{i}.json"
        res = json.loads(part.read_text()) if part.exists() else prior.get(i)
        A, B = st[i], st[i + 1]
        if res is None:
            res = await ask(i, max(0.0, min(A["end_s"], B["start_s"]) - BOUNDARY_PAD),
                            min(dur, max(A["end_s"], B["start_s"]) + BOUNDARY_PAD), f"boundary{i}")
        if not res["clean"] and "narrow" not in res:
            wide = await ask(i, max(0.0, A["start_s"] - 0.5), min(dur, B["end_s"] + 0.5), f"boundary{i}.wide")
            res = dict(wide, narrow={k: res[k] for k in ("window", "fps", "first_ends_s", "second_begins_s", "evidence")})
        res.pop("cut", None)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_text(json.dumps(res, indent=1))
        return res
    res = list(await asyncio.gather(*(one(i) for i in range(len(st) - 1))))
    out.write_text(json.dumps(res, indent=1))
    return res


def load_labels(run_dir: Path) -> dict:
    """The person-confirmed truth of one source (labels.json): who confirmed it ("human:<name>"; a model may
    pre-label, recorded as prelabeled_by) and, per reference step, its working time (start_s, end_s), whether a
    camera shows it (visible) and whether it is a real step of the task at all (is_step; a step the model made up
    is never planted). missed_steps lists steps the person saw that the model did not. A held-out source's labels
    are committed before any check of it runs (committed_labels_problem)."""
    d = json.loads((Path(run_dir) / "labels.json").read_text())
    if not str(d.get("made_by", "")).startswith("human"):
        raise ValueError(f"{run_dir}/labels.json: made_by {d.get('made_by')!r}; labels must be confirmed by a person (human:<name>)")
    steps = sorted(d["steps"], key=lambda x: x["index"])
    for i, st in enumerate(steps):
        if st["index"] != i or not st["start_s"] < st["end_s"] or not isinstance(st.get("visible"), bool) \
                or not isinstance(st.get("is_step", True), bool):
            raise ValueError(f"{run_dir}/labels.json step {st.get('index')}: needs index {i}, start_s < end_s, visible "
                             "and is_step true or false")
    return dict(d, steps=steps)


def labels_boundaries(labels: dict) -> list[dict]:
    """The labels as boundaries (refined_layout's input): clean where a step ends before the next begins."""
    st = labels["steps"]
    return [dict(after_step=i, first_ends_s=st[i]["end_s"], second_begins_s=st[i + 1]["start_s"], fps=None,
                 clean=st[i]["end_s"] < st[i + 1]["start_s"]) for i in range(len(st) - 1)]


COVER_SHARE = 0.5       # a step's cut working time must cover at least this share of the reference's own window


def uncovered_steps(ref: dict, cores: list[tuple[float, float]]) -> dict[int, dict[str, str]]:
    """Steps where a planted mistake would leave the step's own content in the wrong place, judged against the
    reference's account of the step (its window and evidence frame), by kind of mistake:
    omit: the removed stretch (from the end of the previous step's working time to the start of the next's, since a
    removal drops the in-between stretches on both sides) must hold the evidence frame and cover at least COVER_SHARE
    of the window, or the step stays in the clip;
    swaps are not gated here: a swap moves each step's working time and drops the stretches around the pair, so no
    part of a step stays in its old place. (Open, not applied: whether a swap whose evidence frame lies outside the
    moved block is fair; such a rule excluded 10 of 32 swaps, mostly flagged or missed, so it would favor the checker
    and needs an independent check first.)
    Two model outputs disagree in these cases, the procedure and the boundary calls; code compares them (audit of
    2026-11-03: brickpress omit10 removed 47.1 to 60.6 s of a step the reference puts at 60 to 64 s)."""
    out: dict[int, dict[str, str]] = {}
    st = sorted(ref["steps"], key=lambda x: x["index"])
    n = len(st)
    for j, step in enumerate(st):
        s0, e0, ev = step["start_s"], step["end_s"], step.get("evidence_s")
        a = cores[j - 1][1] if j > 0 else cores[j][0]
        b = cores[j + 1][0] if j + 1 < n else cores[j][1]
        share = max(0.0, min(b, e0) - max(a, s0)) / max(e0 - s0, 1e-6)
        bad = {}
        if (ev is not None and not a <= ev <= b) or share < COVER_SHARE:
            bad["omit"] = "cut_misses_step"
        if bad:
            out[step["index"]] = bad
    return out


def ungradable_steps(run_dir: Path, cuts: str) -> dict[int, str] | None:
    """Steps a person said are not a real step of the task, or that a camera cannot show (labels cuts), or whose
    refined cut misses the reference's own window for the step (refined cuts), with the outcome a mistake planted
    on them gets; None for midpoint cuts, where the self-check marks decide instead."""
    if cuts == "refined":
        bp = Path(run_dir) / CUT_INPUT[cuts]
        clip = Path(run_dir) / "clip.mp4"
        if not bp.exists() or not clip.exists():
            return None
        ref = json.loads((Path(run_dir) / "reference.procedure.json").read_text())
        _, dur = media.count_frames_and_secs(clip)
        cores, _, _ = refined_layout(ref, dur, json.loads(bp.read_text()))
        return uncovered_steps(ref, cores) or None
    if cuts != "labels":
        return None
    return {st["index"]: "not_a_step" if not st.get("is_step", True) else "not_visible"
            for st in load_labels(run_dir)["steps"] if not st.get("is_step", True) or not st["visible"]}


def committed_labels_problem(run_dir: Path) -> str | None:
    """A held-out source's labels.json must equal bench/holdout-labels/<sid>.json as committed at HEAD of the
    repository above it: committing is what makes "labels before any check" checkable by anyone."""
    run_dir = Path(run_dir).resolve()
    root = next((d for d in run_dir.parents if (d / ".git").exists()), None)
    rel = f"bench/holdout-labels/{run_dir.name[len('bench-'):]}.json"
    if root is None:
        return f"no git repository above {run_dir.name}, so its labels cannot be shown committed"
    r = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{rel}"], capture_output=True, text=True)
    if r.returncode != 0:
        return f"{rel} is not committed; labels are committed before any check of a held-out source"
    if json.loads(r.stdout) != json.loads((run_dir / "labels.json").read_text()):
        return f"labels.json differs from the committed {rel}"
    return None


def independence_problems(run_dir: Path, cuts: str) -> list[str]:
    """What makes a grading depend on the model under test: truth (the cut points) or selection (which mistakes are
    graded) made by it. Only person-confirmed labels pass."""
    if DECIDED_BY.get(cuts) != "human":
        return [f"cuts {cuts!r}: the step boundaries are drawn by the {DECIDED_BY.get(cuts, MODEL_UNDER_TEST)}, not a person"]
    try:
        load_labels(run_dir)
    except (OSError, ValueError, KeyError) as ex:
        return [f"labels: {ex}"]
    problem = committed_labels_problem(run_dir) if is_holdout(run_dir) else None
    return [problem] if problem else []


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def registry_path(start: Path) -> Path | None:
    """bench/holdout.json of the repository at or above start."""
    return next((d / "bench" / "holdout.json" for d in [Path(start).resolve(), *Path(start).resolve().parents]
                 if (d / "bench" / "holdout.json").exists()), None)


def holdout_hashes(start: Path) -> set[str]:
    """The SHA-256 of every held-out source video, as registered at download (bench/holdout.json "downloads")."""
    rp = registry_path(start)
    return {x["sha256"] for x in json.loads(rp.read_text()).get("downloads", [])} if rp else set()


def register_download(registry: Path, title: str, sid: str, video: Path, **credit: str) -> dict:
    """Record a downloaded held-out video by its content hash, before anything is made from it. The title must be
    one the seeded draw picked; the hash is what every later step checks, so renaming or moving files changes
    nothing."""
    d = json.loads(Path(registry).read_text())
    if title not in d["picked"]:
        raise ValueError(f"{title!r} is not among the held-out picks in {registry}")
    entry = {"title": title, "sid": sid, "sha256": sha256_file(Path(video)), "bytes": Path(video).stat().st_size,
             **{k: v for k, v in credit.items() if v}}      # author, license, url: the page's credit line
    d["downloads"] = [x for x in d.get("downloads", []) if x["sid"] != sid] + [entry]
    Path(registry).write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    return entry


def is_holdout(run_dir: Path) -> bool:
    """A held-out source: its source video's content hash (source.json, written by prepare_source) is registered
    in bench/holdout.json. Identity by content, not by folder or file name."""
    sp = Path(run_dir) / "source.json"
    return sp.exists() and json.loads(sp.read_text())["sha256"] in holdout_hashes(run_dir)


def require_independent(run_dir: Path, cuts: str) -> None:
    """A held-out source is cut, checked, scored and exported only from person-confirmed truth and selection;
    anything else is refused before it costs or counts (2026-10-28 audits)."""
    if is_holdout(run_dir) and (problems := independence_problems(run_dir, cuts)):
        raise PermissionError(f"held-out grading refused for {Path(run_dir).name}: " + "; ".join(problems))


def refuse_on_holdout(run_dir: Path, what: str) -> None:
    """Bench steps that exist only to cut with the model's boundaries never run on a held-out source."""
    if is_holdout(run_dir):
        raise PermissionError(f"{what} refused for {Path(run_dir).name}: a held-out source is cut only from person-confirmed labels")


def refined_layout(proc: dict, duration: float, boundaries: list[dict]
                   ) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[bool]]:
    """Each step's working time (cores) and the in-between stretch after it (gaps), from the refined boundaries.
    A gap runs from half a frame after the last frame of a step to half a frame before the first of the next:
    a tool still resting at a step's place after its work counts as in-between, since someone who skipped the
    step would never have it there. An unclean boundary gets a zero-length gap at the reference's midpoint, and
    a boundary that would leave a step under MIN_SEGMENT of working time is not clean."""
    mids = segments(proc, duration)
    bs = sorted(boundaries, key=lambda b: b["after_step"])
    clean = [bool(b["clean"]) for b in bs]
    n = len(proc["steps"])
    while True:
        gaps = []
        for i, b in enumerate(bs):
            if clean[i]:
                h = 0.5 / b["fps"] if b.get("fps") else 0.0     # labels from a person have no frame rate
                x, y = round(b["first_ends_s"] + h, 3), round(b["second_begins_s"] - h, 3)
                gaps.append((x, max(x, y)))
            else:
                gaps.append((mids[i][1], mids[i][1]))
        edges = [0.0] + [t for g in gaps for t in g] + [duration]
        cores = [(edges[2 * j], edges[2 * j + 1]) for j in range(n)]
        bad = [j for j, (x, y) in enumerate(cores) if y - x < MIN_SEGMENT]
        if not bad:
            return cores, gaps, clean
        changed = False
        for j in bad:
            for i in (j - 1, j):
                if 0 <= i < len(clean) and clean[i]:
                    clean[i] = False
                    changed = True
        if not changed:
            raise ValueError("reference steps overlap: no valid cuts")


def layout_pieces(order: list[int], cores: list[tuple[float, float]],
                  gaps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The clip's pieces for a planted order: each step's working time, and an in-between stretch only where the
    two steps are still neighbors. A removed step loses the stretches on both sides; a swapped pair loses the
    stretches around it. Contiguous pieces are merged and empty ones dropped."""
    out: list[tuple[float, float]] = []
    for idx, j in enumerate(order):
        keep_gap = idx + 1 < len(order) and order[idx + 1] == j + 1
        for x, y in [cores[j]] + ([gaps[j]] if keep_gap else []):
            if y - x <= 1e-6:
                continue
            if out and abs(out[-1][1] - x) < 1e-6:
                out[-1] = (out[-1][0], y)
            else:
                out.append((x, y))
    return out


def plan_is_clean(plan: dict, clean: list[bool]) -> bool:
    """A planted mistake is fair only if every cut it uses is clean: the boundaries before and after each
    planted step."""
    need = {j for k in plan["truth"]["steps"] for j in (k - 1, k)}
    return all(clean[j] for j in need if 0 <= j < len(clean))


def cut_plan(run_dir: Path, ref: dict, duration: float, cuts: str):
    """For a cut method, a function from a planted order to the clip's pieces, and which boundaries are clean
    (None for "midpoint", the reference's own boundaries, where every cut counts)."""
    if cuts == "midpoint":
        segs = segments(ref, duration)
        return (lambda order: [segs[k] for k in order]), None
    if cuts == "labels":
        lab = load_labels(run_dir)
        if len(lab["steps"]) != len(ref["steps"]):
            raise ValueError(f"{run_dir}/labels.json labels {len(lab['steps'])} steps; the reference has {len(ref['steps'])}")
        cores, gaps, clean = refined_layout(lab, duration, labels_boundaries(lab))
        return (lambda order: layout_pieces(order, cores, gaps)), clean
    bp = Path(run_dir) / CUT_INPUT[cuts]
    if not bp.exists():
        raise FileNotFoundError(f"{bp}: run bench-boundaries first")
    cores, gaps, clean = refined_layout(ref, duration, json.loads(bp.read_text()))
    return (lambda order: layout_pieces(order, cores, gaps)), clean


def trial_paths(run_dir: Path, cuts: str, rep: int = 0, checker: str = "") -> tuple[str, Path, Path]:
    """Name prefix for checks, the variants folder and the results file of a cut method, checker version and
    repeat; "midpoint", first checker, first run keeps the names of the first trial. A repeat checks the same clips
    again; a checker label (such as v2) checks them with a changed checker, keeping the earlier checks."""
    vdir = run_dir / ("variants" if cuts == "midpoint" else f"variants-{cuts}")
    if cuts == "midpoint" and rep == 0 and not checker:
        return "", vdir, run_dir / "bench-results.json"
    tag = cuts + (f"-{checker}" if checker else "") + (f"-r{rep}" if rep else "")
    return f"{tag}-", vdir, run_dir / f"bench-results-{tag}.json"


def variant_plans(n: int) -> list[dict]:
    """Every planted mistake for an n-step procedure, with its truth."""
    plans = [dict(name=f"omit{k}", order=[j for j in range(n) if j != k], truth=dict(kind="omit", steps=[k]))
             for k in range(n)]
    for k in range(n - 1):
        order = list(range(n)); order[k], order[k + 1] = order[k + 1], order[k]
        plans.append(dict(name=f"swap{k}{k + 1}", order=order, truth=dict(kind="swap", steps=[k, k + 1])))
    return plans


def correct_plan(n: int) -> dict:
    """The correct performance: the expert's clip in order, cut and re-encoded like the planted mistakes, checked
    against the reference that carries the self-check's marks. The self-check itself is calibration: re-scored
    with the marks it made, it cannot fail, so it is never counted as a graded result."""
    return dict(name="correct", order=list(range(n)), truth=dict(kind="correct", steps=[]))


SELFCHECK_PLAN = dict(name="selfcheck", order=None, truth=dict(kind="selfcheck", steps=[]))


def all_plans(n: int) -> list[dict]:
    return variant_plans(n) + [correct_plan(n)]


def score(truth: dict, v: dict, reference: dict | None = None, use_marks: bool = True) -> dict:
    """Judged on the planted steps only. caught: the planted step reported missing (omit) or both planted steps out
    of order (swap); flagged: a planted step sent to review (unclear, cut short, disputed, or one of a swapped pair
    out of order); missed: the planted steps look fine; untestable: a planted step the checker did not find in the
    expert's own clip (the self-check's marks; never with use_marks False). extras: other steps wrongly reported
    missing or out of order; extras_review: other steps sent to review. For the correct case: correct_pass,
    flagged (review) or false_alarm (fail)."""
    if truth["kind"] in ("correct", "selfcheck"):
        return dict(outcome={"pass": "correct_pass", "review": "flagged", "fail": "false_alarm"}[v["verdict"]])
    planted = set(truth["steps"])
    steps = {st["index"]: st for st in (reference or {}).get("steps", [])}
    if use_marks and any(steps.get(k, {}).get("self_check", "observed") != "observed" for k in planted):
        return dict(outcome="untestable")
    by = {c["reference_step"]: c for c in v["checks"]}
    extras = sorted((set(v["missing_steps"]) | set(v["out_of_order_steps"])) - planted)
    review = lambda c: c["status"] in ("unclear", "done_differently") or c.get("shortened") or c.get("disputed")
    extras_review = sorted(c["reference_step"] for c in v["checks"]
                           if c["reference_step"] not in planted and c["reference_step"] not in extras and review(c))
    if truth["kind"] == "omit":
        c = by[truth["steps"][0]]
        # done differently on a removed step: the checker explained the absence away (the result shows in later frames)
        outcome = ("caught" if c["status"] == "not_observed" else "explained_away" if c["status"] == "done_differently"
                   else "flagged" if review(c) else "missed")
    else:
        cs = [by[k] for k in truth["steps"]]
        outcome = ("caught" if all(c.get("out_of_order") for c in cs) else
                   "flagged" if any(c.get("out_of_order") or review(c) or c["status"] == "not_observed" for c in cs) else "missed")
    return dict(outcome=outcome, extras=extras, extras_review=extras_review)


MODEL_UNDER_TEST = "model under test"     # Muse Spark: it wrote the reference, the step boundaries and the checks
NOT_GRADED = {                             # outcome: why the row is not graded; the row stays in every table
    "no_clean_cut": "the step boundaries do not separate the planted steps, so no cut removes one cleanly",
    "cut_misses_step": "the cut misses the reference's own window for a planted step (its evidence frame is outside, or "
                       "under half the window is covered), so the step would stay in the clip",
    "not_visible": "the labels say a camera cannot show a planted step",
    "not_a_step": "the labels say a planted step is not a real step of the task (the model made it up)",
    "never_extracted": "a step the person saw that the model never listed: no check could catch its removal",
    "untestable": "the checker did not find the planted step in the expert's own clip (self-check)",
    "no_footage": "removing the planted step leaves no footage to check (it is the clip's only step)",
    "not_checked": "no saved check for this clip",
    "error": "the check failed with an error",
    "calibration": "the self-check, re-scored with the marks it made, cannot fail; calibration only",
}
DECIDED_BY = {"midpoint": MODEL_UNDER_TEST, "refined": MODEL_UNDER_TEST, "labels": "human"}   # who drew a cut method's boundaries
CUT_INPUT = {"refined": "reference.boundaries.json", "labels": "labels.json"}                   # the file each one reads


def result_row(sid: str, plan: dict, v: dict | None = None, reference: dict | None = None, outcome: str | None = None,
               by: str = "code", use_marks: bool = True, **kw) -> dict:
    """One row per planted mistake, graded or not, so every table can show its full denominator. A graded row
    carries the checker's report and its score; a row that is not graded keeps its reason and who decided it:
    code, a person, or the model under test (whose say over its own exam is what the audit of 2026-10-28 found)."""
    row = dict(sid=sid, name=plan["name"], truth=plan["truth"], verdict="none")
    if v is None:
        return dict(row, outcome=outcome, graded=False, excluded_by=by, why=NOT_GRADED[outcome], **kw)
    row.update(verdict=v["verdict"], missing=v["missing_steps"], out_of_order=v["out_of_order_steps"],
               unclear=v["unclear_steps"], **score(plan["truth"], v, reference, use_marks=use_marks))
    if plan["truth"]["kind"] == "selfcheck":            # keeps its outcome (passed or review) for calibration
        return dict(row, graded=False, excluded_by="code", why=NOT_GRADED["calibration"], **kw)
    if row["outcome"] == "untestable":
        return dict(row, graded=False, excluded_by=MODEL_UNDER_TEST, why=NOT_GRADED["untestable"], **kw)
    return dict(row, graded=True, **kw)


SWITCHES = schema.SOFTENINGS + ("selection",)
# What each checker version label asks of the model (verify.verify_video's options); a label not named here is the
# v2 checker. The "c" labels are the same checks with confirm looks added (add_confirm).
CHECKERS = {"v3": dict(act=True), "v3c": dict(act=True),   # v3: the act rule (seen_as)
            "v4": dict(effort="high")}                          # v4: v2 with the model's reasoning effort high


def checker_options(label: str) -> dict:
    return dict(CHECKERS.get(label, {}))
ABLATIONS = [((), "as reported (every rule on)"),
             (("marks",), "without the self-check marks"),
             (("narration",), "without the narration-only rule"),
             (("timing",), "without SAM timing"),
             (("span",), "without the model-seconds cut-short rule"),
             (("+sam_order",), "with the SAM order rule (fails the identical-footage test, so off in the headline)"),
             (("moments",), "without the other-moments rule"),
             (("confirm",), "without the confirm looks"),
             (("act",), "without the act rule (a step seen only by its result is not sent to review)"),
             (("selection",), "without the clean-cut and visibility calls (clips never checked stay not graded)"),
             (SWITCHES, "without any of them")]


def tally(rows: list[dict]) -> dict:
    """Counts per kind over full rows: each outcome, how many graded, how many planted, and wrong flags."""
    out = {}
    for kind in ("omit", "swap", "correct"):
        rs = [r for r in rows if r["truth"]["kind"] == kind]
        t = {"planted": len(rs), "graded": sum(r["graded"] for r in rs)}
        for r in rs:
            t[r["outcome"]] = t.get(r["outcome"], 0) + 1
        g = [r for r in rs if r["graded"]]
        t["wrong_fail_elsewhere"] = sum(1 for r in g if r.get("extras"))
        t["review_elsewhere"] = sum(1 for r in g if r.get("extras_review"))
        out[kind] = t
    return out


def decide(sid: str, plan: dict, v: dict | None, reference: dict, cuts: str, clean: list[bool] | None,
           ungradable: dict[int, str] | None, off: tuple[str, ...] = ()) -> dict:
    """A plan's row: not graded when a selection call leaves it out (unless "selection" is switched off), not
    checked without a saved check, else scored. Under labels a person's visibility call, not the self-check
    marks, decides which planted steps are gradable. Removing a clip's only step leaves nothing to check: not graded,
    decided by code, whatever is switched off."""
    if plan["truth"]["kind"] == "omit" and plan.get("order") == []:
        return result_row(sid, plan, outcome="no_footage")
    if plan["truth"]["kind"] in ("omit", "swap") and "selection" not in off:
        if clean is not None and not plan_is_clean(plan, clean):
            return result_row(sid, plan, outcome="no_clean_cut", by=DECIDED_BY[cuts])
        for k in sorted(plan["truth"]["steps"]):
            u = (ungradable or {}).get(k)
            if isinstance(u, dict):          # per kind of mistake (refined cuts: uncovered_steps)
                u = u.get(plan["truth"]["kind"])
            if u:
                return result_row(sid, plan, outcome=u, by=DECIDED_BY[cuts])
    if v is None:
        return result_row(sid, plan, outcome="not_checked")
    return result_row(sid, plan, v, reference, use_marks="marks" not in off and cuts != "labels")


def never_extracted_rows(sid: str, run_dir: Path, cuts: str) -> list[dict]:
    """Under labels, each step the person saw that the model never listed: a removal no check could catch, counted
    among the planted removals and not graded."""
    if cuts != "labels":
        return []
    return [result_row(sid, dict(name=f"never{i}", order=None, truth=dict(kind="omit", steps=[])), outcome="never_extracted",
                       by=MODEL_UNDER_TEST, missed_step=str(text))
            for i, text in enumerate(load_labels(run_dir).get("missed_steps", []))]


def full_rows_problems(rows: list[dict], n_steps: dict[str, int]) -> list[str]:
    """The full-denominator check: every source has exactly one row per plan (all_plans) plus its self-check, and
    rows for steps the model never extracted (labels only)."""
    out = []
    for sid, n in n_steps.items():
        want = sorted([p["name"] for p in all_plans(n)] + ["selfcheck"])
        got = sorted(r["name"] for r in rows if r["sid"] == sid and r["outcome"] != "never_extracted")
        if got != want:
            out.append(f"{sid}: rows {got} != plans {want}")
    return out


async def prepare_source(sid: str, src_video: Path, runs_root: Path, budget: float, width: int = 854) -> dict:
    """Scout, choose the window, cut the clip, and build its reference (extract, ground, self-check)."""
    run_dir = Path(runs_root) / f"bench-{sid}"; run_dir.mkdir(parents=True, exist_ok=True)
    sha = sha256_file(Path(src_video))
    (run_dir / "source.json").write_text(json.dumps({"sid": sid, "video": Path(src_video).name, "sha256": sha,
                                                     "holdout": sha in holdout_hashes(run_dir)}, indent=1))
    client = make_client(run_dir, budget)
    full = run_dir / "full.mp4"
    if not full.exists():
        _, dur = media.count_frames_and_secs(Path(src_video))
        media.cut(Path(src_video), [(0.0, dur)], full, width=width, fps=15)
    _, full_dur = media.count_frames_and_secs(full)
    if is_holdout(run_dir):             # the exam window is drawn, not chosen by the model
        (a, b), picked = seeded_window(sha, full_dur), None
    else:
        scout_p = run_dir / "scout.procedure.json"
        scout = json.loads(scout_p.read_text()) if scout_p.exists() else await extract(client, full, run_dir, "scout", max_output_tokens=16000)
        win = choose_window(scout, full_dur)
        if win is None:
            return dict(sid=sid, error="no window of 4 to 7 steps within 20 to 75 s", scout_steps=len(scout["steps"]))
        a, b, picked = win
    clip = run_dir / "clip.mp4"
    media.cut(full, [(a, b)], clip, width=width, fps=15)
    ref = await extract(client, clip, run_dir, "reference")
    await ground(client, ref, clip, run_dir, "reference")
    ref = await self_check(client, ref, clip, run_dir, "reference")
    (run_dir / "reference.procedure.json").write_text(json.dumps(ref, indent=1))
    return dict(sid=sid, window=[a, b], scout_steps=picked, reference_steps=len(ref["steps"]))


async def run_variants(sid: str, runs_root: Path, budget: float, concurrency: int = 6, cuts: str = "midpoint",
                       only: list[str] | None = None, rep: int = 0, checker: str = "") -> list[dict]:
    run_dir = Path(runs_root) / f"bench-{sid}"
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    clip = run_dir / "clip.mp4"
    _, dur = media.count_frames_and_secs(clip)
    require_independent(run_dir, cuts)
    pieces, clean = cut_plan(run_dir, ref, dur, cuts)
    ungradable = ungradable_steps(run_dir, cuts)
    pre, vdir, results_file = trial_paths(run_dir, cuts, rep, checker)
    pre0, _, _ = trial_paths(run_dir, cuts)
    gp = run_dir / "reference.grounding.json"
    grounding = json.loads(gp.read_text()) if gp.exists() else None
    vdir.mkdir(exist_ok=True)
    client = make_client(run_dir, budget)
    sem = asyncio.Semaphore(concurrency)

    async def one(plan: dict) -> dict:
        # every plan is checked; a selection call only decides grading, at scoring time, so a score can be shown
        # with and without it (rescore_results, off=("selection",))
        out = run_dir / f"{pre}verify-{plan['name']}.json"
        first_timing = run_dir / f"{pre0}verify-{plan['name']}.timing.json"
        async with sem:
            try:                             # one failed cut, check or score must not lose the others
                if not pieces(plan["order"]):    # nothing left to cut (a one-step clip's removal): no check, no spend
                    return decide(sid, plan, None, ref, cuts, clean, ungradable)
                video = vdir / f"{plan['name']}.mp4"
                if not video.exists():
                    media.cut(clip, pieces(plan["order"]), video, width=854, fps=15)
                if (rep or checker) and first_timing.exists() and not (run_dir / f"{pre}verify-{plan['name']}.timing.json").exists():
                    # the same clip: SAM's measurement does not change between repeats or checker versions, so reuse it
                    (run_dir / f"{pre}verify-{plan['name']}.timing.json").write_text(first_timing.read_text())
                v = json.loads(out.read_text()) if out.exists() else \
                    await verify_video(client, ref, video, run_dir, f"{pre}verify-{plan['name']}", clip, grounding=grounding,
                                       **checker_options(checker))
                return decide(sid, plan, v, ref, cuts, clean, ungradable)
            except Exception as ex:
                return result_row(sid, plan, outcome="error", error=str(ex)[:300])
    plans = [p for p in all_plans(len(ref["steps"])) if only is None or p["name"] in only]
    results = list(await asyncio.gather(*(one(p) for p in plans)))
    sc = json.loads((run_dir / "reference.selfcheck.json").read_text())
    results.append(result_row(sid, SELFCHECK_PLAN, sc))
    if only is None:
        results_file.write_text(json.dumps(results, indent=1))
    return results


async def add_confirm(sid: str, runs_root: Path, budget: float, cuts: str = "refined", from_checker: str = "",
                      to_checker: str = "c", concurrency: int = 6) -> list[dict]:
    """The confirm look as an experiment on fixed first passes: every saved check of from_checker is copied to
    to_checker with its raw responses (the same answers, so only the confirm looks differ), and each step it placed
    in the video gets a second look at that stretch (verify.confirm_looks). The copy records where it came from."""
    from .verify import confirm_looks, reference_frames
    run_dir = Path(runs_root) / f"bench-{sid}"
    require_independent(run_dir, cuts)
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    pre_from, vdir, _ = trial_paths(run_dir, cuts, 0, from_checker)
    pre_to, _, _ = trial_paths(run_dir, cuts, 0, to_checker)
    client = make_client(run_dir, budget)
    sem = asyncio.Semaphore(concurrency)

    async def one(plan: dict) -> dict:
        src, dst = f"{pre_from}verify-{plan['name']}", f"{pre_to}verify-{plan['name']}"
        if not (run_dir / f"{src}.json").exists():
            return dict(name=plan["name"], skipped="no saved check")
        if (run_dir / f"{dst}.json").exists():
            return dict(name=plan["name"], skipped="done")
        for f in (run_dir / "raw").glob(f"{src}.*.json"):
            (run_dir / "raw" / (dst + f.name[len(src):])).write_bytes(f.read_bytes())
        if (run_dir / f"{src}.timing.json").exists():
            (run_dir / f"{dst}.timing.json").write_bytes((run_dir / f"{src}.timing.json").read_bytes())
        v = json.loads((run_dir / f"{src}.json").read_text())
        video = vdir / f"{plan['name']}.mp4"
        async with sem:
            try:
                frames = reference_frames(ref, run_dir, dst, run_dir / "clip.mp4")
                v = await confirm_looks(client, ref, v, frames, video, run_dir, dst, v["_source"]["duration_s"],
                                        **checker_options(to_checker))
            except Exception as ex:
                return dict(name=plan["name"], error=str(ex)[:300])
        v = schema.apply_order_rules(ref, v)
        v["_source"] = dict(v["_source"], first_pass_from=src)
        (run_dir / f"{dst}.json").write_text(json.dumps(v, indent=1))
        return dict(name=plan["name"], looks=sum("confirm_look" in c for c in v["checks"]), verdict=v["verdict"])
    return list(await asyncio.gather(*(one(p) for p in all_plans(len(ref["steps"])))))


async def boundaries_for(sid: str, runs_root: Path, budget: float) -> list[dict]:
    run_dir = Path(runs_root) / f"bench-{sid}"
    refuse_on_holdout(run_dir, "the model's step-boundary calls")
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    return await refine_boundaries(make_client(run_dir, budget), ref, run_dir / "clip.mp4", run_dir)


async def remnants(sid: str, runs_root: Path, budget: float, cuts: str) -> list[dict]:
    """The free-ish yardstick for a cut method: for each removed step that SAM can measure (its tool works at a
    place of its own), the seconds SAM still sees the tool there after the removal, against the expert's.
    Midpoint cuts reuse the saved measurement; other cuts make the variant and run one SAM call each."""
    run_dir = Path(runs_root) / f"bench-{sid}"
    refuse_on_holdout(run_dir, "the remnant yardstick")
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    grounding = json.loads((run_dir / "reference.grounding.json").read_text())
    phrase = timing.tool_phrase(ref, grounding)
    if phrase is None:
        return []
    fitted = timing.fit(ref, grounding, phrase)["steps"]
    clip = run_dir / "clip.mp4"
    _, dur = media.count_frames_and_secs(clip)
    pieces, clean = cut_plan(run_dir, ref, dur, cuts)
    pre, vdir, _ = trial_paths(run_dir, cuts)
    vdir.mkdir(exist_ok=True)
    client = make_client(run_dir, budget)
    out = []
    for plan in variant_plans(len(ref["steps"])):
        k = plan["truth"]["steps"][0]
        if plan["truth"]["kind"] != "omit" or not fitted[k]["measurable"]:
            continue
        if clean is not None and not plan_is_clean(plan, clean):
            out.append(dict(sid=sid, step=k, clean=False)); continue
        name = f"{pre}verify-{plan['name']}"
        if cuts == "midpoint":
            v = json.loads((run_dir / f"{name}.json").read_text())
            m = next((c.get("measured") for c in v["checks"] if c["reference_step"] == k), None)
        else:
            video = vdir / f"{plan['name']}.mp4"
            if not video.exists():
                media.cut(clip, pieces(plan["order"]), video, width=854, fps=15)
            meas = await measure_timing(client, ref, grounding, video, run_dir, name)
            m = (meas["steps"].get(str(k)) or meas["steps"].get(k)) if meas else None
        if m:
            out.append(dict(sid=sid, step=k, clean=True, ref_seconds=m["ref_seconds"], seconds=m["seconds"]))
    return out


async def add_timing_to_saved(sid: str, runs_root: Path, budget: float, concurrency: int = 6) -> int:
    """Add the SAM timing measurement to saved checks that lack it (one SAM call each)."""
    from .verify import add_timing
    run_dir = Path(runs_root) / f"bench-{sid}"
    refuse_on_holdout(run_dir, "SAM timing on the midpoint cuts")
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    grounding = json.loads((run_dir / "reference.grounding.json").read_text())
    client = make_client(run_dir, budget)
    sem = asyncio.Semaphore(concurrency)
    todo = [f for f in sorted(run_dir.glob("verify-*.json"))
            if not f.name.endswith(".timing.json") and "timing" not in json.loads(f.read_text())]

    async def one(f: Path) -> None:
        v = json.loads(f.read_text())
        video = run_dir / "variants" / f"{f.stem[len('verify-'):]}.mp4"
        async with sem:
            v = await add_timing(client, ref, grounding, v, video, run_dir, f.stem)
        f.write_text(json.dumps(v, indent=1))
    await asyncio.gather(*(one(f) for f in todo))
    return len(todo)


def timing_model(run_dir: Path, ref: dict) -> dict | None:
    """The SAM timing model fitted on the expert's clip, or None without a usable tool track."""
    gp = Path(run_dir) / "reference.grounding.json"
    g = json.loads(gp.read_text()) if gp.exists() else None
    phrase = timing.tool_phrase(ref, g) if g else None
    return timing.fit(ref, g, phrase) if phrase else None


def load_check(f: Path, ref: dict, model: dict | None, **rules) -> dict:
    """A saved check under the current rules, its measurements given the current fit's reference side."""
    v = json.loads(Path(f).read_text())
    if model:
        timing.refresh_reference_fields(v, model)
    return schema.apply_order_rules(ref, v, **rules)


def source_dirs(runs_root: Path) -> list[Path]:
    return [d for d in sorted(Path(runs_root).glob("bench-*")) if d.is_dir() and (d / "reference.procedure.json").exists()]


def rescore_results(runs_root: Path, cuts: str = "midpoint", rep: int = 0, off: tuple[str, ...] = (),
                    checker: str = "") -> list[dict]:
    """Re-score every source's saved checks with the current rules (free): one row per planted mistake, graded or
    not (result_row), plus each source's self-check. off names inputs to switch off (SWITCHES: the model-derived
    softenings, and the model's clean-cut calls, which then grade every checked clip), so every number can be shown
    with and without each. Saved checks are read, never rewritten: they are the run's evidence."""
    unknown = set(off) - set(SWITCHES) - set(schema.OPT_IN)
    if unknown:
        raise ValueError(f"unknown switches {sorted(unknown)}; known: {SWITCHES + schema.OPT_IN}")
    rules = schema.rules_for(off)
    out = []
    for run_dir in source_dirs(runs_root):
        sid = run_dir.name[len("bench-"):]
        ref = json.loads((run_dir / "reference.procedure.json").read_text())
        pre, _, _ = trial_paths(run_dir, cuts, rep, checker)
        plans = all_plans(len(ref["steps"]))
        require_independent(run_dir, cuts)
        clean = None
        if cuts != "midpoint":
            if not (run_dir / CUT_INPUT[cuts]).exists():
                out += [result_row(sid, p, outcome="not_checked", note=f"no {CUT_INPUT[cuts]} for this source")
                        for p in plans + [SELFCHECK_PLAN]]
                continue
            _, dur = media.count_frames_and_secs(run_dir / "clip.mp4")
            _, clean = cut_plan(run_dir, ref, dur, cuts)
        ungradable = ungradable_steps(run_dir, cuts)
        model = timing_model(run_dir, ref)
        for p in plans + [SELFCHECK_PLAN]:
            f = run_dir / ("reference.selfcheck.json" if p["name"] == "selfcheck" else f"{pre}verify-{p['name']}.json")
            v = None
            if f.exists():
                v = load_check(f, ref, model, **rules)
            out.append(decide(sid, p, v, ref, cuts, clean, ungradable, off))
        out += never_extracted_rows(sid, run_dir, cuts)
    return out
