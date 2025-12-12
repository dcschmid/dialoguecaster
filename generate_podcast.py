#!/usr/bin/env python3
"""Local Podcast Pipeline (Supertonic Edition)
---------------------------------------------

Standalone script using Supertonic to convert
Markdown dialogue scripts into audio (WAV/MP3) plus WebVTT subtitles.

- 100% local with Supertonic (ONNX Runtime)
- Language: English (default)
- Dialogue format: "Name: Text" per line
- Configurable pauses between segments
- Outputs: MP3 + .vtt (+ optional per-segment WAV; intro/outro music supported)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import re
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING, Any
from dotenv import load_dotenv
import json
import numpy as np

AudioSegment: Any = None
try:
    from pydub import AudioSegment  # For combining segments & MP3 export
except Exception:  # pragma: no cover
    AudioSegment = None

if TYPE_CHECKING:
    from pydub import AudioSegment as AudioSegmentType
else:
    AudioSegmentType = Any

# Supertonic (ONNX Runtime)
HAS_SUPERTONIC = False
SUPERTONIC_IMPORT_ERROR: Optional[Exception] = None
try:  # pragma: no cover
    from supertonic import TTS

    HAS_SUPERTONIC = True
except Exception as err:  # pragma: no cover
    SUPERTONIC_IMPORT_ERROR = err
    TTS = None  # type: ignore

# Logging Setup
LOG_LEVEL = os.getenv("CHATTERBOX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("supertonic_podcast_tts")

SUPPORTED_LANGS = {"en"}
DEFAULT_LANGUAGE = "en"
MIN_PYTHON = (3, 11, 0)
SUPERTONIC_SAMPLE_RATE_FALLBACK = 24000
DEFAULT_MALE_VOICE = "M3"
DEFAULT_FEMALE_VOICE = "F3"
DEFAULT_MALE_ALIASES = ["daniel", "male", "host"]
DEFAULT_FEMALE_ALIASES = ["annabelle", "female", "guest"]

# Regex: speaker line "Name: Text"
SPEAKER_LINE = re.compile(r"^([A-Za-z0-9_ÄÖÜäöüß\- ]{1,40}):\s*(.*)$")


@dataclass
class Segment:
    index: int
    speaker: str
    text: str
    start: float = 0.0
    end: float = 0.0


class MarkdownDialogueParser:
    """Extract speaker segments from a simple Markdown dialogue format."""

    def parse(self, content: str) -> List[Segment]:
        lines = content.splitlines()
        segments: List[Segment] = []
        current_speaker: Optional[str] = None
        buffer: List[str] = []

        def flush():
            nonlocal segments, current_speaker, buffer
            if current_speaker and buffer:
                text = " ".join([b.strip() for b in buffer if b.strip()]).strip()
                if text:
                    segments.append(
                        Segment(
                            index=len(segments) + 1,
                            speaker=current_speaker.lower(),
                            text=text,
                        )
                    )
            buffer = []

        for line in lines:
            line = line.rstrip()
            if not line.strip():
                # Blank line => flush current segment
                flush()
                continue
            m = SPEAKER_LINE.match(line)
            if m:
                flush()
                current_speaker = m.group(1).strip()
                rest = m.group(2).strip()
                if rest:
                    buffer.append(rest)
            else:
                if current_speaker:
                    buffer.append(line.strip())
        flush()
        return segments


def load_speaker_voice_map(path_str: Optional[str], required: bool = False) -> Dict[str, str]:
    """JSON: { "daniel": "M3", "annabelle": "F3" }"""
    if not path_str:
        return {}
    path = Path(path_str)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Supertonic voice JSON missing: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"Supertonic voice JSON invalid: {err}") from err
    if not isinstance(data, dict):
        raise ValueError("Supertonic voice JSON must contain an object mapping")
    result: Dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        voice = ""
        if isinstance(value, str):
            voice = value.strip()
        elif isinstance(value, dict):
            preferred = value.get("voice") or value.get("id") or value.get("name")
            if isinstance(preferred, str):
                voice = preferred.strip()
        if voice:
            result[key.lower()] = voice
    if result:
        logger.info("Supertonic voices loaded for: %s", ", ".join(sorted(result.keys())))
    return result


def build_speaker_mapping(
    language: str,
    overrides: Optional[Dict[str, str]],
    default_male: str = DEFAULT_MALE_VOICE,
    default_female: str = DEFAULT_FEMALE_VOICE,
    male_aliases: Optional[List[str]] = None,
    female_aliases: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Return speaker -> Supertonic voice style mapping with sensible defaults."""
    default_male = (default_male or DEFAULT_MALE_VOICE).upper()
    default_female = (default_female or DEFAULT_FEMALE_VOICE).upper()
    male_aliases = male_aliases or DEFAULT_MALE_ALIASES
    female_aliases = female_aliases or DEFAULT_FEMALE_ALIASES

    mapping: Dict[str, str] = {}
    mapping["_default_male"] = default_male
    mapping["_default_female"] = default_female
    for alias in male_aliases:
        if alias:
            mapping[alias.lower()] = default_male
    for alias in female_aliases:
        if alias:
            mapping[alias.lower()] = default_female
    if overrides:
        for key, value in overrides.items():
            if isinstance(key, str) and isinstance(value, str) and value.strip():
                mapping[key.lower()] = value.strip()
    return mapping


