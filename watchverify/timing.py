"""SAM timing check: where the tool is tells which step is happening, so time per step can be measured instead of
guessed from a language model's seconds.

A k-nearest-neighbor model is fitted on the expert's video: every frame where SAM 3.1 tracked the tool becomes a
point (the box center, in the tracking copy's pixels divided by its width), labeled with the step whose time window
contains it, or "between steps". In a candidate video the same tool is tracked, each frame is labeled by its nearest
reference points, the labels are smoothed over one second, and code measures each step's seconds and the order in
which steps began. A step is measurable only if its own reference frames classify back to it (leave-one-out), so a
step done at the same place as another is never judged by position.

Assumes the camera does not move between the two videos (a fixed workstation camera; true for variants cut from
one clip). The measurement is a second sensor next to the model's reading; schema.apply_order_rules acts when they
agree and asks for review when they disagree."""
from collections import Counter

BETWEEN = -1
K = 5
MAX_DIST = 0.08          # farther than this (in frame widths) from every reference point: unknown place
MEASURABLE = 0.6         # share of a step's own reference frames that must classify back to it
MIN_RUN = 3              # frames in a row before a step counts as begun (0.6 s at 5 fps)


def tool_phrase(procedure: dict, grounding: dict, min_boxes: int = 20) -> str | None:
    """The first tracked phrase (the extractor lists tools first) with enough boxes, else the most tracked one."""
    counts = {p: len(grounding["tracks"].get(p, [])) for p in grounding["phrases"]}
    for p in grounding["phrases"]:
        if counts[p] >= min_boxes:
            return p
    best = max(counts, key=counts.get, default=None)
    return best if best and counts[best] > 0 else None


def points(boxes: list[dict], width: int) -> dict[int, tuple[float, float, float]]:
    """One point per frame: the center of the box of the object id seen most often (frame -> (t, x, y))."""
    ids = Counter(b["object_id"] for b in boxes)
    out: dict[int, tuple[float, float, float]] = {}
    for b in sorted(boxes, key=lambda b: -ids[b["object_id"]]):
        if b["frame"] not in out and b["t"] is not None:
            out[b["frame"]] = (b["t"], (b["left"] + b["right"]) / 2 / width, (b["top"] + b["bottom"]) / 2 / width)
    return out


def _label(steps: list[dict], t: float) -> int:
    for s in steps:
        if s["start_s"] <= t <= s["end_s"]:
            return s["index"]
    return BETWEEN


def _knn(train: list[tuple[float, float, int]], x: float, y: float, skip: int | None = None) -> int | None:
    d = sorted(((px - x) ** 2 + (py - y) ** 2, lab) for i, (px, py, lab) in enumerate(train) if i != skip)
    if not d or d[0][0] ** 0.5 > MAX_DIST:
        return None
    return Counter(lab for _, lab in d[:K]).most_common(1)[0][0]


def fit(procedure: dict, grounding: dict, phrase: str) -> dict:
    fps, width = grounding["track_fps"], grounding["width"]
    pts = points(grounding["tracks"][phrase], width)
    train = [(x, y, _label(procedure["steps"], t)) for t, x, y in pts.values()]
    per_step = {}
    for s in procedure["steps"]:
        own = [i for i, p in enumerate(train) if p[2] == s["index"]]
        back = sum(_knn(train, train[i][0], train[i][1], skip=i) == s["index"] for i in own)
        per_step[s["index"]] = dict(ref_seconds=round(len(own) / fps, 2),
                                    self_accuracy=round(back / len(own), 2) if own else 0.0,
                                    measurable=bool(own) and len(own) / fps >= 1.0 and back / len(own) >= MEASURABLE)
    model = dict(phrase=phrase, fps=fps, width=width, train=train, steps=per_step)
    # the expert's own tool path, measured the way a candidate is: where it already reaches a later step's place
    # first (the tool passes over it), the same pattern in a candidate is a shared place, not disorder
    boxes = grounding["tracks"][phrase]
    base = measure(model, boxes, grounding.get("track_frames") or max((b["frame"] for b in boxes), default=-1) + 1)
    for k, m in base["steps"].items():
        per_step[k]["ref_began_s"] = m["began_s"]
    return model


REFERENCE_FIELDS = ("ref_seconds", "self_accuracy", "measurable", "ref_began_s")


def refresh_reference_fields(v: dict, model: dict) -> dict:
    """Give a saved check's measurements the current fit's reference side (which depends only on the expert's
    clip), so rules added later apply to saved measurements without a new SAM call."""
    for c in v["checks"]:
        m, ref = c.get("measured"), model["steps"].get(c["reference_step"])
        if m is not None and ref is not None:
            m.update({k: ref[k] for k in REFERENCE_FIELDS})
    return v


def smooth(labels: list[int | None], window: int = 5) -> list[int | None]:
    out = []
    for i in range(len(labels)):
        w = [l for l in labels[max(0, i - window // 2): i + window // 2 + 1] if l is not None]
        out.append(Counter(w).most_common(1)[0][0] if w else None)
    return out


def measure(model: dict, boxes: list[dict], n_frames: int) -> dict:
    """Seconds per step and the second each step began, in a candidate tracked at the model's fps and width."""
    fps = model["fps"]
    pts = points(boxes, model["width"])
    raw = [(_knn(model["train"], pts[f][1], pts[f][2]) if f in pts else None) for f in range(n_frames)]
    labels = smooth(raw)
    seconds = Counter(l for l in labels if l is not None and l != BETWEEN)
    began: dict[int, float] = {}
    run_label, run_len = None, 0
    for f, l in enumerate(labels):
        run_len = run_len + 1 if l == run_label else 1
        run_label = l
        if l not in (None, BETWEEN) and run_len == MIN_RUN and l not in began:
            began[l] = round((f - MIN_RUN + 1) / fps, 2)
    steps = {}
    for k, ref in model["steps"].items():
        steps[k] = dict(ref, seconds=round(seconds.get(k, 0) / fps, 2), began_s=began.get(k))
    return dict(phrase=model["phrase"], frames=n_frames, tracked_frames=len(pts), steps=steps)


def attach(v: dict, measurement: dict) -> dict:
    """Put each step's measurement on its check, for the rules and the report."""
    for c in v["checks"]:
        m = measurement["steps"].get(c["reference_step"]) or measurement["steps"].get(str(c["reference_step"]))
        if m is not None:
            c["measured"] = m
    v["timing"] = {k: measurement[k] for k in ("phrase", "frames", "tracked_frames")}
    return v
