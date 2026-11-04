"""The accuracy test's results page: outcome tiles over full denominators, every number with and without each rule
that rests on another model output, the comparison between checker versions, and one grid per source video (a row
per planted mistake, a column per step, colored by what the checker reported, the planted steps outlined; a row
that is not graded says why and who decided). Light theme, self-contained, no scripts."""
import html, json, re
from collections import Counter
from pathlib import Path
from . import bench, schema
from .report import CSS

CELL = {"observed": ("#e6f4ea", "seen"), "not_observed": ("#f9d6d5", "missing"), "unclear": ("#fdf0d5", "can't tell"),
        "out_of_order": ("#f4b6b3", "out of order"), "shortened": ("#fde2b8", "cut short"), "disputed": ("#fde2b8", "disputed"),
        "done_differently": ("#dde8f8", "done differently")}
OUTCOME = {"caught": ("caught", "ok"), "flagged": ("flagged for review", "warn"), "missed": ("missed", "bad"),
           "untestable": ("not graded: self-check", "muted"), "correct_pass": ("passed", "ok"), "false_alarm": ("false alarm", "bad"),
           "no_clean_cut": ("not graded: no clean cut", "muted"), "cut_misses_step": ("not graded: cut misses the step", "muted"), "not_checked": ("not checked", "muted"),
           "error": ("check failed", "bad"), "no_footage": ("not graded: nothing left to check", "muted"), "explained_away": ("explained away: done another way", "warn"),
           "not_visible": ("not graded: not visible", "muted"), "not_a_step": ("not graded: not a real step", "muted"),
           "never_extracted": ("not graded: never extracted", "muted")}
EXTRA_CSS = """
.plain{font-size:16px;border-left-color:var(--ink)}.plain ul{margin:6px 0 0 0;padding-left:20px}.plain li{margin:4px 0}
.good{color:var(--ok)}.bad{color:var(--bad)}
.grid td.c{width:26px;height:22px;padding:0;border:1px solid #fff;text-align:center;font-size:11px}
.grid td.p{outline:2px solid #1d2433;outline-offset:-2px}.grid th{font-size:12px;padding:3px 6px}
.grid td.n{font-size:13px;padding:3px 8px;white-space:nowrap}.legend span{display:inline-block;margin-right:14px;font-size:13px}
.legend i{display:inline-block;width:14px;height:14px;vertical-align:middle;margin-right:5px;border:1px solid #d9dee7}
.cmp td,.cmp th{text-align:right;font-size:13px;padding:4px 6px}.cmp td:first-child,.cmp th:first-child{text-align:left;min-width:170px}
.wide{overflow-x:auto}
"""


def e(x) -> str:
    return html.escape(str(x))


def cell_state(c: dict) -> str:
    if c.get("out_of_order"):
        return "out_of_order"
    if c["status"] == "observed" and c.get("shortened"):
        return "shortened"
    if c["status"] == "observed" and c.get("disputed"):
        return "disputed"
    return c["status"]


def label(r: dict) -> str:
    kind, ks = r["truth"]["kind"], r["truth"]["steps"]
    if r["outcome"] == "never_extracted":
        return f"a step the model never listed: {e(r.get('missed_step', ''))}"
    return (f"step {ks[0]} removed" if kind == "omit" else f"steps {ks[0]} and {ks[1]} swapped" if kind == "swap"
            else "expert's clip, checked again" if kind == "correct" else "self-check (calibration, not graded)")


def source_grid(run_dir: Path, results: list[dict], pre: str = "") -> str:
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    model = bench.timing_model(run_dir, ref)
    n = len(ref["steps"])
    head = "".join(f'<th title="{e(st["action"])}">{st["index"]}</th>' for st in ref["steps"])
    rows = []
    for r in results:
        word, cls = OUTCOME.get(r["outcome"], (r["outcome"], "muted"))
        f = run_dir / ("reference.selfcheck.json" if r["name"] == "selfcheck" else f"{pre}verify-{r['name']}.json")
        if r["outcome"] in ("no_clean_cut", "cut_misses_step", "not_checked", "error", "not_visible", "not_a_step", "never_extracted", "no_footage") or not f.exists():
            rows.append(f'<tr><td class="n">{label(r)}</td><td class="n muted" colspan="{n}">{e(r.get("why", "no saved check"))} '
                        f'(decided by {e(r.get("excluded_by", "code"))})</td><td class="n"><span class="badge {cls}">{word}</span></td></tr>')
            continue
        v = bench.load_check(f, ref, model)            # the saved check under the current rules, not rewritten
        by = {c["reference_step"]: c for c in v["checks"]}
        cells = []
        for k in range(n):
            c = by.get(k)
            state = cell_state(c) if c else "unclear"
            color, w = CELL[state]
            planted = k in r["truth"]["steps"]
            reason = (c or {}).get("status_reason") or (c or {}).get("evidence", "")
            cells.append(f'<td class="c{" p" if planted else ""}" style="background:{color}" '
                         f'title="step {k}: {w}. {e(reason[:200])}"></td>')
        extra = (f' <span class="muted">+ wrong flag on step {", ".join(map(str, r["extras"]))}</span>' if r.get("extras") else "")
        if r.get("extras_review"):
            extra += f' <span class="muted">+ review on step {", ".join(map(str, r["extras_review"]))}</span>'
        rows.append(f'<tr><td class="n">{label(r)}</td>{"".join(cells)}<td class="n"><span class="badge {cls}">{word}</span>{extra}</td></tr>')
    steps = "; ".join(f'{st["index"]}: {e(st["action"])}' for st in ref["steps"])
    return (f'<table class="grid"><tr><th>planted mistake</th>{head}<th>outcome</th></tr>{"".join(rows)}</table>'
            f'<p class="muted" style="font-size:13px">Steps: {steps}.</p>')


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def load_sources(path: Path) -> dict[str, dict]:
    """Source details by id: bench/sources.json (a list), or the held-out registry's downloads (bench/holdout.json)."""
    d = json.loads(Path(path).read_text())
    if isinstance(d, dict):
        return {x["sid"]: dict(x, id=x["sid"]) for x in d.get("downloads", [])}
    return {s["id"]: s for s in d}


