# DialogueCaster - Markdown to Podcast (US English)

Convert Markdown dialogue scripts into podcast audio using KOKORO-TTS (`hexgrad/kokoro`).

## Features
- US English synthesis (`en`) with curated voices
- Speaker-aware voice selection (`daniel`/male -> `am_michael`, `annabelle`/female -> `af_heart`)
- MP3 + WebVTT export
- Automatic intro/outro support from `audio/intro.mp3` and `audio/outro.mp3`
- Segment caching for faster reruns
- Mock mode for fast local testing

## Requirements
- Python 3.10-3.12
- FFmpeg on PATH

## Install
```bash
pip install -r requirements.txt
./setup.sh
```

For local test tooling:
```bash
pip install -r requirements-dev.txt
```

## Quick Start
```bash
# Fast test without real TTS
python generate_podcast.py podscripts/en/decades/1980s.md --mock

# Real synthesis (US English)
python generate_podcast.py podscripts/en/decades/1980s.md
```

## Usage
```bash
python generate_podcast.py script.md --output-dir output
```

Optional overrides:
```bash
python generate_podcast.py script.md \
  --kokoro-voice am_michael \
  --kokoro-female-voice af_heart \
  --kokoro-speed 1.0
```

Intro/outro behavior:
```bash
# automatic if audio/intro.mp3 and audio/outro.mp3 exist
python generate_podcast.py script.md

# disable intro/outro
python generate_podcast.py script.md --no-intro --no-outro
```

## CLI Notes
- `--structured-output`: default output layout is `output/en/<episode>/`
- `--clear-cache`: clears cached WAV segments before synthesis

## Output Layout
```text
output/
  en/
    <episode>/
      <episode>.mp3
      <episode>.vtt
```

## Troubleshooting
- `kokoro` import error: `pip install -r requirements.txt`
- MP3 export error: install FFmpeg and verify `ffmpeg -version`
- Only silence: remove `--mock`

## License
MIT
