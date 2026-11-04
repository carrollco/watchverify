"""Builds the demo video from saved runs and the committed pages: no model calls, no network.

The video is data: SCENES below, each a narration line and one visual (a title card, clips from the
test footage, or a slow pan over a rendered page). Narration is spoken by a local voice (piper), captions
are burned in from the same text, and every scene lasts as long as its narration. Edit a line, re-run,
and the timing, captions and audio follow.

    python demo/build_video.py --voice tmp/voices/kokoro --speaker af_heart --pace 1.08 --out tmp/video/watchverify-demo.mp4

Needs: playwright with Chromium (cards and page pans), piper-tts and a voice model, imageio-ffmpeg.
Inputs it reads: docs/demo-acer15.html and the Acer clips under runs/bench-acer15
(made by `bench-prepare acer15` and `bench-run acer15`; not committed, being video).
"""
import argparse, asyncio, html, json, math, re, shutil, subprocess, wave
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
FF = imageio_ffmpeg.get_ffmpeg_exe()
BAND = 150                                         # caption strip height, px, below the picture
W, H, FPS, SCALE = 1920, 1080, 30, 1.5          # pages render at 1280 CSS px wide, 1.5x, so 1920 px
CSS_W, CSS_H = int(W / SCALE), int(H / SCALE)
RUN = ROOT / "runs" / "bench-acer15"
EXPERT, OMIT3, SWAP01 = RUN / "clip.mp4", RUN / "variants-refined" / "omit3.mp4", RUN / "variants-refined" / "swap01.mp4"
DEMO, RESULTS = ROOT / "docs" / "demo-acer15.html", ROOT / "docs" / "results.html"
REPO = "github.com/carrollco/watchverify"
CREDIT = ("Footage: \"How to open Acer Aspire 15 (A15-41M) - disassembly and upgrade options\" by LaptopMedia, "
          "Wikimedia Commons, CC BY 3.0. Shortened, and cut into versions with a step removed or two steps swapped.")

