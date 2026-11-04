"""Grading evidence anyone can re-score. export_evidence copies what an accuracy-test grading used and produced
(the reference as run, its SAM grounding, each planted mistake's plan with its truth and cut pieces, every raw model
response and the request as sent, the cost ledger, the claimed results) into one folder, without the videos.
replay_evidence rebuilds every check through the checker's own code (verify.verify_video): the transport reads the
saved responses instead of calling Meta, and ReplayMedia stands in for ffmpeg with each clip's length and
tracking-frame count. No network, no key. A match with the claimed results shows the totals follow from the saved
answers by the published code; it does not show the answers are right.

The grader's inputs other than the checks are separate files, each saying who made it, so each can be swapped for
its neutral version in neutral/ and the totals recomputed (INPUTS; the two-number rule of the 2026-10-28 audit):
  marks.json                the self-check's mark per step: a step the checker did not find in the expert's clip
                            reads "can't tell", and a mistake planted on it is not graded
  narration.json            steps whose checkpoint is only heard: "can't tell", never missing
  selection.json            which step boundaries are clean: a mistake planted across an unclean one is not graded
  reference.grounding.json  SAM tracks of the expert's clip, the basis of SAM timing
The checks are rebuilt with the reference as run (its marks decided which steps got a second look); the switches
act at scoring, on the same observations. So "without the marks" re-scores what the model saw; a run without them
would also have taken second looks the saved run did not. Leaks into the model's requests are prevented by the
checker's allow-list (verify._spec) and tested by tests/test_leaks.py, whose planted markers are random tokens that
can only match exactly; searching saved requests for the real answer key's values is not used, since a real value
(a half second, a common word) also turns up where nothing leaked."""
import asyncio, json, shutil, tempfile
from pathlib import Path
from . import bench, media, schema
from .budget import Budget
from .ledger import Ledger
from .meta_client import MetaClient, ReplayTransport, safe_name
from .verify import verify_video

REFERENCE_FILES = ("reference.procedure.json", "reference.grounding.json", "reference.boundaries.json")
REFERENCE_KEYS = ("scout.", "reference.", "boundary")
INPUTS = {"marks": ("marks.json", "neutral/no-marks.json"),
          "narration": ("narration.json", "neutral/no-narration.json"),
          "selection": ("selection.json", "neutral/all-clean.json"),
          "grounding": ("reference.grounding.json", "neutral/no-grounding.json")}


class ReplayMedia:
    """The video toolkit verify_video uses, answered from the plan instead of a file: the candidate's length and
    the tracking copy's frame count. Cutting and resampling make nothing; their output is never read in replay."""

    def __init__(self, duration_s: float, track_frames: int | None):
        self.duration_s, self.track_frames = duration_s, track_frames

    def count_frames_and_secs(self, path: Path) -> tuple[int, float]:
        if ".track" in Path(path).name:
            return int(self.track_frames or 0), 0.0
        return 0, float(self.duration_s)

    def cut(self, src: Path, segments, out: Path, **kw) -> Path:
        return Path(out)

    def resample(self, src: Path, out: Path, **kw) -> Path:
        return Path(out)


def _scrub(reference: dict) -> dict:
    ref = json.loads(json.dumps(reference))
    if "_source" in ref and "video" in ref["_source"]:
        ref["_source"]["video"] = "clip.mp4"           # the local path means nothing elsewhere
    return ref


def _write(path: Path, d) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=1))


def grader_inputs(ref: dict, clean: list[bool] | None, ungradable: dict[int, str] | None, cuts: str) -> dict[str, tuple[dict, dict]]:
    """Each switchable input of the grader as (the run's version, its neutral version), with who made it."""
    mut = bench.MODEL_UNDER_TEST
    return {
        "marks": (dict(made_by=mut, how="the checker run on the expert's own clip (self-check)",
                       steps={str(st["index"]): st.get("self_check", "observed") for st in ref["steps"]}),
                  dict(made_by="code", how="neutral: no marks, every step counts as found in the expert's clip", steps={})),
        "narration": (dict(made_by=mut, how="the reference's checkpoint_visibility",
                           steps=[st["index"] for st in ref["steps"] if st.get("checkpoint_visibility") == "narration_only"]),
                      dict(made_by="code", how="neutral: no step is narration-only", steps=[])),
        "selection": (dict(made_by=bench.DECIDED_BY.get(cuts, "code"), cuts=cuts, clean=clean,
                           ungradable=None if ungradable is None else {str(k): v for k, v in sorted(ungradable.items())},
                           how="a planted mistake is graded only if the boundaries around its steps are clean and, "
                               "under labels, a person says its steps are real and a camera shows them"),
                      dict(made_by="code", cuts=cuts, clean=None, ungradable=None,
                           how="neutral: every boundary counts as clean and every step as real and visible")),
    }