def labelers(runs_root: Path, sids: list[str]) -> set[str]:
    out = set()
    for sid in sids:
        f = Path(runs_root) / f"bench-{sid}" / "labels.json"
        if f.exists():
            out.add(json.loads(f.read_text())["made_by"])
    return out


def label_changes(runs_root: Path, sids: list[str]) -> tuple[int, int]:
    """Steps labeled, and steps whose proposed values the person changed (labels.json, changed_from_prelabels)."""
    n = changed = 0
    for sid in sids:
        f = Path(runs_root) / f"bench-{sid}" / "labels.json"
        if f.exists():
            d = json.loads(f.read_text())
            n += len(d["steps"]); changed += len(d.get("changed_from_prelabels", []))
    return n, changed


def big_removals(runs_root: Path, rows: list[dict], cuts: str, share: float = 0.3) -> list[dict]:
    """Graded removals whose cut takes out more than this share of the clip (the step plus both in-between stretches)."""
    from . import media
    out, plans = [], {}
    for r in rows:
        if r["truth"]["kind"] != "omit" or not r["graded"]:
            continue
        if r["sid"] not in plans:
            rd = Path(runs_root) / f"bench-{r['sid']}"
            ref = json.loads((rd / "reference.procedure.json").read_text())
            _, dur = media.count_frames_and_secs(rd / "clip.mp4")
            plans[r["sid"]] = (bench.cut_plan(rd, ref, dur, cuts)[0], dur, len(ref["steps"]))
        pieces, dur, n = plans[r["sid"]]
        k = r["truth"]["steps"][0]
        kept = sum(y - x for x, y in pieces([j for j in range(n) if j != k]))
        if dur - kept > share * dur:
            out.append(dict(r, removed_s=round(dur - kept, 1)))
    return out


def untouched_steps(runs_root: Path, rows: list[dict], cuts: str, checker: str) -> dict:
    """Every step nobody touched, in graded clips with a planted mistake and in the untouched copies: how many there
    were, and how many the checker sent to a person (can't tell, done another way, cut short or disputed) or failed.
    Also what a supervisor would have in front of them: marked moments per recording, broken and untouched, and how
    long and how many steps the clips were."""
    out = Counter()
    models, clips = {}, {}
    for r in rows:
        k = r["truth"]["kind"]
        if not (k in ("correct", "omit", "swap") and r["graded"]):
            continue
        rd = Path(runs_root) / f"bench-{r['sid']}"
        ref = json.loads((rd / "reference.procedure.json").read_text())
        if r["sid"] not in models:
            models[r["sid"]] = bench.timing_model(rd, ref)
            clips[r["sid"]] = (len(ref["steps"]), max(st["end_s"] for st in ref["steps"]))
        v = bench.load_check(rd / f"{bench.trial_paths(rd, cuts, 0, checker)[0]}verify-{r['name']}.json", ref, models[r["sid"]])
        planted = set(r["truth"]["steps"])
        marks, on_planted = 0, set()
        for c in v["checks"]:
            red = c["status"] == "not_observed" or bool(c.get("out_of_order"))
            yellow = not red and (c["status"] in ("unclear", "done_differently") or bool(c.get("shortened") or c.get("disputed")))
            marks += red or yellow
            if c["reference_step"] in planted:
                on_planted |= {"red"} if red else {"yellow"} if yellow else set()
                continue
            out["n"] += 1
            out["fail"] += red
            out["review"] += yellow
        # What sat on the planted step when the tally did not count it as noticed (a removal) or counted it as only
        # flagged (a swap): the supervisor still sees a mark there, for another reason, or none at all.
        if k == "omit" and r["graded"] and r["outcome"] not in ("caught", "flagged"):
            out["omit_other_" + ("red" if "red" in on_planted else "yellow" if on_planted else "none")] += 1
        if k == "swap" and r["graded"] and r["outcome"] == "flagged":
            out["swap_flag_" + ("red" if "red" in on_planted else "yellow")] += 1
        side = "good" if k == "correct" else "bad"
        out[f"rec_{side}"] += 1
        out[f"marks_{side}"] += marks
    return {**out, "clips": clips}