# One scene per entry. visual kinds: card (title, lines), clips (one or two clips side by side, each
# [file, start_s, end_s, label]), pan (page, from heading, to heading). Narration is spoken and captioned.
SCENES = [
    {"say": "In January 2024, a door blew off a plane in mid-air. During a repair, someone had taken out four bolts "
            "and never put them back. Nobody noticed, because a finished job looks the same whether every step was "
            "done or not.",
     "card": {"title": "A skipped step leaves no trace", "lines": [
         "Alaska Airlines flight 1282, January 2024: a door plug blew out in flight.",
         "Four bolts had been taken out during a repair and never put back (NTSB report AIR-25-04)."]}},
    {"say": "Plenty of hands-on work already gets filmed: repairs, assembly, lab work. But nobody has time to watch "
            "it all. So I built watchverify. You film an expert doing the job once. After that, it checks every "
            "new recording of that job and points you to any step it couldn't find.",
     "card": {"title": "watchverify: watch once, then verify", "lines": [
         "1. Film an expert doing the job once.",
         "2. AI turns that video into a checklist of steps you can see on camera.",
         "3. Every new recording gets checked against it, with the exact moment to look at."]}},
    {"say": "Here's the expert taking a laptop apart. Meta's Muse Spark AI watches it, picture and sound together, "
            "and writes down each step, and what you'd see on camera if that step was really done.",
     "clips": [[EXPERT, 0.0, 58.0, "The expert's video (sped up)"]]},
    {"say": "It found ten steps. A second Meta model, called SAM, follows each tool and part through the video, so "
            "every step gets a time and a picture.",
     "pan": {"page": DEMO, "from": "h2:Procedure", "to": "h2:Procedure", "width": 840}},
    {"say": "Some things a camera just can't prove, like whether the clips inside are damaged. Instead of guessing, "
            "it says so.",
     "pan": {"page": DEMO, "from": "h3:Step 0", "to": "h3:Step 1", "width": 840}},
    {"say": "First it checks the expert's own video. If it can't see a step even there, it won't blame the next "
            "person for it.",
     "pan": {"page": DEMO, "from": "h2:Self-check", "to": "h2:Self-check", "down": 150, "width": 840}},
    {"say": "Now a second recording, with one step cut out. On the left, the expert pries open the front edge. "
            "On the right, that never happens.",
     "clips": [[EXPERT, 9.0, 21.0, "The expert"], [OMIT3, 9.0, 21.0, "Same job, step 3 cut out"]]},
    {"say": "It flags step three as missing, and shows where it looked. It also wrongly flags two steps that were "
            "fine. False alarms like that are its biggest weakness.",
     "pan": {"page": DEMO, "from": "h2:Check: omit3", "to": "tr:3", "width": 840}},
    {"say": "Here, two steps are done in the wrong order. It catches that too.",
     "clips": [[EXPERT, 0.0, 7.5, "The expert: left corner, then right"],
               [SWAP01, 0.0, 7.5, "Wrong order: right corner, then left"]]},
    {"say": "So does it work? I tested it on six videos it had never seen. Code cut steps out, so the right answers "
            "were known before it looked. Out of 26 missing steps, it flagged 21. It called 8 missing outright, and for 13 "
            "it said a person should look. Five got past it. And about one in seven steps that were fine got "
            "flagged anyway. So it won't replace an inspector. It tells a supervisor which recordings to watch, "
            "and exactly where to look.",
     "pace": 1.15,
     "chart": {"title": "Six videos it had never seen", "rows": [
         ["A step cut out", 26, [("caught", 8, "good"), ("a person should look", 13, "warning"),
                                 ("got past it", 5, "critical")]],
         ["Two steps swapped", 19, [("caught", 7, "good"), ("a person should look", 7, "warning"),
                                    ("got past it", 5, "critical")]],
         ["Nothing changed", 6, [("passed", 5, "good"), ("a person should look", 1, "warning")]]],
      "note": "Steps that were fine got a \"person should look\" about 1 time in 7. Every number: the README."}},
    {"say": "I built the test so it couldn't flatter my checker. The answers were locked in before it ran, the AI "
            "never saw them, and every answer it gave is saved, so anyone can check my numbers. It also showed me a "
            "real blind spot. The AI tends to count a step as done just because the result is on screen, like a "
            "cover that's already off.",
     "card": {"title": "A test that can't flatter it", "lines": [
         "Mistakes made by cutting the video, so the right answers exist up front.",
         "The AI never sees the answers, or even the file names.",
         "Six test videos picked at random, each checked once.",
         "Every AI answer saved: anyone can re-check the numbers.",
         "Blind spot found: a step counts as done when its result is on screen."]}},
    {"say": "It all runs on Meta's AI. Muse Spark watches the video, SAM follows the tools, and Muse Voice "
            "Transcribe writes down what the expert says. A check costs about nine cents.",
     "card": {"title": "Built on Meta's AI", "lines": [
         "Muse Spark 1.3: watches the video with its sound and writes the checklist.",
         "SAM 3.1: follows each tool and part, for step times and pictures.",
         "Muse Voice Transcribe: writes down what the expert says, with times.",
         "About 9 cents per check, with a hard spending cap."]}},
    {"say": "Next, I want it to tell one bolt from another, so a missing bolt like that one gets caught. "
            "watchverify: watch once, then verify.",
     "card": {"title": "watchverify", "lines": [f"Code, results and every number: {REPO}",
                                                "Built during the Meta AI hackathon, October to November 2026.",
                                                "Next: telling one bolt from another."],
              "foot": CREDIT}},
]

CARD_CSS = """
*{box-sizing:border-box}body{margin:0;width:1280px;height:720px;background:#ffffff;color:#1d2433;
font-family:'DejaVu Sans',system-ui,sans-serif;display:flex;flex-direction:column;justify-content:center;padding:0 90px}
h1{font-size:46px;margin:0 0 26px;line-height:1.15}.accent{width:90px;height:6px;background:#1f5fbf;margin-bottom:26px}
p{font-size:24px;line-height:1.45;margin:0 0 12px;color:#2b3445}.foot{margin-top:28px;font-size:14px;color:#5b6475}
.chart h1{font-size:32px}.row{display:grid;grid-template-columns:190px 1fr;align-items:center;gap:18px;margin:0 0 30px}
.row b{font-size:21px}.row b small{display:block;font-size:15px;font-weight:400;color:#5b6475}
.bar{display:flex;gap:2px;height:46px}.seg{border-radius:0;min-width:4px}.seg:first-child{border-radius:4px 0 0 4px}
.seg:last-child{border-radius:0 4px 4px 0}.labels{display:flex;gap:2px;margin-top:6px;font-size:16px;color:#1d2433}
.labels div{overflow:visible;white-space:nowrap}.note{font-size:20px;color:#3b4455;margin-top:10px}
.legend{display:flex;gap:22px;font-size:16px;margin:0 0 26px 208px;color:#1d2433}.legend i{display:inline-block;width:14px;
height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}
"""
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
PAN_CSS_W = 1120                                   # pages pan at this width so their 1100 px column fills the frame


