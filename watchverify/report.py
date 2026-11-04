"""One self-contained HTML page per run: the reference procedure with its evidence (frames with tracked boxes,
a timeline of steps, tracks and speech), every verification in the run with its evidence frames, and the cost
from the ledger. Light theme, images inlined, no scripts, so the file can be opened or sent as it is."""
import base64, html, json
from pathlib import Path
from . import media, schema
from .ledger import Ledger

STATUS_WORDS = {"observed": ("seen", "ok"), "not_observed": ("missing", "bad"), "unclear": ("can't tell", "warn"),
                "done_differently": ("done another way", "warn")}
VISIBILITY_WORDS = {"clear": "clearly visible", "subtle": "subtle", "narration_only": "narration only"}
VERDICT_WORDS = {"pass": ("PASS", "ok"), "fail": ("FAIL", "bad"), "review": ("NEEDS REVIEW", "warn")}

CSS = """
:root{--ink:#1d2433;--muted:#5b6475;--line:#d9dee7;--bg:#ffffff;--panel:#f6f8fb;--ok:#1b7f3b;--bad:#b42318;--warn:#a15c00;--accent:#1f5fbf}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 24px 60px}h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 10px}
.sub{color:var(--muted);margin:0 0 18px}.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:150px}
.tile b{display:block;font-size:20px}.tile span{color:var(--muted);font-size:13px}
.badge{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px;font-weight:600;border:1px solid}
.ok{color:var(--ok);border-color:var(--ok)}.bad{color:var(--bad);border-color:var(--bad)}.warn{color:var(--warn);border-color:var(--warn)}
.muted{color:var(--muted)}.steps{display:grid;grid-template-columns:1fr;gap:14px}
.step{display:grid;grid-template-columns:340px 1fr;gap:16px;border:1px solid var(--line);border-radius:8px;padding:12px;background:#fff}
.step img{width:100%;border-radius:4px;border:1px solid var(--line)}.step h3{margin:0 0 6px;font-size:16px}
dl{margin:0;display:grid;grid-template-columns:130px 1fr;gap:3px 10px;font-size:14px}dt{color:var(--muted)}dd{margin:0}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{background:var(--panel);font-weight:600}td img{width:200px;border-radius:4px;border:1px solid var(--line)}
.verdict{font-size:18px;font-weight:700}.note{background:var(--panel);border-left:3px solid var(--accent);padding:8px 12px;margin:10px 0;font-size:14px}
svg text{font:12px system-ui,sans-serif;fill:var(--ink)}footer{margin-top:40px;color:var(--muted);font-size:13px}
"""


def _img(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def e(x) -> str:
    return html.escape(str(x))


def timeline(proc: dict, grounding: dict | None, duration: float, width: int = 1040) -> str:
    """Steps, tracked phrases and speech turns on one time axis."""
    left, right = 170, 20
    sx = lambda t: left + (width - left - right) * (t / duration if duration else 0)
    rows, y = [], 26
    out = [f'<svg viewBox="0 0 {width} {{H}}" width="100%" role="img" aria-label="timeline">']
    for s in range(0, int(duration) + 1, 5 if duration > 15 else 1):
        out.append(f'<line x1="{sx(s):.1f}" y1="16" x2="{sx(s):.1f}" y2="{{B}}" stroke="#eef1f5"/>'
                   f'<text x="{sx(s):.1f}" y="12" text-anchor="middle" fill="#5b6475">{s}s</text>')
    out.append(f'<text x="0" y="{y + 14}">steps</text>')
    for st in proc["steps"]:
        vis = st.get("checkpoint_visibility", "clear")
        fill = {"clear": "#1f5fbf", "subtle": "#7ea6e0", "narration_only": "#c4cbd6"}.get(vis, "#1f5fbf")
        x0, x1 = sx(st["start_s"]), sx(st["end_s"])
        out.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(x1 - x0 - 2, 2):.1f}" height="20" rx="3" fill="{fill}">'
                   f'<title>step {st["index"]}: {e(st["action"])} ({VISIBILITY_WORDS.get(vis, vis)})</title></rect>'
                   f'<text x="{x0 + 5:.1f}" y="{y + 14}" fill="#fff">{st["index"]}</text>')
    y += 32
    if grounding:
        fps = grounding["track_fps"]
        for ph in grounding["phrases"]:
            color = "#" + grounding["colors"][ph]
            out.append(f'<text x="0" y="{y + 11}">{e(ph[:24])}</text>')
            for b in grounding["tracks"].get(ph, []):
                if b["t"] is not None and (b.get("confidence") is None or b["confidence"] >= 0.4):
                    out.append(f'<rect x="{sx(b["t"]):.1f}" y="{y}" width="{max(sx(1 / fps) - sx(0) - 0.5, 1):.1f}" height="14" fill="{color}"/>')
            y += 22
        if grounding.get("turns"):
            out.append(f'<text x="0" y="{y + 11}">speech</text>')
            for t in grounding["turns"]:
                x0, x1 = sx(t["startMs"] / 1000), sx(t["endMs"] / 1000)
                out.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(x1 - x0, 2):.1f}" height="14" rx="3" fill="#e9d8a6">'
                           f'<title>{e(t["transcript"])}</title></rect>')
            y += 22
    out.append("</svg>")
    return "".join(out).replace("{H}", str(y + 6)).replace("{B}", str(y))


