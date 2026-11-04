"""watchverify command line. Every subcommand writes into runs/<run>/ and respects --budget (dollars)."""
import argparse, asyncio, json, sys
from pathlib import Path
from . import media
from .extract import extract
from .verify import verify_video, self_check, rescore
from .ground import ground
from .report import write_report
from .meta_client import make_client


def main(argv=None):
    ap = argparse.ArgumentParser(prog="watchverify")
    ap.add_argument("--run", default="dev", help="run id under runs/")
    ap.add_argument("--budget", type=float, default=1.00, help="dollar ceiling for this run")
    ap.add_argument("--replay", default=None, help="fixtures dir: replay saved responses, no network")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="video to procedure JSON"); e.add_argument("video"); e.add_argument("--name", default="reference")
    k = sub.add_parser("cut", help="build a variant clip from (start,end) segments in order"); k.add_argument("src"); k.add_argument("out"); k.add_argument("segments", nargs="+", help="start:end pairs in seconds")
    vv = sub.add_parser("verify", help="check a candidate VIDEO against a reference procedure JSON"); vv.add_argument("reference"); vv.add_argument("video"); vv.add_argument("--name", default="verify")
    vv.add_argument("--reference-video", default=None, help="the expert's video, for reference frames (default: the one the procedure names)")
    vv.add_argument("--no-second-look", action="store_true", help="skip the second look at steps reported not observed")
    vv.add_argument("--checker", default="", help="checker version label (bench.CHECKERS), such as v3; default v2")
    g = sub.add_parser("ground", help="SAM tracks, speech turns and evidence frames for a procedure"); g.add_argument("procedure"); g.add_argument("video"); g.add_argument("--name", default="reference")
    g.add_argument("--fps", type=int, default=5, help="frame rate of the tracking copy (SAM bills per frame)")
    sc = sub.add_parser("self-check", help="check the expert's own video against its procedure; marks steps the camera cannot show"); sc.add_argument("procedure"); sc.add_argument("video"); sc.add_argument("--name", default="reference")
    sub.add_parser("rescore", help="re-apply the code rules to the run's saved verifications (free)")
    cuts_help = ("where planted mistakes are cut: midpoint (the reference's boundaries), refined (bench-boundaries) or "
                 "labels (labels.json, person-confirmed; the only method a held-out root accepts)")
    root_help = "where the bench-<sid> run folders are: runs, or runs/holdout (held-out: labels cuts only)"
    bp = sub.add_parser("bench-prepare", help="accuracy test: scout a source video, cut a clip, build its reference"); bp.add_argument("sid"); bp.add_argument("video")
    bp.add_argument("--root", default="runs", help=root_help)
    br = sub.add_parser("bench-run", help="accuracy test: cut the planted mistakes and check each one"); br.add_argument("sid")
    br.add_argument("--checker", default="", help="checker version label, such as v2: checks the same clips with a changed checker, keeping earlier checks")
    br.add_argument("--root", default="runs", help=root_help)
    br.add_argument("--cuts", default="midpoint", choices=["midpoint", "refined", "labels"], help=cuts_help)
    br.add_argument("--rep", type=int, default=0, help="repeat number: check the same clips again (0 is the first run)")
    br.add_argument("--only", nargs="*", default=None, help="check only these planted mistakes (names like omit2, swap01, correct)")
    bc = sub.add_parser("bench-confirm", help="accuracy test: copy a checker's saved checks to a new label and add a confirm look at each step's claimed stretch"); bc.add_argument("sid")
    bc.add_argument("--cuts", default="refined", choices=["midpoint", "refined", "labels"]); bc.add_argument("--root", default="runs")
    bc.add_argument("--from-checker", default="v2"); bc.add_argument("--to-checker", default="v2c")
    bb = sub.add_parser("bench-boundaries", help="accuracy test: find where each step's hand work ends, from dense stills"); bb.add_argument("sid")
    bb.add_argument("--root", default="runs", help=root_help)
    bm = sub.add_parser("bench-remnants", help="accuracy test: SAM seconds left of each removed, measurable step"); bm.add_argument("sid")
    bm.add_argument("--root", default="runs", help=root_help)
    bm.add_argument("--cuts", default="midpoint", choices=["midpoint", "refined", "labels"], help=cuts_help)
    be = sub.add_parser("bench-evidence", help="accuracy test: copy one source's grading (no video) into a folder anyone can re-score"); be.add_argument("sid"); be.add_argument("out")
    be.add_argument("--checker", default="", help="checker version label, such as v2: checks the same clips with a changed checker, keeping earlier checks")
    be.add_argument("--cuts", default="refined", choices=["midpoint", "refined", "labels"], help=cuts_help)
    be.add_argument("--root", default="runs", help=root_help)
    bx = sub.add_parser("bench-replay", help="re-score committed grading evidence offline (no network, no key) and compare with the claimed results"); bx.add_argument("evidence")
    bx.add_argument("--without", default="", help="comma-separated inputs to swap for their neutral versions: marks, narration, selection, grounding")
    bx.add_argument("--off", default="", help="comma-separated rules to switch off, as bench-score's with-and-without rows: marks, narration, timing, moments, confirm, selection")
    for k in ("marks", "narration", "selection", "grounding"):
        bx.add_argument(f"--{k}", default=None, help=f"read this file as the {k} input (one source's folder only)")
    bx.add_argument("--json", action="store_true", help="print the totals as one JSON document")
    bs = sub.add_parser("bench-score", help="accuracy test: re-score every source with the current rules (free) and print the table")
    bs.add_argument("--checker", default="", help="checker version label, such as v2: checks the same clips with a changed checker, keeping earlier checks")
    bs.add_argument("--root", default="runs", help=root_help)
    bs.add_argument("--cuts", default="midpoint", choices=["midpoint", "refined", "labels"], help=cuts_help)
    bs.add_argument("--rep", type=int, default=0, help="which repeat to score")
    bo = sub.add_parser("bench-report", help="accuracy test: write the results page from the saved checks (free)")
    bo.add_argument("--cuts", default="refined", choices=["midpoint", "refined", "labels"], help=cuts_help)
    bo.add_argument("--out", default="runs/bench-report.html")
    bo.add_argument("--checker", default="", help="checker version label of the checks to show, such as v2")
    bo.add_argument("--root", default="runs", help=root_help)
    bo.add_argument("--sources", default="bench/sources.json", help="source details: bench/sources.json, or bench/holdout.json for held-out")
    bt = sub.add_parser("bench-timing", help="accuracy test: add the SAM timing measurement to saved checks"); bt.add_argument("sid")
    bt.add_argument("--root", default="runs", help=root_help)
    hr = sub.add_parser("holdout-register", help="record a downloaded held-out video by its content hash in bench/holdout.json, before anything is made from it")
    hr.add_argument("sid"); hr.add_argument("video"); hr.add_argument("--title", required=True, help="the title exactly as the draw picked it")
    for k in ("author", "license", "url"):
        hr.add_argument(f"--{k}", default="", help=f"the video's {k}, for the results page's credit line")
    ls_ = sub.add_parser("label-stills", help="labels: stills of a source's clip and an overview page of them with the steps as text"); ls_.add_argument("sid")
    ls_.add_argument("--root", default="runs/holdout", help=root_help)
    lp = sub.add_parser("label-page", help="labels: the confirm page from the source's prelabels.json"); lp.add_argument("sid")
    lp.add_argument("--root", default="runs/holdout", help=root_help)
    lv = sub.add_parser("label-serve", help="labels: serve the confirm pages on 127.0.0.1; their Confirm writes labels.json")
    lv.add_argument("--root", default="runs/holdout", help=root_help); lv.add_argument("--port", type=int, default=8781)
    lv.add_argument("--who", required=True, help="the person confirming, recorded as made_by human:<who>")
    r = sub.add_parser("report", help="write the run's HTML page from its procedure, grounding and verifications"); r.add_argument("--name", default="reference")
    r.add_argument("--only", nargs="+", default=None, help="show only these saved verifications (file stems, in this order); the cost covers only their calls and the reference's")
    r.add_argument("--out", default=None, help="write the page here instead of <run>/report.html")
    r.add_argument("--credit", default=None, help="footage credit for the page footer (else the run's meta.json)")
    sub.add_parser("ledger", help="print this run's cost ledger")
    a = ap.parse_args(argv)
    run_dir = Path("runs") / a.run
    if a.cmd == "cut":
        segs = [tuple(map(float, s.split(":"))) for s in a.segments]
        media.cut(Path(a.src), segs, Path(a.out)); print(a.out, media.count_frames_and_secs(Path(a.out))); return
    if a.cmd == "ledger":
        from .ledger import Ledger
        print(Ledger(run_dir / "ledger.jsonl").summary()); return
    if a.cmd == "report":
        print(write_report(run_dir, a.name, Path(a.out) if a.out else None, only=a.only, credit=a.credit)); return
    if a.cmd == "bench-report":
        from .bench_report import write
        print(write(Path(a.root), Path(a.sources), Path(a.out), cuts=a.cuts, checker=a.checker,
                    baseline=Path("runs/bench-summary-v1-times-shown.json"))); return
    if a.cmd == "holdout-register":
        from . import bench
        print(json.dumps(bench.register_download(Path("bench/holdout.json"), a.title, a.sid, Path(a.video), author=a.author, license=a.license, url=a.url), indent=1)); return
    if a.cmd in ("label-stills", "label-page", "label-serve"):
        from . import labels
        if a.cmd == "label-stills":
            print(len(labels.stills(Path(a.root) / f"bench-{a.sid}")), "stills;", labels.overview_page(Path(a.root) / f"bench-{a.sid}"))
        elif a.cmd == "label-page":
            print(labels.confirm_page(Path(a.root) / f"bench-{a.sid}"))
        else:
            print(f"serving {a.root} on http://localhost:{a.port}/ (confirm pages at bench-<sid>/label.html)")
            labels.serve(Path(a.root), a.port, a.who)
        return
    if a.cmd == "bench-evidence":
        from .replay import export_evidence
        print(json.dumps(export_evidence(Path(a.root) / f"bench-{a.sid}", Path(a.out), a.cuts, checker=a.checker), indent=1)); return
    if a.cmd == "bench-replay":
        from .replay import replay_evidence
        use = {k: Path(getattr(a, k)) for k in ("marks", "narration", "selection", "grounding") if getattr(a, k)}
        r = replay_evidence(Path(a.evidence), tuple(x for x in a.without.split(",") if x), use,
                            tuple(x for x in a.off.split(",") if x))
        if a.json:
            print(json.dumps(r["totals"], indent=1, sort_keys=True)); return
        print(f"{r['checks']} rows rebuilt from the committed responses and re-scored by the published code"
              + (f"; {r['matches']} match the claimed results" if r["as_exported"] else f" with {'; '.join(x for x in (a.without and f'inputs swapped ({a.without})', use and 'files given', a.off and f'rules off ({a.off})') if x)}"))
        print("(a match shows the totals follow from the saved answers; it does not show the answers are right)")
        for kind, c in sorted(r["totals"].items()):
            print(f"  {kind:8} " + "  ".join(f"{k} {n}" for k, n in sorted(c.items())))
        if r["as_exported"]:
            for m in r["mismatches"]:
                print(f"  MISMATCH {m['source']} {m['name']}: claimed {m['claimed']}, re-scored {m['outcome']}")
            raise SystemExit(0 if r["matches"] == r["checks"] else 1)
        return                                   # a with-and-without replay is offline too: never build a client
    if a.cmd == "bench-confirm":
        from . import bench
        res = asyncio.run(bench.add_confirm(a.sid, Path(a.root), a.budget, a.cuts, a.from_checker, a.to_checker))
        print("\n".join(json.dumps(r) for r in res)); return
    if a.cmd in ("bench-prepare", "bench-run", "bench-score", "bench-timing", "bench-boundaries", "bench-remnants"):
        from . import bench
        if a.cmd == "bench-prepare":
            print(json.dumps(asyncio.run(bench.prepare_source(a.sid, Path(a.video), Path(a.root), a.budget)), indent=1))
        elif a.cmd == "bench-run":
            res = asyncio.run(bench.run_variants(a.sid, Path(a.root), a.budget, cuts=a.cuts, rep=a.rep, only=a.only, checker=a.checker))
            print("\n".join(f"{r['name']:10} {r['verdict']:7} {r['outcome']}" for r in res))
        elif a.cmd == "bench-boundaries":
            for b in asyncio.run(bench.boundaries_for(a.sid, Path(a.root), a.budget)):
                print(f"after step {b['after_step']}: ends {b['first_ends_s']:6.2f}  next begins {b['second_begins_s']:6.2f}  "
                      f"{'clean' if b['clean'] else 'NOT CLEAN'}")
        elif a.cmd == "bench-remnants":
            print(json.dumps(asyncio.run(bench.remnants(a.sid, Path(a.root), a.budget, a.cuts))))
        elif a.cmd == "bench-timing":
            print(asyncio.run(bench.add_timing_to_saved(a.sid, Path(a.root), a.budget)), "checks measured")
        else:
            for off, label in bench.ABLATIONS:
                res = bench.rescore_results(Path(a.root), cuts=a.cuts, rep=a.rep, off=off, checker=a.checker)
                if not off:
                    (Path(a.root) / ("bench-summary.json" if a.cuts == "midpoint" and not a.rep and not a.checker else f"bench-summary-{a.cuts}{'-' + a.checker if a.checker else ''}-r{a.rep}.json")).write_text(json.dumps(res, indent=1))
                    print(f"{len({r['sid'] for r in res})} source videos, {a.cuts} cuts; every planted mistake has a row")
                    for r in res:
                        if not r["graded"] and r["truth"]["kind"] != "selfcheck":
                            print(f"  not graded: {r['sid']} {r['name']}: {r['why']} (decided by {r['excluded_by']})")
                t = bench.tally(res)
                print(f"-- {label}")
                for kind in ("omit", "swap", "correct"):
                    k = t[kind]
                    rest = "  ".join(f"{o} {n}" for o, n in sorted(k.items()) if o not in ("planted", "graded", "wrong_fail_elsewhere", "review_elsewhere"))
                    elsewhere = (f"  | an untouched step failed in {k['wrong_fail_elsewhere']}, sent to review in {k['review_elsewhere']}"
                                 if kind != "correct" else "")
                    print(f"{kind:8} {k['graded']:3} graded of {k['planted']:3}  {rest}{elsewhere}")
        return
    if a.cmd == "rescore":
        for stem, verdict in rescore(run_dir):
            print(f"{stem:40} {verdict}")
        return
    client = make_client(run_dir, a.budget, Path(a.replay) if a.replay else None)
    if a.cmd == "extract":
        p = asyncio.run(extract(client, Path(a.video), run_dir, a.name))
        print(json.dumps({k: v for k, v in p.items() if k != "_source"}, indent=1))
    elif a.cmd == "verify":
        from . import bench
        ref = json.loads(Path(a.reference).read_text())
        gp = run_dir / "reference.grounding.json"
        v = asyncio.run(verify_video(client, ref, Path(a.video), run_dir, a.name,
                                     Path(a.reference_video) if a.reference_video else None, not a.no_second_look,
                                     grounding=json.loads(gp.read_text()) if gp.exists() else None,
                                     **bench.checker_options(a.checker)))
        print(json.dumps({k: v2 for k, v2 in v.items() if not k.startswith("_")}, indent=1))
    elif a.cmd == "self-check":
        proc = asyncio.run(self_check(client, json.loads(Path(a.procedure).read_text()), Path(a.video), run_dir, a.name))
        Path(a.procedure).write_text(json.dumps(proc, indent=1))
        print(json.dumps([{"index": st["index"], "action": st["action"], "self_check": st["self_check"]} for st in proc["steps"]], indent=1))
    elif a.cmd == "ground":
        proc = json.loads(Path(a.procedure).read_text())
        gr = asyncio.run(ground(client, proc, Path(a.video), run_dir, a.name, fps=a.fps))
        print(json.dumps({k: gr[k] for k in ("phrases", "track_frames")} |
                         {"steps": [{"index": s["index"], "frame": s["frame"],
                                     "tracked": {p: t["frames"] for p, t in s["tracks"].items()},
                                     "speech": [x["text"] for x in s["speech"]]} for s in gr["steps"]]}, indent=1))
    print(client.ledger.summary(), file=sys.stderr)


if __name__ == "__main__":
    main()