def chart_html(c: dict) -> str:
    """Horizontal 100% bars, one per row, segments in the fixed status colors, each labeled with its word and count."""
    seen, legend = [], ""
    for _, _, segs in c["rows"]:
        for word, _, tone in segs:
            if (word, tone) not in seen:
                seen.append((word, tone))
    legend = "".join(f'<span><i style="background:{STATUS[t]}"></i>{html.escape(w)}</span>' for w, t in seen)
    rows = ""
    for name, n, segs in c["rows"]:
        bar = "".join(f'<div class="seg" style="flex:{k};background:{STATUS[t]}"></div>' for _, k, t in segs)
        lab = "".join(f'<div style="flex:{k}">{k}{" " + html.escape(w) if k / n >= 0.12 else ""}</div>' for w, k, _ in segs)
        rows += f'<div class="row"><b>{html.escape(name)}<small>{n} tests</small></b><div><div class="bar">{bar}</div><div class="labels">{lab}</div></div></div>'
    return (f'<div class="chart"><div class="accent"></div><h1>{html.escape(c["title"])}</h1><div class="legend">{legend}</div>'
            f'{rows}<div class="note">{html.escape(c["note"])}</div></div>')


LABEL_CSS = """*{margin:0}body{width:1280px;height:720px;background:transparent;font-family:'DejaVu Sans',sans-serif}
.l{position:absolute;top:%dpx;left:%dpx;background:#ffffff;color:#1d2433;font-size:20px;font-weight:600;padding:6px 12px;
border-radius:6px;border:1px solid #d9dee7}"""


def run(*args):
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


SAY_AS = {"watchverify": "watch verify"}      # how the voice should say a word; captions keep the written form


def speak(voice_path: Path, scenes: list, work: Path, pace: float = 1.0, speaker: str = "af_heart") -> list[float]:
    """One WAV per scene; returns each scene's spoken length in seconds. pace below 1 speaks faster; a scene's own
    "pace" overrides it. voice_path is a Kokoro folder (kokoro-v1.0.onnx and voices-v1.0.bin, Apache 2.0) or a
    piper voice model (.onnx)."""
    texts = []
    for sc in scenes:
        text = sc["say"]
        for word, said in SAY_AS.items():
            text = text.replace(word, said)
        texts.append((text, sc.get("pace", pace)))
    lengths = []
    if Path(voice_path).is_dir():
        import numpy as np
        from kokoro_onnx import Kokoro
        k = Kokoro(str(Path(voice_path) / "kokoro-v1.0.onnx"), str(Path(voice_path) / "voices-v1.0.bin"))
        for i, (text, sc_pace) in enumerate(texts):
            samples, rate = k.create(text, voice=speaker, speed=1.0 / sc_pace, lang="en-us")
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            with wave.open(str(work / f"say{i:02d}.wav"), "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate); wf.writeframes(pcm)
            lengths.append(len(samples) / rate)
        return lengths
    from piper import PiperVoice, SynthesisConfig
    voice = PiperVoice.load(str(voice_path))
    for i, (text, sc_pace) in enumerate(texts):
        out = work / f"say{i:02d}.wav"
        with wave.open(str(out), "wb") as wf:
            voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=sc_pace))
        with wave.open(str(out)) as r:
            lengths.append(r.getnframes() / r.getframerate())
    return lengths