def derive_speaker_key(name: str, mapping: Dict[str, str]) -> str:
    """Pick a voice style for a given speaker name using mapping + simple heuristics."""
    normalized = (name or "").strip().lower()
    male_default = mapping.get("male", mapping.get("_default_male", DEFAULT_MALE_VOICE))
    female_default = mapping.get("female", mapping.get("_default_female", DEFAULT_FEMALE_VOICE))
    if normalized in mapping:
        return mapping[normalized]

    female_markers = ("woman", "female", "frau", "ms", "mrs", "miss", "annabelle")
    male_markers = ("man", "male", "herr", "mr", "daniel")

    if any(marker in normalized for marker in female_markers) and "man" not in normalized:
        return female_default
    if any(marker in normalized for marker in male_markers):
        return male_default

    # Default fallback to male voice for unknowns
    return male_default


def parse_aliases(raw: Optional[str], defaults: List[str]) -> List[str]:
    """Convert a comma-separated alias string into a clean list."""
    if raw is None:
        return defaults
    aliases: List[str] = []
    for part in raw.split(","):
        cleaned = part.strip()
        if cleaned:
            aliases.append(cleaned)
    return aliases or defaults


class SupertonicSynthesizer:
    """Supertonic wrapper with a mock fallback."""

    def __init__(
        self,
        default_voice: str,
        speed: float,
        total_steps: int,
        max_chunk_length: int,
        silence_duration: float,
        mock: bool,
        speaker_voice_map: Dict[str, str],
    ):
        self.sample_rate = SUPERTONIC_SAMPLE_RATE_FALLBACK
        self.default_voice = (default_voice or DEFAULT_MALE_VOICE).upper()
        self.speed = speed
        self.total_steps = total_steps
        self.max_chunk_length = max_chunk_length
        self.silence_duration = silence_duration
        self.speaker_voice_map = {k.lower(): v for k, v in speaker_voice_map.items()}
        self.mock = mock or not HAS_SUPERTONIC
        self.tts: Optional[TTS] = None
        self.style_cache: Dict[str, Any] = {}

        if not self.mock:
            try:
                self.tts = TTS(auto_download=True)
                self.sample_rate = int(
                    getattr(self.tts, "sample_rate", SUPERTONIC_SAMPLE_RATE_FALLBACK)
                )
                logger.info(
                    "Supertonic ready (default voice=%s, sample_rate=%s)",
                    self.default_voice,
                    self.sample_rate,
                )
            except Exception as err:  # pragma: no cover
                logger.error("Supertonic init failed (%s)", err)
                self.mock = True
                self.tts = None

        if self.mock and not mock and HAS_SUPERTONIC:
            logger.warning("Supertonic backend unavailable or init failed – using mock silence.")

    def synthesize(self, text: str, speaker_name: str) -> AudioSegmentType:
        if not text.strip():
            return AudioSegment.silent(duration=250)
        if self.mock or self.tts is None:
            return self._mock_audio(text)

        voice_choice = self._voice_for_speaker(speaker_name)
        try:
            style = self._style_for_voice(voice_choice)
            wav, _ = self.tts.synthesize(
                text,
                voice_style=style,
                total_steps=self.total_steps,
                speed=self.speed,
                max_chunk_length=self.max_chunk_length,
                silence_duration=self.silence_duration,
            )
        except Exception as err:  # pragma: no cover
            logger.error("Supertonic synthesis failed for %s (%s)", speaker_name or "unknown", err)
            return self._mock_audio(text)

        return self._numpy_audio_to_segment(wav)

    def _voice_for_speaker(self, speaker_name: Optional[str]) -> str:
        if self.speaker_voice_map:
            return derive_speaker_key(speaker_name or "", self.speaker_voice_map)
        return self.default_voice

    def _style_for_voice(self, voice_name: str):
        if self.tts is None:
            raise RuntimeError("TTS backend not initialized")
        key = (voice_name or self.default_voice).upper()
        if key in self.style_cache:
            return self.style_cache[key]
        try:
            style = self.tts.get_voice_style(key)
        except Exception as err:
            if key != self.default_voice:
                logger.warning(
                    "Voice style %s unavailable (%s) – falling back to %s",
                    key,
                    err,
                    self.default_voice,
                )
                return self._style_for_voice(self.default_voice)
            raise
        self.style_cache[key] = style
        return style

    def _numpy_audio_to_segment(self, wav: Any) -> AudioSegmentType:
        wav_np = np.asarray(wav, dtype=np.float32)
        wav_np = np.squeeze(wav_np)
        wav_np = np.nan_to_num(wav_np, nan=0.0, posinf=1.0, neginf=-1.0)
        wav_np = np.clip(wav_np, -1.0, 1.0)
        audio_int16 = (wav_np * 32767).astype(np.int16)
        return AudioSegment(
            audio_int16.tobytes(),
            frame_rate=self.sample_rate,
            sample_width=2,
            channels=1,
        )

    def _mock_audio(self, text: str) -> AudioSegmentType:
        words = max(1, len(text.split()))
        seconds = min(8.0, 0.5 * words)
        return AudioSegment.silent(duration=int(seconds * 1000))