# Where "good" and "bad" sit in the plain-words box: a supervisor could lean on the result for that job (good) or
# could not (bad). Rough lines, stated so they can be argued with.
NOTICED_GOOD = 0.75        # removed steps caught or sent to a person
CAUGHT_GOOD = 0.5          # swapped pairs called out of order outright
CLEAN_GOOD = 0.8           # untouched copies of the expert's clip passing clean
FALSE_REVIEW_BAD = 0.10    # untouched steps sent to a person anyway
WORTH_IT = "https://github.com/carrollco/watchverify#where-it-fits"


def plain_words(rows: list[dict], rows_off: list[dict], steps: dict) -> str:
    """The results for a reader outside AI: the question, how to read the marks, what happened (each line marked good
    or bad), what it would mean for a supervisor, and what it can't do. Every number is computed from the rows."""
    t, f = bench.tally(rows), bench.tally(rows_off)
    om, sw, co = (Counter(t[k]) for k in ("omit", "swap", "correct"))      # a count never seen reads as 0
    f = {k: Counter(v) for k, v in f.items()}
    g = om["graded"] or 1
    noticed, slipped = om["caught"] + om["flagged"], om["missed"] + om["explained_away"]
    slipped_off = f["omit"]["missed"] + f["omit"]["explained_away"]
    n = max(steps.get("n", 0), 1)
    u = steps.get("review", 0) / n
    chance_pair = 1 - (1 - u) ** 2
    clean = co.get("correct_pass", 0)
    clips = steps.get("clips", {})
    nsteps, secs = [c[0] for c in clips.values()] or [0], [c[1] for c in clips.values()] or [0]
    per = lambda side: steps.get(f"marks_{side}", 0) / max(steps.get(f"rec_{side}", 0), 1)
    pct = lambda x: f"{100 * x:.0f}%"
    one_in = lambda x: f"about 1 in {round(1 / x)}" if x else "none"
    say = lambda k, one, many: f"{k} {one if k == 1 else many}"
    sg = max(sw["graded"], 1)
    sw_yellow, sw_red = steps.get("swap_flag_yellow", 0), steps.get("swap_flag_red", 0)
    other_marked = steps.get("omit_other_red", 0) + steps.get("omit_other_yellow", 0)
    word = lambda good: '<b class="good">Good:</b>' if good else '<b class="bad">Bad:</b>'
    lines = [
        f'{word(noticed / g >= NOTICED_GOOD)} <b>a step cut out</b> ({om["graded"]} tests): it marked the right step '
        f'{noticed} times, {om["caught"]} red ("missing") and {om["flagged"]} yellow. The other {slipped} were not called '
        f'missing: {say(steps.get("omit_other_red", 0), "got a red mark for the wrong reason (out of order)", "got red marks for the wrong reason (out of order)")}, '
        f'{say(steps.get("omit_other_yellow", 0), "got a yellow", "got yellows")} saying "done another way", and '
        f'{steps.get("omit_other_none", 0)} got no mark at all.',
        f'{word(co["graded"] and clean / co["graded"] >= CLEAN_GOOD)} <b>a job done right</b> ({co["graded"]} recordings): '
        f'{clean} came back with no marks at all; {co["graded"] - clean} got a mark for nothing.',
        f'{word(u <= FALSE_REVIEW_BAD)} <b>false alarms:</b> on steps nobody touched it put a yellow mark on {one_in(u)} '
        f'({steps.get("review", 0)} of {steps.get("n", 0)}) and a red one on {steps.get("fail", 0)}. So yellow is a hint, '
        f'not proof: even a checker that noticed nothing would have marked about {round(u * om["graded"])} of the '
        f'{om["graded"]} cut steps yellow. It marked {om["flagged"]}.',
        f'{word(sw["caught"] / max(sw["graded"], 1) >= CAUGHT_GOOD)} <b>two steps swapped</b> ({sw["graded"]} tests): '
        f'{sw["caught"]} red ("out of order"). {sw_yellow} more got yellow ({pct(sw_yellow / sg)}), but by the same '
        f'arithmetic ({one_in(u)} fine steps gets one) a pair of untouched steps gets a yellow about {pct(chance_pair)} of the time, so those '
        f'{"barely count" if sw_yellow / sg > chance_pair else "count for nothing"}'
        + (f'; {say(sw_red, "more got red marks for the wrong reason (both steps called missing)", "more got red marks for the wrong reason (steps called missing)")}' if sw_red else '') + '.',
        f'<b class="bad">Fine print:</b> two backup rules make many of the yellow marks. One uses SAM 3.1, Meta\'s object '
        f'tracker, to measure how long the tool is in use at each step; the other marks a step much shorter than the '
        f'expert\'s. With both off, {slipped_off} of {om["graded"]} cut steps are not counted as noticed, instead of '
        f'{slipped}.']
    shop = (f'<p><b>What it would mean for a supervisor.</b> Instead of watching every recording, you open the ones with '
            f'marks and jump to the marked moments: about {per("bad"):.0f} per broken recording here, '
            f'{per("good"):.1f} per good one. Doing that on these videos, {noticed} of the {om["graded"]} cut steps would '
            f'have been put in front of you as missing or worth a look, {other_marked} more with a mark for another '
            f'reason, and {steps.get("omit_other_none", 0)} with no mark at all. That only helps if you can tell from '
            f'the marked moment that the step is missing. It is a pointer for a person, not an inspector that signs off '
            f'a job.</p>')
    cant = (f'<p><b>What these numbers can\'t tell you.</b> Each test clip is {min(secs):.0f} to {max(secs):.0f} seconds '
            f'with {min(nsteps)} to {max(nsteps)} steps; a real job can run an hour. The mistakes were made by cutting '
            f'video, which is not quite how people skip steps (see the README). The untouched copies are the expert\'s own '
            f'video, re-cut, which is easier to pass clean than a different person doing the job. It can\'t yet tell one '
            f'bolt from another. '
            f'And {om["graded"]} tests is a small number: read every figure as rough. What it adds and what it\'s good for: '
            f'<a href="{WORTH_IT}">the README (EXTERNAL · source repo ↗)</a>.</p>')
    lines_used = (f'Where good and bad sit (rough lines, argue with them): good if at least {pct(NOTICED_GOOD)} of cut '
                  f'steps get a mark, at least {pct(CAUGHT_GOOD)} of swaps get red, at least {pct(CLEAN_GOOD)} of good '
                  f'recordings come back clean, and at most {pct(FALSE_REVIEW_BAD)} of untouched steps get yellow.')
    return ('<div class="note plain"><p><b>What this page answers.</b> If someone skips a step in a hands-on job, or '
            'does two steps in the wrong order, and it is on camera, does watchverify notice? (watchverify runs on Muse '
            'Spark, Meta\'s AI that understands video.) And does it leave good work alone?</p><p><b>How to read it.</b> Think of a spell-checker. A <b>red</b> mark is a firm call: "this '
            'step is missing" or "out of order". A <b>yellow</b> mark means "a person should look at this moment". '
            'No mark means it passed. A useful spell-checker underlines most typos and few correct words.</p>'
            f'<p><b>What happened</b> (I made the mistakes with code, so the right answer was known before it looked):</p>'
            '<ul>' + "".join(f"<li>{x}</li>" for x in lines) + f'</ul>{shop}{cant}<p class="muted">{lines_used}</p></div>')