def join_audio(work: Path, n: int, starts: list[float], total: float, out: Path):
    """Each scene's speech placed at its start time in one silent track."""
    with wave.open(str(work / "say00.wav")) as r:
        rate, width, ch = r.getframerate(), r.getsampwidth(), r.getnchannels()
    buf = bytearray(int(total * rate) * width * ch)
    for i in range(n):
        with wave.open(str(work / f"say{i:02d}.wav")) as r:
            frames = r.readframes(r.getnframes())
        at = int(starts[i] * rate) * width * ch
        buf[at:at + len(frames)] = frames
    with wave.open(str(out), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(width); w.setframerate(rate); w.writeframes(bytes(buf))


def srt_time(t: float) -> str:
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def captions(scenes: list, starts: list[float], lengths: list[float], out: Path):
    """Sentences of each scene's narration, timed in proportion to their length within the spoken stretch."""
    cues = []
    for sc, t0, dur in zip(scenes, starts, lengths):
        parts = [p for p in re.split(r"(?<=[.?!:])\s+", sc["say"]) if p]
        chunks = []
        for p in parts:                      # long sentences split at a comma near the middle
            if len(p) > 95 and ", " in p:
                mid = min((m.start() for m in re.finditer(", ", p)), key=lambda k: abs(k - len(p) / 2))
                chunks += [p[:mid + 1], p[mid + 2:]]
            else:
                chunks.append(p)
        total = sum(len(c) for c in chunks)
        t = t0
        for c in chunks:
            d = dur * len(c) / total
            cues.append((t, t + d, c)); t += d
    out.write_text("".join(f"{k + 1}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n\n" for k, (a, b, txt) in enumerate(cues)))


async def render_stills(scenes: list, work: Path):
    """Cards and label overlays as PNGs; for pans, the page region the pan crosses."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": CSS_W, "height": CSS_H}, device_scale_factor=SCALE)
        card_pg = await ctx.new_page()
        pan_pages = {}

        async def pan_page(width: int):
            if width not in pan_pages:
                ctx_w = await b.new_context(viewport={"width": width, "height": int(H * width / W)},
                                            device_scale_factor=W / width)
                pan_pages[width] = await ctx_w.new_page()
            return pan_pages[width]
        for i, sc in enumerate(scenes):
            pg = card_pg
            if "chart" in sc:
                await pg.set_content(f'<html><head><style>{CARD_CSS}</style></head><body>{chart_html(sc["chart"])}</body></html>')
                await pg.screenshot(path=str(work / f"card{i:02d}.png"))
            elif "card" in sc:
                c = sc["card"]
                body = "".join(f"<p>{html.escape(x)}</p>" for x in c["lines"])
                foot = f'<div class="foot">{html.escape(c["foot"])}</div>' if c.get("foot") else ""
                await pg.set_content(f'<html><head><style>{CARD_CSS}</style></head><body><div class="accent"></div>'
                                     f'<h1>{html.escape(c["title"])}</h1>{body}{foot}</body></html>')
                await pg.screenshot(path=str(work / f"card{i:02d}.png"))
            elif "clips" in sc:
                two = len(sc["clips"]) == 2
                labels = "".join(
                    f'<div class="l" style="{"left:%dpx" % (k * CSS_W // 2 + 16) if two else "left:16px"}">'
                    f'{html.escape(cl[3])}</div>' for k, cl in enumerate(sc["clips"]))
                top = (CSS_H - CSS_W // 2 * 9 // 16) // 2 - 44 if two else 14
                await pg.set_content(f'<html><head><style>{LABEL_CSS % (top, 16)}</style></head><body>{labels}</body></html>')
                await pg.screenshot(path=str(work / f"label{i:02d}.png"), omit_background=True)
            elif "pan" in sc:
                pn = sc["pan"]
                width = pn.get("width", PAN_CSS_W)
                pan_scale = W / width
                pg = await pan_page(width)
                await pg.goto(pn["page"].as_uri()); await pg.wait_for_load_state("networkidle")
                ys = []
                for target in (pn["from"], pn["to"]):
                    if target == "top":
                        ys.append(0)
                        continue
                    tag, text = target.split(":", 1)
                    after = ys[0] if ys else -1      # "to" is the first match below "from" (a row of that table)
                    y = await pg.evaluate("""([tag, text, after]) => { const el = [...document.querySelectorAll(tag)]
                        .find(h => h.textContent.trim().startsWith(text)
                                   && h.getBoundingClientRect().top + window.scrollY - 24 >= after);
                        if (!el) return null;
                        return el.getBoundingClientRect().top + window.scrollY - 24; }""", [tag, text, after])
                    if y is None:
                        raise SystemExit(f"scene {i}: no {tag} starting {text!r} in {pn['page'].name}")
                    ys.append(max(0, y))
                ys[1] += pn.get("down", 0)
                page_h = await pg.evaluate("document.documentElement.scrollHeight")
                view_h = -(-H // pan_scale) + 1     # rounded up, so the screenshot is never a pixel short of the frame
                y0, y1 = ys[0], min(max(ys[1], ys[0]), page_h - view_h)
                y0 = min(y0, y1)
                await pg.screenshot(path=str(work / f"pan{i:02d}.png"), full_page=True,
                                    clip={"x": 0, "y": y0, "width": width, "height": (y1 - y0) + view_h})
                sc["_pan_px"] = (y1 - y0) * pan_scale
        await b.close()


def fit(dur_s: float) -> str:
    return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=white"


def build_scene(i: int, sc: dict, dur: float, work: Path) -> Path:
    out = work / f"scene{i:02d}.mp4"
    enc = ["-r", FPS, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-an", "-t", f"{dur:.3f}"]
    if "card" in sc or "chart" in sc:
        run("-loop", "1", "-framerate", FPS, "-i", work / f"card{i:02d}.png", "-vf", f"scale={W}:{H},format=yuv420p", *enc, out)
    elif "pan" in sc:
        dist, hold = sc["_pan_px"], min(1.2, dur / 5)
        ease = f"(1-cos(PI*min(max((t-{hold})/{max(dur - 2 * hold, 0.1)},0),1)))/2"
        run("-loop", "1", "-framerate", FPS, "-i", work / f"pan{i:02d}.png",
            "-vf", f"scale={W}:-1,crop={W}:{H}:0:'{dist:.1f}*{ease}'", *enc, out)
    else:
        clips, ins, parts = sc["clips"], [], []
        for k, (f, a, b_, _) in enumerate(clips):
            speed = max(1.0, (b_ - a) / dur)
            ins += ["-ss", f"{a}", "-t", f"{b_ - a}", "-i", f]
            w = W // 2 if len(clips) == 2 else W
            parts.append(f"[{k}:v]setpts=(PTS-STARTPTS)/{speed:.4f},scale={w}:-2,tpad=stop_mode=clone:stop_duration={dur}[v{k}]")
        if len(clips) == 2:
            stack = f"[v0][v1]hstack=inputs=2,pad={W}:{H}:0:(oh-ih)/2:color=white[s]"
        else:
            stack = f"[v0]{fit(dur)}[s]"
        n = len(clips)
        filt = ";".join(parts + [stack, f"[s][{n}:v]overlay=0:0[o]"])
        run(*ins, "-loop", "1", "-i", work / f"label{i:02d}.png", "-filter_complex", filt, "-map", "[o]", *enc, out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--voice", required=True, help="a Kokoro folder (kokoro-v1.0.onnx, voices-v1.0.bin) or a piper voice model (.onnx)")
    ap.add_argument("--speaker", default="af_heart", help="Kokoro voice name")
    ap.add_argument("--out", default=str(ROOT / "tmp" / "video" / "watchverify-demo.mp4"))
    ap.add_argument("--pad", type=float, default=0.5, help="seconds of quiet after each scene's narration")
    ap.add_argument("--pace", type=float, default=1.0, help="speaking speed: below 1 is faster (the event allows 3 minutes)")
    a = ap.parse_args()
    out = Path(a.out); work = out.parent / "work"
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    for f in (EXPERT, OMIT3, SWAP01, DEMO, RESULTS):
        if not f.exists():
            raise SystemExit(f"missing input: {f}")
    lengths = speak(Path(a.voice), SCENES, work, a.pace, a.speaker)
    durs = [round(L + a.pad + 0.3, 2) for L in lengths]
    starts = [0.3 + sum(durs[:i]) for i in range(len(durs))]   # speech begins 0.3 s into each scene
    total = sum(durs)
    asyncio.run(render_stills(SCENES, work))
    segs = [build_scene(i, sc, d, work) for i, (sc, d) in enumerate(zip(SCENES, durs))]
    (work / "list.txt").write_text("".join(f"file '{s.name}'\n" for s in segs))
    run("-f", "concat", "-safe", "0", "-i", work / "list.txt", "-c", "copy", work / "video.mp4")
    join_audio(work, len(SCENES), starts, total, work / "voice.wav")
    captions(SCENES, starts, lengths, work / "captions.srt")
    # captions get their own light strip under the picture, so they never cover what is on screen
    style = ("FontName=DejaVu Sans,FontSize=10,PrimaryColour=&H00332419,BorderStyle=1,Outline=0,Shadow=0,"
             "MarginV=9,Alignment=2")
    frame = (f"scale={W}:{H - BAND}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:0:color=white,"
             f"drawbox=x=0:y={H - BAND}:w={W}:h={BAND}:color=0xEEF1F5:t=fill,")
    run("-i", work / "video.mp4", "-i", work / "voice.wav",
        "-vf", frame + f"subtitles={work / 'captions.srt'}:fontsdir=/usr/share/fonts/truetype/dejavu:force_style='{style}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", out)
    shutil.copy(work / "captions.srt", out.with_suffix(".srt"))
    print(json.dumps({"out": str(out), "seconds": round(total, 1), "scenes": [round(d, 1) for d in durs]}))


if __name__ == "__main__":
    main()
