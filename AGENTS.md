# AGENTS.md

Operational guide for coding agents. Focus: deterministic, safe generation of podcast audio (Piper TTS) from Markdown.

---

## 1. Overview

Goal: Markdown dialogue scripts (format `Name: Text`) → MP3 + WebVTT, optionally per‑segment WAVs.

Primary script:

- `chatterbox_tts.py` – pipeline: parse → segment → synthesize → mux → export
- `optimize_covers.py` – cover image optimization

Technologies:

- Python 3.9+ (3.11.x preferred)
- Piper (`piper-tts` from PyPI) using ONNX Runtime (`onnxruntime` / `onnxruntime-gpu`)
- Optional OpenVoice V2 backend (ToneColorConverter + MeloTTS, PyTorch)
- Pydub + FFmpeg
- Optional per-speaker Piper speaker-id overrides via `--speaker-ids-json`
- Optional per-speaker voice assignments via `--speaker-voices-json` (defaults to `voices/speaker_voices.json` when present)

Outputs (default-on features below can be disabled with `--no-*` flags):

- `output/<name>.mp3`
- `output/<name>.vtt`
- `output/<name>.wav` (disable with `--no-export-wav`)
- Segment WAVs (enable/disable: `--save-segments-wav` / `--no-save-segments-wav`, default ON)

---

## 2. Setup

```bash
python -m venv podcast-tts-env
source podcast-tts-env/bin/activate
pip install -r requirements.txt
# Optional OpenVoice backend
pip install -r requirements-openvoice.txt
# Download checkpoints_v2_0417.zip (OpenVoice docs) → unzip to checkpoints_v2/
```

Optional `.env` (no secrets). Then quick test:

```bash
python chatterbox_tts.py podscripts/classic-rock/classic-rock.md --language en --mock --output-dir out_test
```

Drop downloaded Piper voices (`*.onnx` + `.onnx.json`) into `voices/`. The repo contains `voices/speaker_voices.json` which already maps `daniel` → Ryan and `annabelle` → Cori; extend the file for additional hosts or pass a different JSON via `--speaker-voices-json`.

FFmpeg prüfen:

```bash
ffmpeg -version
```

If FFmpeg missing: inform user (do not auto‑install).

---

## 3. Conventions

- Comments / logs now in English (legacy German allowed temporarily during transition).
- No external API keys (Speechify removed).
- Do not re‑segment artificially; keep original granularity.

---

## 4. Typical agent tasks

| Task | Datei(en) | Ziel |
|------|-----------|------|
| New CLI flag | `chatterbox_tts.py` | Extend function, keep backward compatible |
| Add tests | `tests/` | Parsing, mapping, VTT |
| Improve docs | `README.md`, `AGENTS.md` | Clarity & migration |

Bei größeren Refactors: Kurzbegründung in Commit Message.

---

## 5. Architecture (short)

1. Read Markdown
2. Detect speaker lines via regex
3. Accumulate blocks per speaker
4. Synthesize serially (GPU / CPU) – mock on failure if enabled
5. Concatenate segment audio + pauses
6. Derive timestamps → WebVTT
7. Export MP3 (+ WAV if not disabled) + VTT
8. Cleanup temporary files

Failure policy: synthesis exception → log warning → optionally insert silence (do not abort whole pipeline) when feasible.

---

## 6. Tests

Recommended base:

```text
tests/
  test_parsing.py
  test_mapping.py
  test_subtitles.py
```

Use mock instead of real model load: `--mock` or call synthesis stub producing silence.

Test cases:

- Speaker names with umlauts
- Empty lines / multiple blank lines
- Colon inside sentence (not a speaker)
- Multiple speaker names (ensure `[S1]/[S2]` assignment)
- VTT timing with synthetic lengths

---

## 7. Style & quality

- 4 spaces, f‑strings
- Use logging instead of `print` in main paths
- Keep functions small & focused
- Error messages actionable

---

## 8. Performance

- Synthesis is bottleneck; add parallelism only when needed
- Avoid duplicating all segments in RAM
- For long scripts: highlight GPU benefit

---

## 9. Security

- No secrets; `.env` only optional defaults
- No unsolicited network downloads except optional prompt files

---

## 10. Change process

For modifications in `chatterbox_tts.py`:

1. Inspect current arguments (`--help`)
2. Implement backwards‑compatible change
3. Run mock smoke test (small Markdown)
4. Real test optional (if GPU available)
5. Update README / AGENTS if behavior visible to users

---

## 11. Edge cases

| Fall | Verhalten |
|------|-----------|
| Umlaut names | Detected |
| Blank lines | Segment termination |
| Colon inside sentence | No speaker switch |
| Missing speaker-id mapping | Continue with default Piper speaker id (0 or None) |
| >2 unique speakers | Additional names reuse `[S1]` tag |

---

## 12. Command quick ref (defaults & disabling examples)

```bash
# Basic (structured output + segment WAVs + WAV export all ON by default)
python chatterbox_tts.py file.md --language en \
  --piper-voice /voices/en_US-lessac-medium.onnx \
  --output-dir out

# Map fixed speakers to Piper speaker IDs
python chatterbox_tts.py file.md --language en \
  --piper-voice /voices/en_US-lessac-medium.onnx \
  --speaker-ids-json voices/speakers.json \
  --output-dir out_named

Note: In this Kokoro-focused repo the CLI now defaults to Kokoro with sensible defaults:
`--tts-backend kokoro --kokoro-lang-code b --kokoro-voices-json kokoro_voices.json --kokoro-device cuda`

# GPU accelerated run with tweaked length scale
python chatterbox_tts.py file.md --language en \
  --piper-voice /voices/en_US-lessac-medium.onnx \
  --piper-use-cuda \
  --piper-length-scale 0.95 \
  --output-dir out_gpu

# Disable structured layout & segment WAVs
python chatterbox_tts.py file.md --language en --no-structured-output --no-save-segments-wav --output-dir out_flat

# CPU mock test (fast CI)
python chatterbox_tts.py file.md --language en --mock --output-dir out_mock

# Suppress default warning suppression (show all warnings)
python chatterbox_tts.py file.md --language en --no-suppress-warnings --output-dir out_verbose

# Reuse cached segments (delete individual WAVs to force regeneration)
python chatterbox_tts.py file.md --language en --reuse-existing-segments --output-dir out_cached

# OpenVoice V2 (reference audio cloning)
python chatterbox_tts.py file.md --language en --tts-backend openvoice \
  --openvoice-reference voices/reference.wav \
  --openvoice-checkpoints checkpoints_v2 \
  --output-dir out_openvoice
```

---

## 13. Commit & PR

- Prefixes: feat:, fix:, docs:, refactor:, test:
- Small, focused commits
- Update tests / docs on behavior change
- Remove dead files

---

## 14. Enhancement ideas

- Loudness normalization (EBU R128)
- Multi‑file batch CLI
- Automatic silence trimming
- Abstract alternative Piper checkpoints / future releases
- Per‑speaker pause & style parameters

---

## 15. Limits

- Do not commit large audio samples
- No proprietary service integrations without approval
- Do not modify license texts

---

## 16. Uncertainty?

Ask user for high‑risk decisions; make low‑risk formatting assumptions autonomously.

---

## 17. Maintaining this document

Update on: new flags, pipeline changes, additional tests, new backend. PR note: `Update AGENTS.md: reason`.

---

This document underpins consistent automated changes.
