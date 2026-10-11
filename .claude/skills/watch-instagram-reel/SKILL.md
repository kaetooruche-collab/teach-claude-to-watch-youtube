---
name: watch-instagram-reel
description: Watch an Instagram reel (or post video) from its URL by downloading it, extracting frames, and transcribing the audio, so you can describe, summarize, or act on what it shows and says. Use whenever the user shares an instagram.com/reel/, /reels/, /p/ or /tv/ link, or asks "watch this reel", "what does this reel say", or "build/follow what this reel shows".
---

# Watch an Instagram Reel

Claude cannot stream video, and Instagram pages are not readable by WebFetch or
scrapers (login wall). Instead: download the file, then turn it into things
Claude *can* read — metadata, a transcript, and a contact sheet of frames.

## Workflow

1. Run the pipeline (strip tracking params like `?xtok=` — the script does this):

   ```bash
   python3 .claude/skills/watch-instagram-reel/scripts/watch_reel.py "<reel-url>" --out "$SCRATCH/reel"
   ```

   Optional flags: `--cookies cookies.txt` (Netscape format, for login-walled
   or age/region-restricted reels), `--cookies-from-browser chrome`,
   `--fps 1` (frames per second, default adaptive ~1 per 2s, max 24 frames),
   `--no-transcribe`, `--whisper-model base` (default `base`).

2. Read the output files it prints:
   - `meta.json` – uploader, caption, hashtags, duration, music, like/comment counts
   - `transcript.txt` – timestamped speech (empty if the reel is music-only)
   - `frames/frame_XX_<t>s.jpg` – view each with the **Read** tool (images render visually)
   - `video.mp4`, `audio.wav` – raw files if more digging is needed

3. Synthesize: combine caption + transcript + frames. Cover what is said, what
   is shown (including on-screen text, UI screens, code, products), and the
   sequence. Quote on-screen text exactly; mark anything you couldn't read.

4. If the user's goal is to *act* on the reel (e.g. "build this skill/app/recipe"),
   extract the concrete steps/requirements from it first, state them back
   briefly, then do the work.

## Failure handling

- **Login required / rate limited / 403**: ask the user for cookies
  (`--cookies`) or for the caption/transcript pasted directly. Never ask for
  their password.
- **No network access to instagram.com** (sandbox allowlist): tell the user;
  they can upload the downloaded `.mp4` and you run the script with a local
  path instead: `watch_reel.py ./clip.mp4`.
- **No speech detected**: rely on frames + caption; say the audio was music/silent.
- Frames are sampled, so fast on-screen text can be missed — re-run with
  `--fps 2` or extract a specific window with `--start 5 --end 12`.

Report honestly what was and wasn't captured (e.g. "transcribed fully, 12 of
~30s of frames sampled"). Respect creators' content: summarize, don't repost.