def step_cards(proc: dict, grounding: dict | None, run_dir: Path) -> str:
    g_steps = {s["index"]: s for s in (grounding or {}).get("steps", [])}
    cards = []
    for st in proc["steps"]:
        g = g_steps.get(st["index"], {})
        img = f'<img src="{_img(run_dir / g["frame"])}" alt="evidence frame for step {st["index"]}">' if g.get("frame") else '<div class="muted">no frame</div>'
        vis = st.get("checkpoint_visibility")
        vis_badge = f' <span class="badge {"ok" if vis == "clear" else "warn"}">{VISIBILITY_WORDS.get(vis, vis)}</span>' if vis else ""
        objs = []
        for o in st["objects"]:
            tr = g.get("tracks", {}).get(o)
            if tr is not None and grounding:
                objs.append(f'<span class="dot" style="background:#{grounding["colors"][o]}"></span>{e(o)} '
                            f'<span class="muted">(tracked in {tr["frames"]} of {tr["window_frames"]} frames)</span>')
            else:
                objs.append(e(o))
        speech = "<br>".join(f'<span class="muted">{x["start_s"]:.1f}s</span> "{e(x["text"])}"' for x in g.get("speech", []))
        when = f'{st["start_s"]:.1f} to {st["end_s"]:.1f} s' + (f', frame at {g["evidence_s"]:.1f} s' if g else "")
        cards.append(f'''<div class="step"><div>{img}</div><div><h3>Step {st["index"]}: {e(st["action"])}</h3>
<dl><dt>When</dt><dd>{when}</dd><dt>Checkpoint</dt><dd>{e(st["observable_checkpoint"])}{vis_badge}</dd>
<dt>Pass condition</dt><dd>{e(st["pass_condition"])}</dd><dt>Camera can't see</dt><dd>{e(st["cannot_see"])}</dd>
<dt>Objects</dt><dd>{"<br>".join(objs)}</dd>{f"<dt>Speech</dt><dd>{speech}</dd>" if speech else ""}</dl></div></div>''')
    return '<div class="steps">' + "".join(cards) + "</div>"


def verification_section(proc: dict, v: dict, vname: str, run_dir: Path) -> str:
    steps = {s["index"]: s for s in proc["steps"]}
    video = Path(v.get("_source", {}).get("video", ""))
    have_video = video.is_file()
    _, dur = media.count_frames_and_secs(video) if have_video else (0, 0.0)
    word, cls = VERDICT_WORDS.get(v["verdict"], (v["verdict"], "warn"))
    reasons = []
    if v.get("missing_steps"): reasons.append("missing: step " + ", ".join(map(str, v["missing_steps"])))
    if v.get("out_of_order_steps"): reasons.append("out of order: steps " + ", ".join(map(str, v["out_of_order_steps"])))
    if v.get("unclear_steps"): reasons.append("can't tell from the video: step " + ", ".join(map(str, v["unclear_steps"])))
    if v.get("shortened_steps"): reasons.append("cut short: step " + ", ".join(map(str, v["shortened_steps"])))
    if v.get("disputed_steps"): reasons.append("seen only on a second look: step " + ", ".join(map(str, v["disputed_steps"])))
    rows = []
    for c in v["checks"]:
        i = c["reference_step"]
        label, lcls = STATUS_WORDS.get(c["status"], (c["status"], "warn"))
        if c.get("out_of_order"):
            label, lcls = "out of order", "bad"
        elif c.get("shortened"):
            label, lcls = "cut short", "warn"
        elif c.get("disputed"):
            label, lcls = "seen on 2nd look", "warn"
        when = f'{c["observed_start_s"]:.1f} to {c["observed_end_s"]:.1f} s' if c["status"] in schema.PRESENT else "n/a"
        thumb = ""
        if have_video:
            look = c.get("second_look")
            if c["status"] in schema.PRESENT:
                t, cap = c["observed_start_s"] + min(1.0, (c["observed_end_s"] - c["observed_start_s"]) / 2), "seen here"
            elif look:
                t, cap = look["window_offset_s"] + 0.5, "where it should be (searched here)"
            else:
                t, cap = None, ""
            if t is not None:
                f = media.frame_at(video, min(max(t, 0), max(dur - 0.1, 0)), run_dir / "frames" / f"{vname}-step{i}.jpg", width=400)
                thumb = f'<img src="{_img(f)}" alt="candidate frame for step {i}"><div class="muted">{cap}, {t:.1f} s</div>'
        evidence = e(c["evidence"])
        if c.get("status_reason"):
            evidence += f'<br><span class="muted">{e(c["status_reason"])}</span>'
        rows.append(f'<tr><td>{i}</td><td>{e(steps[i]["action"]) if i in steps else ""}</td>'
                    f'<td><span class="badge {lcls}">{label}</span></td><td>{when}</td><td>{evidence}</td>'
                    f'<td>{e(c["cannot_see"])}</td><td>{thumb}</td></tr>')
    extras = "".join(f'<li>{a["start_s"]:.1f} to {a["end_s"]:.1f} s: {e(a["action"])}</li>' for a in v.get("extra_actions", []))
    title = "Self-check: the expert's own video against its procedure" if vname.endswith("selfcheck") else f"Check: {e(video.name or vname)}"
    return f'''<h2>{title}</h2>
<p><span class="verdict badge {cls}">{word}</span> <span class="muted">{e("; ".join(reasons) or "every step seen, in order")}</span></p>
<table><tr><th>Step</th><th>Expected</th><th>Result</th><th>Seen at</th><th>Evidence</th><th>Camera can't see</th><th>Frame</th></tr>{"".join(rows)}</table>
{f"<p><b>Actions not in the reference:</b></p><ul>{extras}</ul>" if extras else ""}
{f'<div class="note">{e(v["notes"])}</div>' if v.get("notes") else ""}'''


