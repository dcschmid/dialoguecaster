# DialogueCaster — Markdown → Podcast (Supertonic)

Convert Markdown dialogue (`Name: Text`) into podcast audio with **Supertonic** (ONNX Runtime, fully local). The pipeline parses dialogue lines into segments, synthesizes them, stitches them together with pauses and optional intro/outro music, and exports **MP3**, **WAV**, **WebVTT**, and optionally **Video** (static image + audio).

---

## 1. Overview

```
Markdown → Dialogue Parser → Supertonic → Audio Segments → MP3/WAV → WebVTT → Optional Video
```

- Fully local Supertonic TTS (models auto-download on first run)
- Per-speaker voice mapping (defaults: `daniel` → **M3**, `annabelle` → **F3**)
- Segment-based synthesis (clean timing, caching-friendly)
- Structured output layout with per-segment WAVs (on by default)
- Mock mode for fast tests without real synthesis
- **NEW**: Video export with static image + audio (requires FFmpeg)

---

## 2. Prerequisites

- Python **3.11+**
- FFmpeg available on `PATH` (`ffmpeg -version`)
- Virtual environment recommended

---

## 3. Setup

Create and activate a venv, then install dependencies (includes `supertonic`, `onnxruntime`, `pydub`):

```bash
python3.11 -m venv supertonic_env
source supertonic_env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Fast path: run `./setup_supertonic.sh` (creates venv `supertonic_env` and installs dependencies).

---

## 4. Quick Smoke Test (mock)

Run a fast, silent test to verify parsing and output layout:

```bash
python generate_podcast.py podscripts/decades/1980s.md --mock --output-dir out_mock
```

---

## 5. Run the Generator

Basic English run with defaults:

```bash
python generate_podcast.py script.md \
  --language en \
  --output-dir output_supertonic
```

Per-speaker mapping for Daniel & Annabelle:

```bash
cat > voices.json <<'JSON'
{
  "daniel": "M3",
  "annabelle": "F3"
}
JSON

python generate_podcast.py script.md \
  --supertonic-voices-json voices.json \
  --output-dir output_supertonic
```

Reuse or disable segment caching:

- Default: segment WAVs are saved and reused if present.
- Force regeneration: add `--no-reuse-existing-segments`.
- Skip segment WAVs entirely: add `--no-save-segments-wav`.

Change which speaker names use the default male/female voices via:

```bash
--male-aliases "daniel,male,host" --female-aliases "annabelle,female,guest"
```

---

## 6. Available Supertonic Voices

Supertonic voice styles are documented here: https://supertone-inc.github.io/supertonic-py/voices/

- Male voices: `M1`, `M2`, `M3`, `M4`, `M5`
- Female voices: `F1`, `F2`, `F3`, `F4`, `F5`

Defaults in this repo: `M3` (male/unknown) and `F3` (female).

---

## 7. Markdown Dialogue Format

```
daniel: Welcome back to Melody Mind!

annabelle: Today we're exploring female vocal icons.
```

- `Name:` must start the line; blank lines end a segment.
- Additional lines without a `Name:` prefix continue the current speaker.

---

## 8. Output Layout (structured default)

With `--structured-output` (default):

```
output_supertonic/
└── en/
    └── episode/
        ├── final/
        │   ├── episode.mp3
        │   ├── episode.wav
        │   └── episode.vtt
        └── segments/
            ├── episode_segment_001_daniel.wav
            └── episode_segment_002_annabelle.wav
```

Without structured output: final files in `--output-dir`, segment WAVs in `segments_wav/`.

---

## 9. Common Flags

| Flag | Description |
|------|-------------|
| `--pause-ms` | Silence between dialogue segments (default `750`) |
| `--pause-jitter-ms` | Random jitter on pauses to sound less metronomic (default `120`, set `0` to disable) |
| `--supertonic-voice` | Default voice style for unknown/male speakers (default `M3`) |
| `--supertonic-female-voice` | Fallback voice for female speakers (default `F3`) |
| `--male-aliases` | Comma-separated speaker names mapped to the default male voice (default `daniel,male,host`) |
| `--female-aliases` | Comma-separated speaker names mapped to the default female voice (default `annabelle,female,guest`) |
| `--supertonic-voices-json` | JSON mapping speaker → voice style |
| `--supertonic-speed` | Speed multiplier (default `0.93`) |
| `--supertonic-steps` | Denoising steps `1–100` (default `10`) |
| `--supertonic-max-chars` | Max chars before internal chunking (default `300`) |
| `--supertonic-silence-sec` | Silence between internal chunks (default `0.15`) |
| `--supertonic-speeds-json` | JSON mapping speaker → speed multiplier (e.g., `{\"daniel\": 0.94}`) |
| `--structured-output` / `--no-structured-output` | Toggle hierarchical layout |
| `--reuse-existing-segments` / `--no-reuse-existing-segments` | Control segment caching |
| `--mock` | Generate silence instead of running Supertonic |
| `--export-video` | Export video file (requires --image-file) |
| `--image-file` | Path to static image for video generation |
| `--video-format` | Video format: mp4, avi, mov (default: mp4) |

---

## 10. Video Export (Optional)

Create videos by combining a static image with the generated audio:

```bash
python generate_podcast.py script.md \
  --export-video \
  --image-file cover.jpg \
  --video-format mp4 \
  --output-dir output_video
```

**Video Export Requirements:**
- FFmpeg must be available on `PATH` (same as MP3 export)
- Supported image formats: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.webp`
- Video formats: `mp4` (default), `avi`, `mov`

The video will have the same duration as the audio and will be saved in the final output directory alongside the MP3 and VTT files.

---

## 12. Troubleshooting

| Issue | Fix |
|-------|-----|
| `supertonic` import error | `pip install -r requirements.txt` (ensure venv active) |
| MP3 export fails | Install FFmpeg and ensure it is on `PATH` |
| Only silence in output | Remove `--mock` and confirm Supertonic installed |
| Voices not applied | Check speaker names in Markdown and JSON keys (lowercase) |
| No segments detected | Verify `Name: Text` format and blank lines between turns |

---

## 13. Project Structure

```
generate_podcast.py      # Main CLI for Supertonic synthesis
requirements.txt         # Dependencies (Supertonic, ONNX Runtime, audio libs)
podscripts/              # Sample Markdown scripts
intro/                   # Optional intro/outro music
prompts/                 # Prompt snippets for content creation
utils/                   # Helpers (e.g., image utilities)
tests/                   # Basic parsing/mapping/CLI tests
```

---

Enjoy building your fully local podcast pipeline! 🎙️✨
