"""ffmpeg helpers (bundled binary from imageio-ffmpeg): cut and reorder segments, extract a frame, make
a 16 kHz WAV, count frames."""
import subprocess, os
from pathlib import Path
import imageio_ffmpeg


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG_ENV_KEYS = ("PATH", "LANG", "TMPDIR")   # what ffmpeg is given of the environment: never the API key
FFMPEG_TIMEOUT_S = 900                          # downloaded videos are untrusted input; a stuck decode is stopped


def run(args: list[str]) -> None:
    env = {k: os.environ[k] for k in FFMPEG_ENV_KEYS if k in os.environ}
    subprocess.run([ffmpeg(), "-v", "error", "-y", *args], check=True, env=env, timeout=FFMPEG_TIMEOUT_S)


def count_frames_and_secs(path: Path) -> tuple[int, float]:
    n, s = imageio_ffmpeg.count_frames_and_secs(str(path))
    return int(n), float(s)


def has_audio(src: Path) -> bool:
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", str(src), "-map", "0:a:0", "-t", "0.1", "-f", "null", "-"],
                       capture_output=True)
    return r.returncode == 0


def cut(src: Path, segments: list[tuple[float, float]], out: Path, width: int = 1280, fps: int = 15) -> Path:
    """Concatenate the given (start, end) segments of src, in the given order, re-encoded to H.264 with
    AAC audio (when src has audio) and faststart. Used to build test variants (omit a segment, or swap two)
    and the short windows the verifier takes a second look at."""
    audio = has_audio(src)
    parts = []
    for i, (a, b) in enumerate(segments):
        parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,scale={width}:-2,fps={fps}[v{i}];")
        if audio:
            parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}];")
    n = len(segments)
    inputs = "".join(f"[v{i}][a{i}]" if audio else f"[v{i}]" for i in range(n))
    graph = "".join(parts) + f"{inputs}concat=n={n}:v=1:a={int(audio)}[v]" + ("[a]" if audio else "")
    args = ["-i", str(src), "-filter_complex", graph, "-map", "[v]"]
    if audio:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "96k"]
    run(args + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out)])
    return out


def resample(src: Path, out: Path, fps: int = 5, width: int = 640) -> Path:
    """A video-only copy at a low frame rate for SAM tracking, which is billed per frame."""
    run(["-i", str(src), "-an", "-vf", f"fps={fps},scale={width}:-2", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
    return out


def frame_at(src: Path, t: float, out: Path, width: int = 640,
             boxes: list[tuple[float, float, float, float, str]] | None = None) -> Path:
    """One frame at t seconds, scaled to width; boxes (left, top, right, bottom, hex color) are in the scaled
    frame's pixels and drawn on it."""
    vf = f"scale={width}:-2"
    for (l, t_, r, b, color) in boxes or []:
        vf += f",drawbox=x={int(l)}:y={int(t_)}:w={max(int(r - l), 1)}:h={max(int(b - t_), 1)}:color=0x{color}@0.95:t=3"
    run(["-ss", f"{max(t, 0):.3f}", "-i", str(src), "-frames:v", "1", "-q:v", "4", "-vf", vf, str(out)])
    return out


def frames_between(src: Path, a: float, b: float, fps: float, out_dir: Path, width: int = 512) -> list[tuple[float, Path]]:
    """Frames from a to b seconds at fps, scaled to width, each with its time in src."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f*.jpg"):
        old.unlink()
    run(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src), "-vf", f"fps={fps},scale={width}:-2", "-q:v", "4",
         str(out_dir / "f%03d.jpg")])
    return [(round(a + i / fps, 2), f) for i, f in enumerate(sorted(out_dir.glob("f*.jpg")))]


def wav_16k(src: Path, out: Path) -> Path:
    run(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
    return out