LOOK_ROLES = {"removed": "removed step the check called seen", "swapped": "swapped step (there, moved)",
              "untouched": "untouched step (there)"}
LOOK_STATUSES = [("observed", "seen"), ("done_differently", "done another way"), ("unclear", "can't tell"),
                 ("not_observed", "not seen")]


def checker_labels(runs_root: Path, cuts: str) -> list[str]:
    """Every checker version with saved checks under these cuts, first checker first (repeats left out)."""
    labs = set()
    for d in bench.source_dirs(runs_root):
        for f in d.glob(f"{cuts}-*verify-correct.json"):
            tag = f.name[len(cuts) + 1:-len("verify-correct.json")].rstrip("-")
            if not re.fullmatch(r"(.+-)?r\d+", tag):
                labs.add(tag)
    return sorted(labs, key=lambda x: (x != "", x))


def first_pass_checker(runs_root: Path, cuts: str, lab: str) -> str | None:
    """The checker whose saved first passes a version reuses (bench.add_confirm records it), else None."""
    for d in bench.source_dirs(runs_root):
        f = d / f"{bench.trial_paths(d, cuts, 0, lab)[0]}verify-correct.json"
        if f.exists():
            src = json.loads(f.read_text()).get("_source", {}).get("first_pass_from")
            if src:
                return next((x for x in checker_labels(runs_root, cuts)
                             if f"{bench.trial_paths(d, cuts, 0, x)[0]}verify-correct" == src), src)
            return None
    return None


def deciders(rows: list[dict], kind: str) -> str:
    c = Counter(r["excluded_by"] for r in rows if r["truth"]["kind"] == kind and not r["graded"])
    return ", ".join(f"{n} decided by the {by}" if by != "code" else f"{n} by code" for by, n in c.most_common()) or "none"