class PodcastAssembler:
    def __init__(self, pause_ms: int = 500):
        self.pause_ms = pause_ms

    def assemble(self, segments_audio: List[AudioSegmentType]) -> AudioSegmentType:
        total = AudioSegment.silent(duration=0)
        first = True
        for seg in segments_audio:
            if not first:
                total += AudioSegment.silent(duration=self.pause_ms)
            total += seg
            first = False
        return total


def export_webvtt(segments: List[Segment], path: Path):
    def fmt(ts: float) -> str:
        hours = int(ts // 3600)
        minutes = int((ts % 3600) // 60)
        secs = ts % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")

    # optional intro/outro duration
    intro_duration = getattr(export_webvtt, "intro_duration", 0.0)
    outro_duration = getattr(export_webvtt, "outro_duration", 0.0)

    with path.open("w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        idx = 1
        if intro_duration > 0.0:
            f.write(f"{idx}\n")
            f.write(f"00:00:00,000 --> {fmt(intro_duration)}\n")
            f.write(f"<v Music>Intro music\n\n")
            idx += 1
        for seg in segments:
            f.write(f"{idx}\n")
            f.write(
                f"{fmt(seg.start + intro_duration)} --> "
                f"{fmt(seg.end + intro_duration)}\n"
            )
            speaker = re.sub(r"\s+", "_", seg.speaker.title())
            f.write(f"<v {speaker}>{seg.text}\n\n")
            idx += 1
        if outro_duration > 0.0:
            last_end = segments[-1].end + intro_duration if segments else intro_duration
            f.write(f"{idx}\n")
            f.write(f"{fmt(last_end)} --> {fmt(last_end + outro_duration)}\n")
            f.write(f"<v Music>Outro music\n\n")


def main():
    if sys.version_info < MIN_PYTHON:
        logger.error(
            "Python %s.%s.%s required (detected %s.%s.%s)",
            *MIN_PYTHON,
            *sys.version_info[:3],
        )
        return 1
    if sys.version_info[:3] >= (3, 12, 0):
        logger.debug("Running on Python %s.%s.%s", *sys.version_info[:3])

    if AudioSegment is None:
        logger.error(
            "pydub not available – install requirements via `pip install -r requirements.txt`"
        )
        return 1
    if shutil.which("ffmpeg") is None:
        logger.warning(
            "ffmpeg not found on PATH – MP3 export will fail; install ffmpeg to enable MP3 output"
        )

    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Podcast Markdown -> Audio via Supertonic (English dialogue synthesis)"
    )
    parser.add_argument("input_file", help="Markdown file with dialogue")
    parser.add_argument(
        "--language", "-l", default=DEFAULT_LANGUAGE, help="Language code (en)"
    )
    parser.add_argument(
        "--output-dir", default="output_supertonic", help="Output directory"
    )
    parser.add_argument(
        "--output-prefix", default=None, help="Optional base name (default: input stem)"
    )
    parser.add_argument(
        "--pause-ms", type=int, default=600, help="Pause between segments (ms)"
    )
    parser.add_argument(
        "--mock", action="store_true", help="Force mock (no real synthesis, silence)"
    )
    parser.add_argument(
        "--tts-backend",
        choices=["supertonic"],
        default="supertonic",
        help="TTS backend to use (default: supertonic)",
    )
    parser.add_argument(
        "--supertonic-voice",
        default=DEFAULT_MALE_VOICE,
        help="Default Supertonic voice style (e.g., M3)",
    )
    parser.add_argument(
        "--supertonic-female-voice",
        default=DEFAULT_FEMALE_VOICE,
        help="Fallback voice style for female speakers (default: F3)",
    )
    parser.add_argument(
        "--male-aliases",
        default=",".join(DEFAULT_MALE_ALIASES),
        help="Comma-separated speaker names mapped to the default male voice (default: daniel,male,host)",
    )
    parser.add_argument(
        "--female-aliases",
        default=",".join(DEFAULT_FEMALE_ALIASES),
        help="Comma-separated speaker names mapped to the default female voice (default: annabelle,female,guest)",
    )
    parser.add_argument(
        "--supertonic-voices-json",
        default=None,
        help="JSON mapping speaker names to Supertonic voice styles (e.g., M3, F3)",
    )
    parser.add_argument(
        "--supertonic-speed",
        type=float,
        default=1.05,
        help="Playback speed multiplier for Supertonic (default: 1.05)",
    )
    parser.add_argument(
        "--supertonic-steps",
        type=int,
        default=5,
        help="Denoising steps for Supertonic (1-100, default: 5)",
    )
    parser.add_argument(
        "--supertonic-max-chars",
        type=int,
        default=300,
        help="Max characters per chunk before Supertonic auto-chunking",
    )
    parser.add_argument(
        "--supertonic-silence-sec",
        type=float,
        default=0.3,
        help="Silence inserted between internal chunks (seconds, default: 0.3)",
    )
    # Output / Struktur-Optionen
    parser.add_argument(
        "--export-wav",
        action="store_true",
        default=True,
        help="Export final WAV (disable with --no-export-wav)",
    )
    parser.add_argument(
        "--no-export-wav", action="store_false", dest="export_wav"
    )
    parser.add_argument(
        "--save-segments-wav",
        action="store_true",
        default=True,
        help="Save each segment as WAV (disable with --no-save-segments-wav)",
    )
    parser.add_argument(
        "--no-save-segments-wav", action="store_false", dest="save_segments_wav"
    )
    parser.add_argument(
        "--suppress-warnings",
        action="store_true",
        default=True,
        help="Suppress future/deprecation warnings (disable with --no-suppress-warnings)",
    )
    parser.add_argument(
        "--no-suppress-warnings", action="store_false", dest="suppress_warnings"
    )
    parser.add_argument(
        "--structured-output",
        action="store_true",
        default=True,
        help="Hierarchical layout: <out>/<language>/<topic>/(final|segments) "
        "(disable with --no-structured-output)",
    )
    parser.add_argument(
        "--no-structured-output", action="store_false", dest="structured_output"
    )
    parser.add_argument(
        "--reuse-existing-segments",
        action="store_true",
        default=True,
        help="Reuse existing segment WAVs when present "
        "(disable with --no-reuse-existing-segments)",
    )
    parser.add_argument(
        "--no-reuse-existing-segments",
        action="store_false",
        dest="reuse_existing_segments",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose logging (DEBUG)"
    )

    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    language = args.language.lower()
    if language not in SUPPORTED_LANGS:
        logger.warning(
            "Language %s untested – falling back to %s",
            language,
            DEFAULT_LANGUAGE,
        )
        language = DEFAULT_LANGUAGE

    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error("Input file missing: %s", input_path)
        return 1
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    base_name = args.output_prefix or input_path.stem

    # Prepare structured output layout if requested
    if args.structured_output:
        topic = base_name
        structured_base = output_root / language / topic
        final_dir = structured_base / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        segments_parent_dir = (
            structured_base / "segments" if args.save_segments_wav else None
        )
        if segments_parent_dir:
            segments_parent_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Structured output enabled: %s", structured_base)
    else:
        final_dir = output_root
        segments_parent_dir = (
            output_root / "segments_wav" if args.save_segments_wav else None
        )
        if segments_parent_dir and not segments_parent_dir.exists():
            segments_parent_dir.mkdir(parents=True, exist_ok=True)
        if args.save_segments_wav and not args.structured_output:
            logger.info(
                "Note: segment WAVs stored flat in %s/segments_wav. "
                "Use --structured-output for <out>/<lang>/<topic>/(final|segments)",
                output_root,
            )

    content = input_path.read_text(encoding="utf-8")
    parser_md = MarkdownDialogueParser()
    segments = parser_md.parse(content)
    if not segments:
        logger.error("No segments detected – aborting")
        return 1
    logger.info("%d segments detected", len(segments))

    if args.tts_backend != "supertonic":
        logger.error("Only the Supertonic backend is supported.")
        return 1

    # Supertonic voice mapping (speaker -> voice style)
    default_voice = (args.supertonic_voice or DEFAULT_MALE_VOICE).upper()
    default_female_voice = (args.supertonic_female_voice or DEFAULT_FEMALE_VOICE).upper()
    if args.supertonic_steps < 1 or args.supertonic_steps > 100:
        logger.error("--supertonic-steps must be between 1 and 100")
        return 1
    if args.supertonic_speed <= 0:
        logger.error("--supertonic-speed must be positive")
        return 1
    if args.supertonic_max_chars <= 0:
        logger.error("--supertonic-max-chars must be positive")
        return 1
    if args.supertonic_silence_sec < 0:
        logger.error("--supertonic-silence-sec must be >= 0")
        return 1

    try:
        supertonic_voice_map = load_speaker_voice_map(args.supertonic_voices_json)
    except (FileNotFoundError, ValueError) as err:
        logger.error("%s", err)
        return 1

    male_aliases = parse_aliases(args.male_aliases, DEFAULT_MALE_ALIASES)
    female_aliases = parse_aliases(args.female_aliases, DEFAULT_FEMALE_ALIASES)

    speaker_voice_map = build_speaker_mapping(
        language,
        supertonic_voice_map,
        default_male=default_voice,
        default_female=default_female_voice,
        male_aliases=male_aliases,
        female_aliases=female_aliases,
    )

    if not HAS_SUPERTONIC and not args.mock:
        detail = f" ({SUPERTONIC_IMPORT_ERROR})" if SUPERTONIC_IMPORT_ERROR else ""
        logger.error(
            "Supertonic backend unavailable%s. "
            "Install via `pip install supertonic` or run with --mock.",
            detail,
        )
        return 1

    if args.suppress_warnings:
        warnings.filterwarnings("ignore", category=FutureWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        logger.info("Suppressing future/deprecation warnings (--suppress-warnings)")

    synthesizer = SupertonicSynthesizer(
        default_voice=default_voice,
        speed=args.supertonic_speed,
        total_steps=args.supertonic_steps,
        max_chunk_length=args.supertonic_max_chars,
        silence_duration=args.supertonic_silence_sec,
        mock=args.mock,
        speaker_voice_map=speaker_voice_map,
    )

    if synthesizer.mock and not args.mock:
        logger.warning(
            "Falling back to mock synthesis. Check Supertonic installation or pass --mock explicitly."
        )

    assembler = PodcastAssembler(pause_ms=args.pause_ms)

    # Synthesis loop
    audio_segments: List[AudioSegmentType] = []
    current_time = 0.0
    segments_wav_dir: Optional[Path] = segments_parent_dir
    pad_width = max(3, len(str(len(segments))))

    try:
        for seg in segments:
            logger.debug(
                "Synthesize segment %d (%s) ...", seg.index, seg.speaker
            )
            safe_speaker = re.sub(
                r"[^a-zA-Z0-9_-]", "_", seg.speaker.lower()
            )
            seg_filename = (
                f"{base_name}_segment_{seg.index:0{pad_width}d}_{safe_speaker}.wav"
            )
            seg_path = (
                segments_wav_dir / seg_filename
                if segments_wav_dir is not None
                else None
            )

            audio: Optional[AudioSegmentType] = None
            if (
                seg_path
                and seg_path.exists()
                and args.reuse_existing_segments
                and segments_wav_dir is not None
            ):
                try:
                    audio = AudioSegment.from_file(str(seg_path))
                    logger.info("Reusing existing segment %s", seg_filename)
                except Exception as reuse_err:  # pragma: no cover
                    logger.warning(
                        "Could not reuse segment %s (%s) – regenerating",
                        seg_filename,
                        reuse_err,
                    )
                    audio = None

            if audio is None:
                audio = synthesizer.synthesize(seg.text, seg.speaker)
                logger.debug(
                    "Synthesized new audio for segment %d",
                    seg.index,
                )

            duration_sec = len(audio) / 1000.0
            seg.start = current_time
            seg.end = current_time + duration_sec
            current_time = seg.end + (args.pause_ms / 1000.0)
            audio_segments.append(audio)

            # Optional per-segment WAV export
            if segments_wav_dir is not None and seg_path is not None:
                if audio is not None and (
                    not seg_path.exists() or not args.reuse_existing_segments
                ):
                    try:
                        audio.export(str(seg_path), format="wav")
                    except Exception as e:  # pragma: no cover
                        logger.warning(
                            "Could not save segment %s (%s)", seg.index, e
                        )
    except KeyboardInterrupt:
        logger.warning("Interrupted by user – stopping synthesis early")
        return 1

    # Intro/Outro music (optional)
    intro_path = Path("intro/epic-metal.mp3")
    if intro_path.exists():
        intro_audio = AudioSegment.from_file(str(intro_path))
        outro_audio = intro_audio  # same audio for outro
        combined = assembler.assemble(audio_segments)
        final_audio = intro_audio + combined + outro_audio
        intro_duration_sec = len(intro_audio) / 1000.0
        outro_duration_sec = len(outro_audio) / 1000.0
        logger.info(
            "Intro/outro added: %s (%.1fs)",
            intro_path.name,
            intro_duration_sec,
        )
    else:
        combined = assembler.assemble(audio_segments)
        final_audio = combined
        intro_duration_sec = 0.0
        outro_duration_sec = 0.0

    # Export final assets
    mp3_path = final_dir / f"{base_name}.mp3"
    final_audio.export(str(mp3_path), format="mp3", bitrate="256k")
    logger.info("MP3 exported: %s (%.1fs)", mp3_path, len(final_audio) / 1000.0)

    if args.export_wav:
        wav_path = final_dir / f"{base_name}.wav"
        final_audio.export(str(wav_path), format="wav")
        logger.info("WAV exported: %s", wav_path)

    vtt_path = final_dir / f"{base_name}.vtt"
    export_webvtt.intro_duration = intro_duration_sec
    export_webvtt.outro_duration = outro_duration_sec
    export_webvtt(segments, vtt_path)
    logger.info("VTT exported: %s", vtt_path)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