def export_evidence(run_dir: Path, out: Path, cuts: str = "refined", rep: int = 0, checker: str = "") -> dict:
    """Copy one source's grading into out/ (see the module note). Returns the summary written to results.json."""
    run_dir, out = Path(run_dir), Path(out)
    sid = run_dir.name[len("bench-"):]
    bench.require_independent(run_dir, cuts)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    for f in REFERENCE_FILES:
        if (run_dir / f).exists():
            d = json.loads((run_dir / f).read_text())
            _write(out / f, _scrub(d) if f == "reference.procedure.json" else d)
    _write(out / INPUTS["grounding"][1], {})
    if not (out / INPUTS["grounding"][0]).exists():
        _write(out / INPUTS["grounding"][0], {})            # no tool track: no SAM timing either way
    _, clip_s = media.count_frames_and_secs(run_dir / "clip.mp4")
    pieces, clean = bench.cut_plan(run_dir, ref, clip_s, cuts)
    ungradable = bench.ungradable_steps(run_dir, cuts)
    if cuts == "labels":
        shutil.copy2(run_dir / "labels.json", out / "labels.json")       # the truth, as the person confirmed it
    for name, (run, neutral) in grader_inputs(ref, clean, ungradable, cuts).items():
        _write(out / INPUTS[name][0], run); _write(out / INPUTS[name][1], neutral)
    pre, vdir, _ = bench.trial_paths(run_dir, cuts, rep, checker)
    plans, checks = [], ["reference.selfcheck"]
    # claimed results are the saved checks under the current rules, as bench.rescore_results scores them
    model = bench.timing_model(run_dir, ref)
    sc = bench.load_check(run_dir / "reference.selfcheck.json", ref, model)
    # the self-check ran against the reference before it carried the self-check's own marks; its claimed outcome
    # is that run re-scored with the marks (bench.rescore_results), so replay does the same (reference_view)
    plans.append(dict(name="selfcheck", order=None, truth=bench.SELFCHECK_PLAN["truth"], checked=True,
                      check="reference.selfcheck", reference_view="unmarked", pieces=[[0.0, clip_s]],
                      duration_s=sc["_source"].get("duration_s", clip_s), track_frames=None,
                      claimed=bench.result_row(sid, bench.SELFCHECK_PLAN, sc, ref)))
    for p in bench.all_plans(len(ref["steps"])):
        entry = dict(name=p["name"], order=p["order"], truth=p["truth"], pieces=[list(x) for x in pieces(p["order"])])
        check = f"{pre}verify-{p['name']}"
        if not (run_dir / f"{check}.json").exists():
            plans.append(dict(entry, checked=False, claimed=bench.decide(sid, p, None, ref, cuts, clean, ungradable)))
            continue
        v = bench.load_check(run_dir / f"{check}.json", ref, model)
        dur = v["_source"].get("duration_s") or media.count_frames_and_secs(vdir / f"{p['name']}.mp4")[1]
        plans.append(dict(entry, checked=True, check=check, duration_s=dur, track_frames=(v.get("timing") or {}).get("frames"),
                          confirm=any("confirm_look" in c for c in v["checks"]),
                          **({"first_pass_from": v["_source"]["first_pass_from"]} if "first_pass_from" in v["_source"] else {}),
                          claimed=bench.decide(sid, p, v, ref, cuts, clean, ungradable)))
        checks.append(check)
    for row in bench.never_extracted_rows(sid, run_dir, cuts):
        plans.append(dict(name=row["name"], order=None, truth=row["truth"], checked=False, never_extracted=True, claimed=row))
    for f in sorted((run_dir / "raw").glob("*.json")):
        if any(f.name.startswith(c + ".") for c in checks) or f.name.startswith(REFERENCE_KEYS):
            shutil.copy2(f, out / "raw" / f.name)
    # a repeat or a later checker reuses the first run's SAM measurement of the same clip (bench.run_variants); its
    # raw SAM answer is carried under this check's names, and the plan says where it came from
    pre0, _, _ = bench.trial_paths(run_dir, cuts)
    for p in plans:
        if p.get("checked") and p["track_frames"] and not (out / "raw" / f"{p['check']}.sam.json").exists():
            first = f"{pre0}verify-{p['name']}"
            for suffix in (".track.upload.json", ".sam.json"):
                shutil.copy2(run_dir / "raw" / f"{first}{suffix}", out / "raw" / f"{p['check']}{suffix}")
            p["timing_from"] = first
    keep = tuple(c + "." for c in checks) + REFERENCE_KEYS
    lines = [l for l in (run_dir / "ledger.jsonl").read_text().splitlines()
             if json.loads(l).get("key", "").startswith(keep) or json.loads(l).get("key", "") in checks]
    (out / "ledger.jsonl").write_text("\n".join(lines) + "\n")
    _write(out / "plans.json", dict(source=sid, cuts=cuts, clip_s=clip_s, plans=plans))
    if (run_dir / "source.json").exists():          # which registered video this is, by content hash
        shutil.copy2(run_dir / "source.json", out / "source.json")
    summary = dict(source=run_dir.name, planted=len(plans) - 1, checked=sum(p["checked"] for p in plans) - 1,
                   graded=sum(p["claimed"]["graded"] for p in plans),
                   claimed={p["name"]: p["claimed"]["outcome"] for p in plans})
    _write(out / "results.json", summary)
    return summary