def write(runs_root: Path, sources_file: Path, out: Path, baseline: Path | None = None, cuts: str = "midpoint",
          checker: str = "") -> Path:
    runs_root = Path(runs_root)
    abl = [(off, name, bench.rescore_results(runs_root, cuts=cuts, off=off, checker=checker)) for off, name in bench.ABLATIONS]
    with_t = abl[0][2]                          # every rule on; this call also leaves the saved checks scored so
    without_t = next(r for off, _, r in abl if off == ("timing",))
    base = json.loads(Path(baseline).read_text()) if baseline and Path(baseline).exists() else []
    sources = load_sources(sources_file)
    sids = sorted({r["sid"] for r in with_t}, key=lambda x: (list(sources).index(x) if x in sources else len(sources), x))
    sources = {sid: sources.get(sid, {"id": sid, "title": sid}) for sid in sids} | sources
    t = bench.tally(with_t)
    om, sw, co = t["omit"], t["swap"], t["correct"]
    co_nomarks = bench.tally(abl[1][2])["correct"]
    graded_v = om["graded"] + sw["graded"]
    marked = {d.name[len("bench-"):]: {st["index"] for st in json.loads((d / "reference.procedure.json").read_text())["steps"]
                                       if st.get("self_check", "observed") != "observed"} for d in bench.source_dirs(runs_root)}
    only_marked = sum(1 for r in with_t if r["graded"] and r.get("extras_review") and set(r["extras_review"]) <= marked[r["sid"]])
    tiles = [(f'{om.get("caught", 0)} of {om["graded"]}', f'removed steps caught (graded; {om["planted"]} planted)'),
             (str(om.get("flagged", 0)), "removed steps flagged for review"),
             (str(om.get("explained_away", 0)), "removed steps explained away (\"done another way\")"),
             (str(om.get("missed", 0)), "removed steps missed"),
             (str(om["planted"] - om["graded"]), f"removed steps not graded ({deciders(with_t, 'omit')})"),
             (f'{sw.get("caught", 0)} of {sw["graded"]}', f'swapped pairs caught (graded; {sw["planted"]} planted)'),
             (str(sw.get("flagged", 0)), "swaps flagged for review"), (str(sw.get("missed", 0)), "swaps missed"),
             (str(sw["planted"] - sw["graded"]), f"swaps not graded ({deciders(with_t, 'swap')})"),
             (f'{co.get("correct_pass", 0)} of {co["planted"]}',
              f'expert\'s clips passed when checked again ({co.get("flagged", 0)} sent to review, '
              f'{plural(co.get("false_alarm", 0), "false alarm")}; {plural(co_nomarks.get("false_alarm", 0), "false alarm")} '
              f'without the self-check marks)'),
             (f'{om["wrong_fail_elsewhere"] + sw["wrong_fail_elsewhere"]} of {graded_v}',
              "graded clips where an untouched step failed (reported missing or out of order)"),
             (f'{om["review_elsewhere"] + sw["review_elsewhere"]} of {graded_v}',
              f"graded clips where an untouched step was sent to review ({only_marked} of them only on a step the "
              f"self-check never found, which reads \"can't tell\" in every clip)")]
    tiles_html = "".join(f'<div class="tile"><b>{a}</b><span>{b}</span></div>' for a, b in tiles)

    def abl_row(name, res):
        k = bench.tally(res)
        cells = []
        for kind in ("omit", "swap"):
            cells += [str(k[kind].get("caught", 0)), str(k[kind].get("flagged", 0))] + \
                     ([str(k[kind].get("explained_away", 0))] if kind == "omit" else []) + [str(k[kind].get("missed", 0)), str(k[kind]["graded"])]
        cells += [str(k["omit"].get("not_checked", 0) + k["swap"].get("not_checked", 0))]
        cells += [str(k["omit"][x] + k["swap"][x]) for x in ("wrong_fail_elsewhere", "review_elsewhere")]
        cells += [str(k["correct"].get(o, 0)) for o in ("correct_pass", "flagged", "false_alarm")]
        return f'<tr><td>{e(name)}</td>' + "".join(f"<td>{x}</td>" for x in cells) + "</tr>"
    abl_html = "".join(abl_row(name, res) for _, name, res in abl)
    causes, looks = Counter(), {role: Counter() for role in LOOK_ROLES}
    for r in with_t:
        if not r["graded"] or r["outcome"] == "not_checked":
            continue
        pre_ = bench.trial_paths(runs_root / f"bench-{r['sid']}", cuts, 0, checker)[0]
        rd = runs_root / f"bench-{r['sid']}"
        ref_ = json.loads((rd / "reference.procedure.json").read_text())
        v = bench.load_check(rd / ("reference.selfcheck.json" if r["name"] == "selfcheck" else f"{pre_}verify-{r['name']}.json"),
                             ref_, bench.timing_model(rd, ref_))
        by = {c["reference_step"]: c for c in v["checks"]}
        for k in r.get("extras_review") or []:
            causes.update(by[k].get("reasons") or ["unrecorded"])
        for c in v["checks"]:
            if "confirm_look" in c:
                planted = c["reference_step"] in r["truth"]["steps"]
                role = {"omit": "removed", "swap": "swapped"}.get(r["truth"]["kind"]) if planted else "untouched"
                looks[role][c["confirm_look"]["status"]] += 1
    causes_html = "".join(f'<tr><td>{e(schema.REASONS.get(c, c))}</td><td>{n}</td></tr>' for c, n in causes.most_common())
    looks_html = ""
    if any(looks.values()):
        def look_row(role):
            k = looks[role]; n = sum(k.values())
            return (f'<tr><td>{e(LOOK_ROLES[role])}</td>' + "".join(f'<td>{k.get(s_, 0)}</td>' for s_, _ in LOOK_STATUSES) +
                    f'<td>{n}</td><td>{round(100 * k.get("not_observed", 0) / n) if n else 0}%</td></tr>')
        looks_html = (f'<h2>What the confirm look said</h2><p class="muted">The confirm look is a second look at the stretch '
                      f'where the check placed each step it called seen. A removed step the check called seen should come back '
                      f'"not seen"; a step that is really there should not. Only "not seen" sends a step to review. Over the '
                      f'graded clips:</p><table class="cmp"><tr><th>Step</th>' +
                      "".join(f'<th>{w}</th>' for _, w in LOOK_STATUSES) + '<th>looks</th><th>not seen</th></tr>' +
                      "".join(look_row(role) for role in LOOK_ROLES if looks[role]) + '</table>')

    def row(name, res, note=""):
        cells = []
        for kind in ("omit", "swap"):
            rs = [r for r in res if r["truth"]["kind"] == kind]
            c = Counter(r["outcome"] for r in rs)
            n = sum(r.get("graded", r["outcome"] not in ("untestable", "no_clean_cut")) for r in rs)   # older summaries lack it
            cells += [f'{c.get("caught", 0)}/{n}', str(c.get("flagged", 0)), str(c.get("missed", 0) + c.get("explained_away", 0))]
        return f'<tr><td>{name}<br><span class="muted" style="font-size:12px">{note}</span></td>' + "".join(f"<td>{x}</td>" for x in cells) + "</tr>"
    dell = lambda res: [r for r in res if r["sid"] == "dell3550"]
    cmp_rows = [row("Expert's seconds shown, plus SAM timing", base, "first source only (Dell); the version run first"),
                row("Seconds hidden", dell(without_t), "first source only, same clips"),
                row("Seconds hidden, plus SAM timing", dell(with_t), "first source only, same clips"),
                row("Seconds hidden", without_t, f"all {len(sids)} sources"),
                row("Seconds hidden, plus SAM timing", with_t, f"all {len(sids)} sources")] if base else \
               [row("Seconds hidden", without_t, f"all {len(sids)} sources"), row("Seconds hidden, plus SAM timing", with_t, f"all {len(sids)} sources")]
    cuts_note = ""
    if cuts == "labels":
        cmp_rows = [row(f"Person-confirmed cuts{', checker ' + e(checker) if checker else ''}", with_t, "every graded clip")]
        nv = [r for r in with_t if r["outcome"] in ("not_visible", "not_a_step")]
        ne = [r for r in with_t if r["outcome"] == "never_extracted"]
        n_lab, n_changed = label_changes(runs_root, sids)
        big = big_removals(runs_root, with_t, cuts)
        n_om = sum(1 for r in with_t if r["truth"]["kind"] == "omit" and r["graded"])
        cuts_note = (f'<div class="note"><b>How the mistakes are cut.</b> A person confirmed, from stills of the expert\'s '
                     f'clip ({e(", ".join(sorted({str(lab) for lab in labelers(runs_root, sids)})))}), where each step\'s hand '
                     f'work starts and ends, whether a camera shows it, and whether it is a real step of the task; a '
                     f'different AI model (not the one being tested) proposed the times from the stills, and the person changed {n_changed} of the {n_lab} steps\' proposed '
                     f'values; the labels were committed before any check. Mistakes planted on steps the person marked not '
                     f'visible or not real are not graded ({len(nv)}). Steps the person saw that the model never listed count '
                     f'as planted removals, not graded ({len(ne)}): the checker could never catch them. The model under test '
                     f'still wrote the step list and its descriptions; "step k removed" means the person-confirmed stretch of '
                     f'the model\'s step k. A removal also drops the in-between stretches on both sides of the step; where the '
                     f'model listed few steps those are long, and {len(big)} of the {n_om} graded removals took out more than '
                     f'30% of the clip.</div>')
    elif cuts == "refined":
        graded = {(r["sid"], r["name"]) for r in with_t if r["truth"]["kind"] in ("omit", "swap") and r["graded"]}
        same = lambda res: [r for r in res if (r["sid"], r["name"]) in graded and r["outcome"] != "not_checked"]
        old_all = bench.rescore_results(runs_root, cuts="midpoint")
        old = same(old_all)
        rep = same(bench.rescore_results(runs_root, cuts=cuts, rep=1))
        rep_keys = {(r["sid"], r["name"]) for r in rep}
        first = [r for r in with_t if (r["sid"], r["name"]) in rep_keys]
        cmp_rows = [row("Old cuts (the reference's midpoints), first checker", old, f"the same {len(graded)} clips")]
        for lab in checker_labels(runs_root, cuts):
            res = with_t if lab == checker else bench.rescore_results(runs_root, cuts=cuts, checker=lab)
            src = first_pass_checker(runs_root, cuts, lab)
            note = f"the same {len(graded)} clips" + (f"; checker {src or 'first'}'s first passes plus confirm looks"
                                                         if src is not None else "")
            cmp_rows.append(row(f"New cuts, {'checker ' + e(lab) if lab else 'first checker'}"
                                f"{' (this page)' if lab == checker else ''}", same(res), note))
        if checker:
            rep = []
        if rep:
            agree = sum(a["outcome"] == b["outcome"] for a in first for b in rep if (a["sid"], a["name"]) == (b["sid"], b["name"]))
            cmp_rows += [row("New cuts, first run", first, f"{len(rep)} clips (Dell and Acer)"),
                         row("New cuts, the same checker run again", rep,
                             f"same {len(rep)} clips; the planted step's outcome matched in {agree} of {len(rep)}")]
        old_by = {(r["sid"], r["name"]): r["outcome"] for r in old_all}
        ncc = [r for r in with_t if r["outcome"] == "no_clean_cut"]
        ncc_om = [r for r in ncc if r["truth"]["kind"] == "omit"]
        kept_om = [r for r in with_t if r["truth"]["kind"] == "omit" and r["graded"]]
        old_missed = lambda rs: sum(old_by.get((r["sid"], r["name"])) == "missed" for r in rs)
        opened = {(r["sid"], r["name"]): r for r in abl[[off for off, _, _ in abl].index(("selection",))][2]}
        ncc_seen = Counter(opened[(r["sid"], r["name"])]["outcome"] for r in ncc_om)
        seen_note = (f' Checked anyway by this checker, those {len(ncc_om)} removals were: caught {ncc_seen.get("caught", 0)}, '
                     f'flagged {ncc_seen.get("flagged", 0)}, missed {ncc_seen.get("missed", 0)}'
                     + (f', not checked {ncc_seen["not_checked"]}' if ncc_seen.get("not_checked") else "") + '.')
        cuts_note = (f'<div class="note"><b>How the mistakes are cut in this version.</b> Muse Spark looked at stills of '
                     f'the expert\'s clip, 4 per second around each step boundary, and named the last frame of one step '
                     f'and the first of the next. Between them is the in-between stretch: moving the tool, putting it down. '
                     f'A planted mistake keeps an in-between stretch only where its two steps are still neighbors, so a '
                     f'removed step leaves no tool resting at its place. Where Spark could not separate two steps even on a '
                     f'second, wider look, their planted mistakes are not graded ({len(ncc)} of '
                     f'{sum(1 for r in with_t if r["truth"]["kind"] in ("omit", "swap"))}). <b>That exclusion favors the '
                     f'checker:</b> the model under test decided it, and of the {len(ncc_om)} removals it left out, '
                     f'{old_missed(ncc_om)} had been missed under the earlier cuts, against {old_missed(kept_om)} of the '
                     f'{len(kept_om)} it kept.{seen_note if ncc_seen.get("not_checked", 0) < len(ncc_om) else ""}</div>')
    legend = "".join(f'<span><i style="background:{c}"></i>{w}</span>' for c, w in
                     [CELL[k] for k in ("observed", "not_observed", "out_of_order", "unclear", "shortened", "done_differently")])
    grids = []
    order = {"selfcheck": -1, "correct": 0, "omit": 1, "swap": 2}
    for sid in sids:
        s = sources[sid]
        res = sorted((r for r in with_t if r["sid"] == sid), key=lambda r: (order[r["truth"]["kind"]], r["truth"]["steps"]))
        pre = bench.trial_paths(runs_root / f"bench-{sid}", cuts, 0, checker)[0]
        grids.append(f'<h3>{e(s["title"].rsplit(".", 1)[0])}</h3>' + source_grid(runs_root / f"bench-{sid}", res, pre))
    credits = "<br>".join(f'"{e(s["title"])}" by {e(s.get("author", "see the registry"))}, {e(s.get("license", ""))}, '
                          f'Wikimedia Commons ({e(s.get("url", ""))})' for s in sources.values() if s["id"] in sids)
    n_checks = len([r for r in with_t if r["truth"]["kind"] in ("omit", "swap")])
    not_graded_why = ("the person marked the step not visible to a camera or not a real step, or removing it leaves no "
                      "footage (a clip's only step)." if cuts == "labels" else
                      "the checker did not find the step in the expert's own clip (self-check), the model could not separate "
                      "the two steps (no clean cut), or the cut that would remove a step misses the reference's own window "
                      "for it (its evidence frame stays in the clip).")
    sensors_off = bench.rescore_results(runs_root, cuts=cuts, off=("timing", "span"), checker=checker)
    plain = plain_words(with_t, sensors_off, untouched_steps(runs_root, with_t, cuts, checker))
    bench.rescore_results(runs_root, cuts=cuts, checker=checker)     # leave the saved checks scored as reported
    held = cuts == "labels" and any(bench.is_holdout(runs_root / f"bench-{sid}") for sid in sids)
    if held:
        head = (f'<h1>The exam: does it catch skipped steps in {len(sids)} videos it had never seen?</h1>\n'
                f'<p class="sub">I took {len(sids)} openly licensed how-to videos of hands-on jobs and planted {n_checks} '
                f'mistakes in copies of them with code (a step cut out, or two steps swapped), plus one untouched copy of '
                f'each. The videos were picked at random before I downloaded them, were never used while I built the '
                f'checker, and every copy was checked once. The record (which videos, when, what it cost) is in '
                f'bench/holdout.json{f"; checker version {e(checker)}" if checker else ""}.</p>\n'
                f'{plain}<div class="note"><b>What these numbers measure.</b> The cut points, and which planted mistakes are graded, '
                f'come from labels a person confirmed before any check, not from the model under test. The step list itself is '
                f'still Muse Spark\'s: every rate is of the steps the model listed. Two rules that send steps to a person read '
                f'model-made seconds (SAM timing, and the cut-short rule on the model\'s own seconds); the table below gives the '
                f'numbers with and without each.</div>')
    else:
        head = (f'<h1>Practice: how it did on the {len(sids)} videos I built it on</h1>\n'
                f'<p class="sub">The same test as the exam, on the {len(sids)} videos I used while building the checker: '
                f'{n_checks} mistakes planted with code (a step cut out, or two steps swapped), plus one untouched copy of '
                f'each. Because I tuned it on these, expect them to flatter it; the fair test is the exam on six videos it '
                f'never saw (results-holdout.html){f". Checker version {e(checker)}" if checker else ""}.</p>\n'
                f'{plain}<div class="note"><b>What these numbers measure.</b> The step boundaries that define each planted mistake, and '
                f'the calls on which mistakes are graded, come from Muse Spark, the same model that does the checking, not from '
                f'a person. So they measure the checker\'s consistency with its own reference, not accuracy against '
                f'human-verified truth. For the held-out set a person confirmed the boundaries and which steps a camera can show '
                f'before any check ran.</div>')
    body = f'''<main>{head}
<div class="note"><b>How the test works.</b> For each video, Muse Spark watched a 30 to 75 second stretch once and wrote the
step-by-step procedure (the reference). Then code cut new versions of the clip with one mistake each: one step removed, or
two neighboring steps swapped. Because code made the cuts, the planted mistake is known for every version, like an answer
key written before the exam. Each version was then checked against the reference without the checker knowing which mistake
it held. <b>Caught</b>: the checker named the planted mistake and failed the clip. <b>Flagged</b>: it sent the planted step
to a person (can't tell, cut short, or its two sensors disagreed). <b>Missed</b>: the planted step looked fine to it.
<b>Not graded</b>: left out of the "of N" with its reason and who decided, and still counted in "planted": {not_graded_why}
<b>Base rate:</b> "flagged" counts only mean something beside how often untouched steps are flagged too; the README
gives both per step. The SAM order rule is off in these numbers (it saw steps in the opposite order on an untouched
copy of the expert's own clip) and appears only as a with-it row below.</div>
{cuts_note}<div class="tiles">{tiles_html}</div>
<h2>Each rule that rests on another model output, switched off</h2>
<p class="muted">Five of the checker's rules use a model output other than the check itself. Each may only leave a step
as it was or send it to review, never pass a step the check failed or sent to review (a property test checks this on
3,000 random checks for each rule). Sending a failed step to review is still a softening, and the self-check marks also
leave mistakes out of the grading. <b>Self-check marks</b>: a step the checker did not find in the expert's own clip is reported
"can't tell", never missing, and a mistake planted on it is not graded. <b>Narration-only</b>: a checkpoint that is only
heard, never seen, is "can't tell". <b>SAM timing</b>: SAM 3.1 tracks the tool, and a small nearest-neighbor model fitted
on the expert's clip says which place belongs to which step; tracked seconds at a step's place can turn "missing" into
"can't tell" or send a step to review. Its labels are Spark's step seconds, so it is not independent of the reference,
and here every clip is cut from the expert's own footage with the same fixed camera, so SAM is measured in-sample: its
help on these clips may not carry over to a new performance. <b>Other moments</b>: the checker lists every other
moment it saw a step; two steps out of order that another listed moment would put in order go to review, not fail.
<b>Confirm looks</b>: a second look at the stretch where the check placed a step it called seen; "not seen" sends the
step to review. Every number, with and without each:</p>
<div class="wide"><table class="cmp"><tr><th>Rules</th><th>removed: caught</th><th>flagged</th><th>explained away</th><th>missed</th><th>graded</th><th>swapped: caught</th>
<th>flagged</th><th>missed</th><th>graded</th><th>never checked</th><th>untouched step failed</th><th>untouched step to review</th>
<th>expert's clip: passed</th><th>review</th><th>false alarm</th></tr>{abl_html}</table></div>
<p class="muted">The first row is the product as it runs; the others show how much each rule moves the numbers.
Switching a rule off re-scores the same observations: a check run without the self-check marks would also have taken a
second look at the steps they cover, which the saved run did not. "Never checked" counts planted mistakes with no saved
check; while it is above zero, the row without the clean-cut calls cannot show what those calls left out.</p>
{looks_html}
<h2>Why untouched steps were sent to review</h2>
<p class="muted">Every reason recorded on an untouched step that went to review, over the graded clips (a step can carry
more than one).</p>
<table class="cmp"><tr><th>Reason</th><th>steps</th></tr>{causes_html}</table>
<h2>Old cuts against new, and the same checker run twice</h2>
<table class="cmp"><tr><th>Checker version</th><th>removed: caught</th><th>flagged</th><th>missed or explained away</th><th>swapped: caught</th><th>flagged</th><th>missed</th></tr>{"".join(cmp_rows)}</table>
<h2>Every planted mistake</h2>
<p class="legend">{legend}<span><i style="outline:2px solid #1d2433;background:#fff"></i>planted step</span></p>
<p class="muted">One row per clip, one column per step. Hover a cell for the checker's reason.</p>
{"".join(grids)}
<h2>Limits of this test</h2>
<ul><li>Development set, model-made truth: see the first note. The held-out grading is the test that counts.</li>
<li>The cuts follow step boundaries the model drew from stills; where they are off by a frame or two, a removed step can
leave a trace behind, and a neighbor can lose an edge (which shows up as an untouched step sent to review).</li>
<li>A swapped clip has visible jumps (a cover back on after it came off). A real second performance would not.</li>
<li>The correct clips are the expert's own, which is easier than another person doing the task right.</li>
<li>About 30 to 45 graded mistakes per table means each rate is uncertain by roughly 15 points either way.</li></ul>
<footer>Footage: {credits}. Clips cut from them with ffmpeg.</footer></main>'''
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>watchverify accuracy test</title><style>{CSS}{EXTRA_CSS}</style></head><body>{body}</body></html>')
    Path(out).write_text(page)
    return Path(out)