def write_report(run_dir: Path, name: str = "reference", out: Path | None = None, only: list[str] | None = None,
                 credit: str | None = None) -> Path:
    """only: the verification files (by stem) to show, in that order; the cost line then covers just the calls
    that made the reference and those checks, found by their ledger key prefix."""
    run_dir = Path(run_dir)
    proc = json.loads((run_dir / f"{name}.procedure.json").read_text())
    gp = run_dir / f"{name}.grounding.json"
    grounding = json.loads(gp.read_text()) if gp.exists() else None
    duration = grounding["seconds"] if grounding else max(s["end_s"] for s in proc["steps"])
    verifs = []
    for p in sorted(run_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and "checks" in d and "verdict" in d and (only is None or p.stem in only):
            verifs.append((p.stem, d))
    if only is not None:
        missing = set(only) - {vn for vn, _ in verifs}
        if missing:
            raise SystemExit(f"no saved verification named {', '.join(sorted(missing))} in {run_dir}")
        verifs.sort(key=lambda vd: only.index(vd[0]))
    ledger = Ledger(run_dir / "ledger.jsonl")
    by_ep: dict[str, float] = {}
    prefixes = None if only is None else tuple(f"{k}." for k in [name, "scout", *only])
    live = [x for x in ledger.entries() if x.get("live", True) and (prefixes is None or x["key"].startswith(prefixes))]
    total = sum(x["cost_usd"] for x in live)
    for x in live:
        by_ep[x["endpoint"]] = by_ep.get(x["endpoint"], 0) + x["cost_usd"]
    meta_p = run_dir / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    tiles = [(len(proc["steps"]), "steps"), (len(grounding["phrases"]) if grounding else 0, "objects tracked by SAM 3.1"),
             (f'{duration:.0f} s', "reference video")]
    for vn, v in verifs:
        label = "self-check, the expert's video" if vn.endswith("selfcheck") else e(Path(v.get("_source", {}).get("video", vn)).name)
        tiles.append((VERDICT_WORDS.get(v["verdict"], (v["verdict"],))[0], label))
    tiles.append((f"${total:.3f}", f"Meta API cost, {len(live)} calls"))
    tiles_html = "".join(f'<div class="tile"><b>{t}</b><span>{l}</span></div>' for t, l in tiles)
    legend = ""
    if grounding:
        legend = " ".join(f'<span class="dot" style="background:#{c}"></span>{e(p)}' for p, c in grounding["colors"].items())
    cost = ", ".join(f"{k} ${v:.3f}" for k, v in sorted(by_ep.items(), key=lambda kv: -kv[1]))
    body = f'''<main><h1>{e(proc["task"])}</h1>
<p class="sub">Procedure extracted from one video by Muse Spark, grounded with SAM 3.1 tracks{" and Voice Transcribe" if grounding and grounding.get("turns") else ""}. Run <code>{e(run_dir.name)}</code>.</p>
<div class="tiles">{tiles_html}</div>
<h2>Timeline</h2>{timeline(proc, grounding, duration)}
<p class="muted">Step bars: dark when the checkpoint is clearly visible, light when subtle, grey when known only from narration. {legend}</p>
<h2>Procedure</h2>{step_cards(proc, grounding, run_dir)}
{"".join(verification_section(proc, v, vn, run_dir) for vn, v in verifs)}
<h2>What it cost</h2><p>${total:.4f} at Meta's published rates ({e(cost)}), from the run's ledger.</p>
<footer>{e(credit or meta.get("footage", ""))}</footer></main>'''
    page = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(proc["task"])}</title><style>{CSS}</style></head><body>{body}</body></html>'
    out = Path(out) if out else run_dir / "report.html"
    out.write_text(page)
    return out
