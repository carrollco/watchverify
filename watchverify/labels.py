"""Person-confirmed truth for the held-out set: stills of each clip, pre-labels (each step's working time and whether
a camera shows it, proposed from the stills by a model that is not under test, recorded as such), and a page on
which a person confirms or corrects every value. Only the page's confirm writes labels.json, with made_by
human:<name>; bench.load_labels refuses anything else, and a held-out grading refuses to run without it.

What feeds the labels, on purpose: the clip's stills (code) and each step's action and checkpoint text (the
reference's step list, the questions being asked). Never the reference's seconds or the model's boundary calls, so
the answer key does not lean on the model under test."""
import datetime, hashlib, hmac, html, json, re, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from pathlib import Path
from . import media

STILL_FPS = 2
STILL_WIDTH = 320
PAD_S = 3.0          # stills shown before and after a step's pre-labeled time


def e(x) -> str:
    return html.escape(str(x))


def stills(run_dir: Path, fps: float = STILL_FPS, width: int = STILL_WIDTH) -> list[tuple[float, Path]]:
    """Every still of the clip at fps, made once and reused (label-stills/, with an index of their times)."""
    out = Path(run_dir) / "label-stills"
    idx = out / "index.json"
    if idx.exists():
        return [(t, out / f) for t, f in json.loads(idx.read_text())]
    _, dur = media.count_frames_and_secs(Path(run_dir) / "clip.mp4")
    got = media.frames_between(Path(run_dir) / "clip.mp4", 0.0, dur, fps, out, width=width)
    idx.write_text(json.dumps([(t, p.name) for t, p in got]))
    return got


def steps_text(ref: dict) -> list[dict]:
    """The questions: each step's action and checkpoint, without any of the reference's seconds."""
    return [{"index": st["index"], "action": st["action"], "observable_checkpoint": st["observable_checkpoint"]}
            for st in ref["steps"]]


def overview_page(run_dir: Path) -> Path:
    """Every still with its time, and the steps as text: what the pre-labeler (a model not under test) looks at."""
    run_dir = Path(run_dir)
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    cells = "".join(f'<figure><img src="label-stills/{p.name}"><figcaption>{t:.1f} s</figcaption></figure>'
                    for t, p in stills(run_dir))
    steps = "".join(f'<li><b>{s["index"]}</b>: {e(s["action"])}. <i>{e(s["observable_checkpoint"])}</i></li>'
                    for s in steps_text(ref))
    page = run_dir / "label-overview.html"
    page.write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>stills</title><style>
