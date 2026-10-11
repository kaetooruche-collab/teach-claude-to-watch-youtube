#!/usr/bin/env python3
"""Download an Instagram reel (or use a local video) and produce metadata,
a transcript, and sampled frames for Claude to inspect.

Requires: ffmpeg/ffprobe. yt-dlp is pip-installed on demand.
Transcription uses faster-whisper (pip-installed on demand), falling back to
openai-whisper if present. Use --no-transcribe to skip.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys

MAX_FRAMES = 24


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def pip_install(pkg):
    run([sys.executable, "-m", "pip", "install", "-q", pkg])


def clean_url(url):
    m = re.match(r"(https?://(?:www\.)?instagram\.com/(?:[^/]+/)?(?:reels?|p|tv)/[A-Za-z0-9_-]+)", url)
    return (m.group(1) + "/") if m else url


def download(url, out, args):
    if shutil.which("yt-dlp") is None:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            pip_install("yt-dlp")
    base = [sys.executable, "-m", "yt_dlp"] if shutil.which("yt-dlp") is None else ["yt-dlp"]
    cmd = base + ["--no-playlist", "-f", "mp4/best", "--write-info-json",
                  "-o", os.path.join(out, "video.%(ext)s"), url]
    if args.cookies:
        cmd += ["--cookies", args.cookies]
    if args.cookies_from_browser:
        cmd += ["--cookies-from-browser", args.cookies_from_browser]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        sys.exit("DOWNLOAD FAILED: Instagram likely requires login, rate-limited the request, "
                 "or this host cannot reach instagram.com. Retry with --cookies/--cookies-from-browser, "
                 "or pass a local .mp4 path instead.")
    vids = [f for f in glob.glob(os.path.join(out, "video.*")) if not f.endswith(".json")]
    if not vids:
        sys.exit("DOWNLOAD FAILED: no video file produced.")
    info = {}
    ij = os.path.join(out, "video.info.json")
    if os.path.exists(ij):
        info = json.load(open(ij))
    return vids[0], info


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def extract_frames(video, out, dur, args):
    fdir = os.path.join(out, "frames")
    shutil.rmtree(fdir, ignore_errors=True)
    os.makedirs(fdir)
    start = args.start or 0
    end = args.end or dur
    span = max(end - start, 0.1)
    fps = args.fps if args.fps else min(0.5, MAX_FRAMES / span)
    fps = min(fps, MAX_FRAMES / span) if not args.fps else fps
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(span), "-i", video,
           "-vf", f"fps={fps},scale='min(720,iw)':-2", "-q:v", "3",
           os.path.join(fdir, "f_%03d.jpg")]
    run(cmd)
    frames = sorted(glob.glob(os.path.join(fdir, "f_*.jpg")))[:MAX_FRAMES * 2]
    named = []
    for i, f in enumerate(frames):
        t = start + i / fps
        new = os.path.join(fdir, f"frame_{i + 1:02d}_{t:.1f}s.jpg")
        os.rename(f, new)
        named.append(new)
    return named


def transcribe(video, out, model):
    wav = os.path.join(out, "audio.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav])
    # Silent / no audio stream check
    r = subprocess.run(["ffmpeg", "-i", wav, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    if m and float(m.group(1)) < -50:
        return "(no audible speech: audio is silent)"
    lines = []
    try:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            pip_install("faster-whisper")
            from faster_whisper import WhisperModel
        wm = WhisperModel(model, device="cpu", compute_type="int8")
        segs, info = wm.transcribe(wav, vad_filter=True)
        for s in segs:
            lines.append(f"[{s.start:6.1f}s] {s.text.strip()}")
        header = f"(language: {info.language})\n"
    except Exception as e:  # network blocked for model download, etc.
        return f"(transcription unavailable: {e}. Use frames + caption, or ask the user for a transcript.)"
    return header + ("\n".join(lines) if lines else "(no speech detected; likely music only)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="Instagram URL or local video path")
    ap.add_argument("--out", default="./reel_out")
    ap.add_argument("--cookies")
    ap.add_argument("--cookies-from-browser")
    ap.add_argument("--fps", type=float, help="frames per second (default adaptive)")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--no-transcribe", action="store_true")
    ap.add_argument("--whisper-model", default="base")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg is required (apt-get install ffmpeg).")
    os.makedirs(args.out, exist_ok=True)

    if os.path.exists(args.source):
        video, info = args.source, {}
    else:
        video, info = download(clean_url(args.source), args.out, args)

    dur = duration(video)
    meta = {
        "source": args.source,
        "uploader": info.get("uploader") or info.get("channel"),
        "caption": info.get("description") or info.get("title"),
        "duration_s": dur,
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "view_count": info.get("view_count"),
        "track": info.get("track"),
        "artist": info.get("artist"),
        "upload_date": info.get("upload_date"),
        "hashtags": re.findall(r"#\w+", info.get("description") or ""),
    }
    json.dump(meta, open(os.path.join(args.out, "meta.json"), "w"), indent=2)

    frames = extract_frames(video, args.out, dur, args)
    transcript = "(skipped)" if args.no_transcribe else transcribe(video, args.out, args.whisper_model)
    open(os.path.join(args.out, "transcript.txt"), "w").write(transcript + "\n")

    print(f"Video: {video} ({dur:.1f}s)")
    print(f"Meta: {os.path.join(args.out, 'meta.json')}")
    print(f"Transcript: {os.path.join(args.out, 'transcript.txt')}")
    print(f"Frames ({len(frames)}) — view each with the Read tool:")
    for f in frames:
        print("  " + f)


if __name__ == "__main__":
    main()