def scoring_reference(ref: dict, marks: dict, narration: dict) -> dict:
    """The reference the rules see: the run's own, with each step's self-check mark and narration-only flag taken
    from the given files (the run's or the neutral ones)."""
    nar = set(narration["steps"])
    steps = []
    for st in ref["steps"]:
        vis = st.get("checkpoint_visibility")
        vis = "narration_only" if st["index"] in nar else ("clear" if vis == "narration_only" else vis)
        steps.append(dict(st, self_check=marks["steps"].get(str(st["index"]), "observed"), checkpoint_visibility=vis))
    return dict(ref, steps=steps)


async def replay_source(ev: Path, use: dict[str, Path] | None = None, off: tuple[str, ...] = ()) -> list[dict]:
    """Rebuild every checked plan of one exported source from its raw responses and score it. use maps an input
    name (INPUTS) to the file to read instead of the evidence's own, such as its neutral version; off names rules
    to switch off (bench.SWITCHES), as bench-score's with-and-without rows do."""
    ev = Path(ev)
    paths = {k: ev / f for k, (f, _) in INPUTS.items()} | {k: Path(p) for k, p in (use or {}).items()}
    inp = {k: json.loads(p.read_text()) for k, p in paths.items()}
    ref = json.loads((ev / "reference.procedure.json").read_text())
    meta = json.loads((ev / "plans.json").read_text())
    sid = safe_name(meta.get("source", ev.name))
    for p in meta["plans"]:                  # names from someone else's evidence become file names: refuse any that could escape
        safe_name(p["name"])
        if p.get("checked"):
            safe_name(p["check"])
    grounding = inp["grounding"] or None
    sref = scoring_reference(ref, inp["marks"], inp["narration"])
    cuts, clean = meta["cuts"], inp["selection"]["clean"]
    rules = schema.rules_for(off)
    ung = inp["selection"].get("ungradable")
    ungradable = None if ung is None else {int(k): v for k, v in ung.items()}
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "ledger.jsonl")
        client = MetaClient(ReplayTransport(ev / "raw"), ledger, Budget(ledger, 1e9))
        for p in meta["plans"]:
            if not p["checked"]:
                row = dict(p["claimed"]) if p.get("never_extracted") else bench.decide(sid, p, None, sref, cuts, clean, ungradable, off)
                out.append(dict(row, claimed=p["claimed"]["outcome"], match=row["outcome"] == p["claimed"]["outcome"]))
                continue
            unmarked = {**ref, "steps": [{k: x for k, x in st.items() if k != "self_check"} for st in ref["steps"]]}
            view = unmarked if p.get("reference_view") == "unmarked" else ref
            v = await verify_video(client, view, Path(tmp) / f"{p['check']}.mp4", Path(tmp), p["check"],
                                   reference_video=Path(tmp) / "no-expert-video", look_again=True,
                                   grounding=grounding if p["track_frames"] else None, confirm=p.get("confirm", False),
                                   m=ReplayMedia(p["duration_s"], p["track_frames"]))
            v = schema.apply_order_rules(sref, v, **rules)
            plan = bench.SELFCHECK_PLAN if p["name"] == "selfcheck" else p
            row = bench.decide(sid, plan, v, sref, cuts, clean, ungradable, off)
            out.append(dict(row, claimed=p["claimed"]["outcome"], match=row["outcome"] == p["claimed"]["outcome"]))
    return out


def replay_evidence(root: Path, without: tuple[str, ...] = (), use: dict[str, Path] | None = None,
                    off: tuple[str, ...] = ()) -> dict:
    """Replay every source folder under root (or root itself). without names inputs (INPUTS) to swap for their
    neutral versions; use names explicit files (one source only); off names rules to switch off (bench.SWITCHES).
    Totals over full rows (bench.tally), and which rows match the claimed results (meaningful only with every input
    as exported and every rule on)."""
    root = Path(root)
    unknown = set(without) - set(INPUTS)
    if unknown:
        raise ValueError(f"unknown inputs {sorted(unknown)}; known: {sorted(INPUTS)}")
    unknown = set(off) - set(bench.SWITCHES) - set(schema.OPT_IN)
    if unknown:
        raise ValueError(f"unknown switches {sorted(unknown)}; known: {bench.SWITCHES}")
    dirs = [root] if (root / "plans.json").exists() else sorted(d for d in root.iterdir() if (d / "plans.json").exists())
    if use and len(dirs) != 1:
        raise ValueError("explicit input files name one source's evidence folder")
    rows = []
    for d in dirs:
        u = {k: d / INPUTS[k][1] for k in without} | dict(use or {})
        rows += [dict(r, source=d.name) for r in asyncio.run(replay_source(d, u, off))]
    return dict(sources=[d.name for d in dirs], checks=len(rows), matches=sum(r["match"] for r in rows),
                as_exported=not without and not use and not off, totals=bench.tally(rows),
                mismatches=[r for r in rows if not r["match"]])