body{{font:13px system-ui,sans-serif;background:#fff;color:#1d2433;margin:10px}}
.g{{display:grid;grid-template-columns:repeat(8,1fr);gap:4px}}figure{{margin:0}}img{{width:100%}}
figcaption{{font-weight:700;font-size:15px}}</style></head><body><ol start="0">{steps}</ol><div class="g">{cells}</div></body></html>''')
    return page


def write_prelabels(run_dir: Path, steps: list[dict], by: str) -> Path:
    """Save a model's proposal (not truth): per step start_s, end_s, visible, and a note on what it saw."""
    for i, st in enumerate(sorted(steps, key=lambda s: s["index"])):
        st.setdefault("is_step", True)
        assert st["index"] == i and st["start_s"] < st["end_s"] and isinstance(st["visible"], bool) \
            and isinstance(st["is_step"], bool), st
    p = Path(run_dir) / "prelabels.json"
    p.write_text(json.dumps({"made_by": by, "from": "the clip's stills and each step's action and checkpoint text",
                             "steps": sorted(steps, key=lambda s: s["index"])}, indent=1))
    return p


PAGE_CSS = """
body{font:15px/1.45 system-ui,sans-serif;background:#fff;color:#1d2433;margin:0}main{max-width:1180px;margin:0 auto;padding:18px}
.note{background:#f5f7fb;border-left:3px solid #3b6fd8;padding:8px 12px;margin:10px 0}
.step{border:1px solid #d9dee7;border-radius:8px;padding:10px 12px;margin:14px 0}.step h3{margin:0 0 4px}
.strip{display:flex;gap:4px;overflow-x:auto;padding:6px 0}.strip figure{margin:0;flex:0 0 200px;cursor:pointer;border:3px solid transparent}
.strip img{width:200px;display:block}.strip figcaption{font-size:12px;text-align:center}
.strip figure.in{border-color:#9cc2a6}.strip figure.start{border-color:#1e7b34}.strip figure.end{border-color:#b3261e}
.ctl{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.ctl input[type=number]{width:80px;font-size:15px}
button{font-size:16px;padding:8px 18px;border-radius:6px;border:1px solid #1e7b34;background:#e6f4ea;cursor:pointer}
.changed{color:#b3261e;font-weight:600}.muted{color:#5b6475;font-size:14px}#saved{font-weight:700;margin-left:12px}
"""

PAGE_JS = r"""
const steps = JSON.parse(document.getElementById('pre').textContent);
function mark(i){const s=document.getElementById('s'+i).valueAsNumber, en=document.getElementById('e'+i).valueAsNumber;
  document.querySelectorAll('#strip'+i+' figure').forEach(f=>{const t=+f.dataset.t;
    f.className = t===s ? 'start' : t===en ? 'end' : (t>s && t<en ? 'in' : '');});
  const p=steps[i], ch = s!==p.start_s || en!==p.end_s || document.getElementById('v'+i).checked!==p.visible
    || document.getElementById('r'+i).checked!==(p.is_step!==false);
  document.getElementById('c'+i).textContent = ch ? 'changed from the proposal' : '';}
function pick(i,t){const which=document.querySelector('input[name=w'+i+']:checked').value;
  document.getElementById(which+i).value=t; if(which==='s') document.querySelector('input[name=w'+i+'][value=e]').checked=true; mark(i);}
async function confirmAll(){const out=steps.map((p,i)=>({index:p.index,start_s:document.getElementById('s'+i).valueAsNumber,
  end_s:document.getElementById('e'+i).valueAsNumber,visible:document.getElementById('v'+i).checked,
  is_step:document.getElementById('r'+i).checked}));
  const missed=document.getElementById('missed').value.split('\n').map(x=>x.trim()).filter(x=>x);
  for(const s of out){ if(!(s.start_s<s.end_s)){alert('Step '+s.index+': the start must be before the end.');return;} }
  const tok=(document.querySelector('meta[name=label-token]')||{}).content||'';
  const r=await fetch('save',{method:'POST',headers:{'Content-Type':'application/json','X-Label-Token':tok},
    body:JSON.stringify({steps:out,missed_steps:missed})});
  document.getElementById('saved').textContent = r.ok ? 'Saved: '+(await r.text()) : 'Not saved: '+(await r.text());}
steps.forEach((_,i)=>mark(i));
"""


def confirm_page(run_dir: Path, title: str = "") -> Path:
    """The page a person confirms or corrects the pre-labels on; its button posts to serve()'s save."""
    run_dir = Path(run_dir)
    ref = json.loads((run_dir / "reference.procedure.json").read_text())
    pre = json.loads((run_dir / "prelabels.json").read_text())
    all_stills = stills(run_dir)
    blocks = []
    for i, (q, p) in enumerate(zip(steps_text(ref), pre["steps"])):
        near = [(t, f) for t, f in all_stills if p["start_s"] - PAD_S <= t <= p["end_s"] + PAD_S]
        strip = "".join(f'<figure data-t="{t}" onclick="pick({i},{t})"><img loading="lazy" src="label-stills/{f.name}">'
                        f'<figcaption>{t:.1f} s</figcaption></figure>' for t, f in near)
        blocks.append(f'''<div class="step"><h3>Step {q["index"]}: {e(q["action"])}</h3>
<div>Checkpoint: {e(q["observable_checkpoint"])}</div><div class="muted">Proposal note: {e(p.get("note", ""))}</div>
<div class="strip" id="strip{i}">{strip}</div>
<div class="ctl"><span>Clicking a still sets: <label><input type="radio" name="w{i}" value="s" checked> start</label>
<label><input type="radio" name="w{i}" value="e"> end</label></span>
<label>start <input type="number" step="0.5" id="s{i}" value="{p["start_s"]}" oninput="mark({i})"> s</label>
<label>end <input type="number" step="0.5" id="e{i}" value="{p["end_s"]}" oninput="mark({i})"> s</label>
<label><input type="checkbox" id="r{i}" {"checked" if p.get("is_step", True) else ""} onchange="mark({i})"> a real step of the task</label>
<label><input type="checkbox" id="v{i}" {"checked" if p["visible"] else ""} onchange="mark({i})"> a camera shows this step being done</label>
<span class="changed" id="c{i}"></span></div></div>''')
    body = f'''<main><h1>Confirm the step labels: {e(title or run_dir.name)}</h1>
<div class="note"><b>What this is for.</b> These labels are the answer key for the held-out accuracy test: where each
step's hand work starts and ends in this clip, and whether a camera shows it being done. Code cuts the test clips at
these times (a step removed, two steps swapped), so a wrong time here makes a wrong exam question. The proposal below was
made by a different AI model from the stills alone ({e(pre["made_by"])}); it is not the answer until you confirm it.</div>
<div class="note"><b>How.</b> For each step: <b>start</b> is the first still where the hands begin this step's work;
<b>end</b> is the last still where they are still doing it (moving to the next place or putting a tool down belongs to
neither step). Pick "start" or "end", then click a still to set it; green outline is the start, red the end. Untick "a camera shows" when the step cannot be seen being done (off camera, hidden, or only said); untick "a real step"
when the listed step does not happen in this clip or is not a step of the task at all (pointing, a graphic). Stills are {STILL_FPS} per second. When every
step looks right, press Confirm at the bottom; you can confirm again after a change, and the last confirm counts.</div>
{"".join(blocks)}
<div class="step"><h3>Steps that are not listed</h3><div>If the hands do a step of the task in this clip that none of the
steps above describes, write it here, one per line (what is done, and about when). The model wrote the list, so this is
how a step it missed gets counted.</div><textarea id="missed" rows="4" style="width:100%;font-size:15px"></textarea></div>
<p><button onclick="confirmAll()">Confirm these labels</button><span id="saved"></span></p>
<script type="application/json" id="pre">{json.dumps(pre["steps"]).replace("</", "<\\/")}</script><script>{PAGE_JS}</script></main>'''
    page = run_dir / "label.html"
    page.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
                    f'initial-scale=1"><title>Confirm labels</title><style>{PAGE_CSS}</style></head><body>{body}</body></html>')
    return page


def save_confirmed(run_dir: Path, steps: list[dict], who: str, missed_steps: list[str] | None = None) -> dict:
    """Write labels.json from a person's confirm: their values, who they are, when, the proposal they saw (by
    digest) and what they changed from it."""
    run_dir = Path(run_dir)
    pre_bytes = (run_dir / "prelabels.json").read_bytes()
    pre = json.loads(pre_bytes)
    n = len(pre["steps"])
    steps = sorted(steps, key=lambda s: s["index"])
    if [s["index"] for s in steps] != list(range(n)):
        raise ValueError(f"expected steps 0 to {n - 1}")
    clean = [{"index": s["index"], "start_s": float(s["start_s"]), "end_s": float(s["end_s"]), "visible": bool(s["visible"]),
              "is_step": bool(s.get("is_step", True))} for s in steps]
    for s in clean:
        if not s["start_s"] < s["end_s"]:
            raise ValueError(f"step {s['index']}: start must be before end")
    changed = [s["index"] for s, p in zip(clean, pre["steps"])
               if (s["start_s"], s["end_s"], s["visible"], s["is_step"]) != (p["start_s"], p["end_s"], p["visible"], p.get("is_step", True))]
    d = {"made_by": f"human:{who}", "confirmed_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
         "prelabeled_by": pre["made_by"], "prelabels_sha256": hashlib.sha256(pre_bytes).hexdigest(),
         "changed_from_prelabels": changed, "missed_steps": [str(x) for x in (missed_steps or [])], "steps": clean}
    (run_dir / "labels.json").write_text(json.dumps(d, indent=1))
    return d


SID_DIR = re.compile(r"bench-[A-Za-z0-9][A-Za-z0-9._-]*")
STILL_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.jpg")
MAX_BODY = 1 << 20


def make_server(root: Path, port: int, who: str, token: str) -> ThreadingHTTPServer:
    """The label server: on 127.0.0.1 only; answers only when the Host (and any Origin) is this server, so another
    site cannot read it or post to it through a browser (DNS rebinding, forged forms); serves only the label pages
    and stills, never a directory listing or any other file; a save needs the token embedded in the page this
    server sent, a JSON body (which a browser will not send cross-site without a preflight this server refuses)
    and at most 1 MiB. The only writer of labels.json."""
    root = Path(root).resolve()
    hosts: set[str] = set()              # filled once the port is bound (port 0 picks a free one)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def _from_here(self) -> bool:
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in hosts and (origin is None or origin in {f"http://{h}" for h in hosts})

        def _parts(self) -> list[str]:
            return urlsplit(self.path).path.strip("/").split("/")

        def do_GET(self):
            if not self._from_here():
                return self._send(403, b"forbidden")
            parts = self._parts()
            if len(parts) == 2 and SID_DIR.fullmatch(parts[0]) and parts[1] in ("label.html", "label-overview.html"):
                f = root / parts[0] / parts[1]
                if not f.is_file():
                    return self._send(404, b"not found")
                page = f.read_text()
                if parts[1] == "label.html":
                    page = page.replace("<head>", f'<head><meta name="label-token" content="{token}">', 1)
                return self._send(200, page.encode(), "text/html; charset=utf-8")
            if len(parts) == 3 and SID_DIR.fullmatch(parts[0]) and parts[1] == "label-stills" and STILL_FILE.fullmatch(parts[2]):
                f = root / parts[0] / parts[1] / parts[2]
                return self._send(200, f.read_bytes(), "image/jpeg") if f.is_file() else self._send(404, b"not found")
            return self._send(404, b"not found")

        def do_POST(self):
            if not self._from_here():
                return self._send(403, b"forbidden")
            if not hmac.compare_digest(self.headers.get("X-Label-Token", ""), token):
                return self._send(403, b"missing or wrong page token: reload the page from this server")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._send(415, b"JSON only")
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_BODY:
                return self._send(413, b"body too large or empty")
            parts = self._parts()
            if not (len(parts) == 2 and SID_DIR.fullmatch(parts[0]) and parts[1] == "save"
                    and (root / parts[0] / "prelabels.json").is_file()):
                return self._send(404, b"no such source")
            try:
                body = json.loads(self.rfile.read(n))
                d = save_confirmed(root / parts[0], body["steps"], who, body.get("missed_steps"))
            except (ValueError, KeyError, TypeError) as ex:
                return self._send(400, str(ex).encode())
            self._send(200, f"{len(d['steps'])} steps, {len(d['changed_from_prelabels'])} changed, at {d['confirmed_at']}".encode())

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    hosts.update({f"127.0.0.1:{srv.server_address[1]}", f"localhost:{srv.server_address[1]}"})
    return srv


def serve(root: Path, port: int, who: str) -> None:
    """Serve the confirm pages of every source under root until stopped (make_server)."""
    make_server(root, port, who, secrets.token_urlsafe(24)).serve_forever()
