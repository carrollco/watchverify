"""The labeling path for held-out truth: stills and pages carry none of the reference's seconds; only a person's
confirm writes labels.json, which bench.load_labels then accepts. No network: a tiny ffmpeg test clip."""
import json, subprocess
import pytest
from watchverify import bench, labels, media

SECRET = [13.37, 21.73, 34.91]          # canary seconds: the reference's own times must never reach the pages


def source(tmp_path):
    d = tmp_path / "holdout" / "bench-x"; d.mkdir(parents=True)
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-t", "8",
                    "-pix_fmt", "yuv420p", str(d / "clip.mp4")], check=True)
    ref = {"task": "t", "steps": [{"index": i, "start_s": SECRET[i], "end_s": SECRET[i] + 1.11, "evidence_s": SECRET[i] + 0.5,
                                   "action": f"act{i}", "observable_checkpoint": f"chk{i}"} for i in range(3)]}
    (d / "reference.procedure.json").write_text(json.dumps(ref))
    return d


def test_pages_carry_no_reference_seconds_and_only_a_confirm_makes_truth(tmp_path):
    d = source(tmp_path)
    assert len(labels.stills(d)) == 16                                  # 8 s at 2 per second
    labels.overview_page(d)
    labels.write_prelabels(d, [{"index": i, "start_s": 2.0 * i + 0.5, "end_s": 2.0 * i + 1.5, "visible": True, "note": "n"}
                               for i in range(3)], "model:prelabeler (from stills)")
    labels.confirm_page(d)
    for page in ("label-overview.html", "label.html"):
        text = (d / page).read_text()
        for x in SECRET:
            for v in (x, x + 1.11, x + 0.5):
                assert f"{v:.2f}" not in text and f"{v:.1f} s" not in text, (page, v)
    with pytest.raises(OSError):
        bench.load_labels(d)                                            # proposals alone are not truth
    assert bench.independence_problems(d, "labels")
    got = labels.save_confirmed(d, [{"index": 0, "start_s": 0.5, "end_s": 1.5, "visible": True},
                                    {"index": 1, "start_s": 2.0, "end_s": 3.5, "visible": True},
                                    {"index": 2, "start_s": 4.5, "end_s": 5.5, "visible": False, "is_step": False}], "owner",
                                   ["tightening a screw at the back, about 6 s"])
    assert got["made_by"] == "human:owner" and got["changed_from_prelabels"] == [1, 2]
    assert got["missed_steps"] == ["tightening a screw at the back, about 6 s"]
    assert bench.ungradable_steps(d, "labels") == {2: "not_a_step"}
    assert got["prelabeled_by"] == "model:prelabeler (from stills)"
    assert bench.load_labels(d)["steps"][2]["visible"] is False and bench.independence_problems(d, "labels") == []
    with pytest.raises(ValueError):
        labels.save_confirmed(d, [{"index": 0, "start_s": 2, "end_s": 1, "visible": True}], "owner")


def test_the_confirm_pages_script_parses(tmp_path):
    """The page's script is generated from Python; a stray escape there breaks every button, silently."""
    import re, shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    d = source(tmp_path)
    labels.write_prelabels(d, [{"index": i, "start_s": 2.0 * i + 0.5, "end_s": 2.0 * i + 1.5, "visible": True}
                               for i in range(3)], "model:prelabeler (from stills)")
    page = labels.confirm_page(d).read_text()
    script = re.findall(r"<script>(.*?)</script>", page, re.S)[0]
    (tmp_path / "page.js").write_text(script)
    r = subprocess.run([node, "--check", str(tmp_path / "page.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_label_server_answers_only_its_own_page(tmp_path):
    """The attacks from the 2026-10-28 security review: a forged confirm from another site (plain-text body, foreign
    Origin, no token), a read through a foreign Host name (DNS rebinding), directory listings, other files."""
    import http.client, threading
    d = source(tmp_path)
    labels.write_prelabels(d, [{"index": i, "start_s": 2.0 * i + 0.5, "end_s": 2.0 * i + 1.5, "visible": True}
                               for i in range(3)], "model:prelabeler (from stills)")
    labels.confirm_page(d)
    (d / "raw").mkdir(); (d / "raw" / "secret.json").write_text("{}")
    srv = labels.make_server(d.parent, 0, "owner", "TOKEN123")
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    here = f"127.0.0.1:{port}"

    def req(method, path, body=None, **headers):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        h = {"Host": here} | headers
        c.request(method, path, body=body, headers=h)
        r = c.getresponse(); out = (r.status, r.read()); c.close(); return out
    try:
        status, page = req("GET", "/bench-x/label.html")
        assert status == 200 and b'content="TOKEN123"' in page
        assert req("GET", "/bench-x/label.html", Host="evil.example")[0] == 403            # rebinding
        assert req("GET", "/")[0] == 404 and req("GET", "/bench-x/")[0] == 404             # no listings
        assert req("GET", "/bench-x/raw/secret.json")[0] == 404                            # nothing else served
        assert req("GET", "/bench-x/label-stills/../raw/secret.json")[0] == 404
        good = json.dumps({"steps": [{"index": i, "start_s": 2.0 * i + 0.5, "end_s": 2.0 * i + 1.5, "visible": True}
                                     for i in range(3)]})
        assert req("POST", "/bench-x/save", good, **{"Content-Type": "text/plain"})[0] == 403           # no token
        assert req("POST", "/bench-x/save", good, **{"Content-Type": "text/plain", "X-Label-Token": "TOKEN123"})[0] == 415
        assert req("POST", "/bench-x/save", good, **{"Content-Type": "application/json", "X-Label-Token": "TOKEN123",
                                                      "Origin": "https://evil.example"})[0] == 403
        assert not (d / "labels.json").exists()
        status, msg = req("POST", "/bench-x/save", good, **{"Content-Type": "application/json", "X-Label-Token": "TOKEN123",
                                                           "Origin": f"http://{here}"})
        assert status == 200 and json.loads((d / "labels.json").read_text())["made_by"] == "human:owner"
    finally:
        srv.shutdown()
