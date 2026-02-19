# AGENTS.md - DialogueCaster Development Guide

## Project Scope
- TTS backend: `hexgrad/kokoro`
- Language support: US English only (`en`)
- Output: MP3 + WebVTT

## Setup
```bash
pip install -r requirements.txt
./setup.sh
```

For local test tooling:
```bash
pip install -r requirements-dev.txt
```

Requirements:
- Python 3.10-3.12
- FFmpeg on PATH

## Common Commands
```bash
# Mock pipeline (fast)
python generate_podcast.py podscripts/en/decades/1980s.md --mock --output-dir out_test

# Real synthesis
python generate_podcast.py podscripts/en/decades/1980s.md --output-dir out_real

# Clear cache
python generate_podcast.py podscripts/en/decades/1980s.md --clear-cache

# Disable intro/outro
python generate_podcast.py script.md --no-intro --no-outro
```

## Tests / Lint / Format
```bash
pytest -v
ruff check .
black --check .
```

## Code Conventions
- Use `pathlib.Path` for file operations
- Keep logging structured (`logger.info("... %s", value)`)
- Validate user inputs at CLI boundaries
- Prefer small focused functions and explicit error handling

## Voice Defaults
- Male/default: `am_michael`
- Female/default: `af_heart`

Speaker aliases:
- male: `daniel,male,host`
- female: `annabelle,female,guest`

## Output Structure
```text
output/
  en/
    <topic>/
      <topic>.mp3
      <topic>.vtt
```
