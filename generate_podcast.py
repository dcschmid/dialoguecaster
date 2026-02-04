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
import hashlib
import os
import shutil
import sys
import re
import random
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
    Any,
    Literal,
    TypedDict,
)
from dotenv import load_dotenv
import json
import numpy as np


# Custom Exception Hierarchy
class DialogueCasterError(Exception):
    """Base exception for DialogueCaster application."""
    pass


class ConfigurationError(DialogueCasterError):
    """Raised when there's a configuration problem."""
    pass


class SynthesisError(DialogueCasterError):
    """Raised when audio synthesis fails."""
    pass


class ValidationError(DialogueCasterError):
    """Raised when input validation fails."""
    pass


class FFmpegError(DialogueCasterError):
    """Raised when FFmpeg operations fail."""
    pass


class DependencyError(DialogueCasterError):
    """Raised when required dependencies are missing."""
    pass
import subprocess
from PIL import Image

AudioSegment: Any = None
try:
    from pydub import AudioSegment  # For combining segments & MP3 export
except Exception:  # pragma: no cover
    AudioSegment = None

if TYPE_CHECKING:
    from pydub import AudioSegment as AudioSegmentType
    from supertonic import TTS
else:
    AudioSegmentType = Any
    TTS = Any

# Supertonic (ONNX Runtime)
HAS_SUPERTONIC = False
SUPERTONIC_IMPORT_ERROR: Optional[Exception] = None
try:  # pragma: no cover
    from supertonic import TTS as _TTS_Runtime

    HAS_SUPERTONIC = True
    if not TYPE_CHECKING:
        TTS = _TTS_Runtime
except Exception as err:  # pragma: no cover
    SUPERTONIC_IMPORT_ERROR = err

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


class VoiceStyleConfig(TypedDict, total=False):
    """Configuration for voice style mapping."""
    voice: str
    id: str
    name: str


class SpeedConfig(TypedDict):
    """Configuration for speaker speed mapping."""
    speed: float


class AudioSegmentCache:
    """Cache for audio segments to avoid re-synthesis."""
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_key(self, text: str, speaker: str, voice: str, speed: float) -> str:
        """Generate cache key based on content and parameters."""
        content = f"{text}|{speaker}|{voice}|{speed}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def get_cached_segment(self, text: str, speaker: str, voice: str, speed: float) -> Optional[AudioSegmentType]:
        """Get cached audio segment if available."""
        cache_key = self._get_cache_key(text, speaker, voice, speed)
        cache_file = self.cache_dir / f"{cache_key}.wav"
        
        if cache_file.exists():
            try:
                if AudioSegment is not None:
                    return AudioSegment.from_file(str(cache_file))
            except Exception as err:
                logger.debug("Failed to load cached segment: %s", err)
        return None
    
    def cache_segment(self, text: str, speaker: str, voice: str, speed: float, segment: AudioSegmentType) -> None:
        """Cache an audio segment."""
        if AudioSegment is None:
            return
            
        cache_key = self._get_cache_key(text, speaker, voice, speed)
        cache_file = self.cache_dir / f"{cache_key}.wav"
        
        try:
            segment.export(str(cache_file), format="wav")
            logger.debug("Cached segment: %s", cache_key[:8])
        except Exception as err:
            logger.debug("Failed to cache segment: %s", err)
    
    def clear_cache(self) -> None:
        """Clear all cached segments."""
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.glob("*.wav"):
                try:
                    cache_file.unlink()
                except Exception as err:
                    logger.debug("Failed to delete cache file %s: %s", cache_file, err)


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
            voice_config: VoiceStyleConfig = value  # type: ignore
            preferred = voice_config.get("voice") or voice_config.get("id") or voice_config.get("name")
            if isinstance(preferred, str):
                voice = preferred.strip()
        if voice:
            result[key.lower()] = voice
    if result:
        logger.info("Supertonic voices loaded for: %s", ", ".join(sorted(result.keys())))
    return result


def load_speaker_speed_map(path_str: Optional[str]) -> Dict[str, float]:
    """JSON: { "daniel": 0.94, "annabelle": 0.92 }"""
    if not path_str:
        return {}
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Supertonic speed JSON missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"Supertonic speed JSON invalid: {err}") from err
    if not isinstance(data, dict):
        raise ValueError("Supertonic speed JSON must contain an object mapping")
    result: Dict[str, float] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        try:
            speed_val = float(value)
        except (TypeError, ValueError):
            continue
        if speed_val > 0:
            result[key.lower()] = speed_val
    if result:
        logger.info("Supertonic speeds loaded for: %s", ", ".join(sorted(result.keys())))
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
        speaker_speed_map: Optional[Dict[str, float]] = None,
        cache_dir: Optional[Path] = None,
    ):
        self.sample_rate = SUPERTONIC_SAMPLE_RATE_FALLBACK
        self.default_voice = (default_voice or DEFAULT_MALE_VOICE).upper()
        self.speed = speed
        self.total_steps = total_steps
        self.max_chunk_length = max_chunk_length
        self.silence_duration = silence_duration
        self.speaker_voice_map = {k.lower(): v for k, v in speaker_voice_map.items()}
        self.speaker_speed_map: Dict[str, float] = {}
        for key, value in (speaker_speed_map or {}).items():
            try:
                speed_val = float(value)
            except (TypeError, ValueError):
                continue
            if speed_val > 0:
                self.speaker_speed_map[key.lower()] = speed_val
        self.mock = mock or not HAS_SUPERTONIC
        self.tts: Optional[TTS] = None
        self.style_cache: Dict[str, Any] = {}
        
        # Initialize audio cache
        if cache_dir:
            self.cache = AudioSegmentCache(cache_dir)
        else:
            self.cache = None

        if not self.mock:
            try:
                self.tts = TTS(auto_download=True)
                self.sample_rate = int(getattr(self.tts, "sample_rate", SUPERTONIC_SAMPLE_RATE_FALLBACK))
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
        
        voice_choice = self._voice_for_speaker(speaker_name)
        spk = (speaker_name or "").strip().lower()
        speed = self.speaker_speed_map.get(spk, self.speed)
        
        # Check cache first
        if self.cache and not self.mock:
            cached_segment = self.cache.get_cached_segment(text, spk, voice_choice, speed)
            if cached_segment:
                logger.debug("Using cached segment for %s", spk)
                return cached_segment
        
        if self.mock or self.tts is None:
            audio = self._mock_audio(text)
        else:
            try:
                style = self._style_for_voice(voice_choice)
                wav, _ = self.tts.synthesize(
                    text,
                    voice_style=style,
                    total_steps=self.total_steps,
                    speed=speed,
                    max_chunk_length=self.max_chunk_length,
                    silence_duration=self.silence_duration,
                )
                audio = self._numpy_audio_to_segment(wav)
            except Exception as err:
                raise SynthesisError(
                    f"Supertonic synthesis failed for {speaker_name or 'unknown'}: {err}"
                ) from err
        
        # Cache the synthesized segment
        if self.cache and not self.mock:
            self.cache.cache_segment(text, spk, voice_choice, speed, audio)
        
        return audio

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
    def __init__(self, pause_ms: int = 500, pause_jitter_ms: int = 0, seed: int = 0):
        self.pause_ms = pause_ms
        self.pause_jitter_ms = pause_jitter_ms
        self._rng = random.Random(seed)

    def next_pause_duration(self) -> int:
        jitter = self._rng.randint(-self.pause_jitter_ms, self.pause_jitter_ms) if self.pause_jitter_ms else 0
        return max(250, self.pause_ms + jitter)

    def assemble(
        self, segments_audio: List[AudioSegmentType], pauses_ms: Optional[List[int]] = None
    ) -> AudioSegmentType:
        total = AudioSegment.silent(duration=0)
        first = True
        pause_iter = iter(pauses_ms or [])
        for seg in segments_audio:
            if not first:
                pause_duration = next(pause_iter, self.next_pause_duration())
                total += AudioSegment.silent(duration=pause_duration)
            total += seg
            first = False
        return total


def export_webvtt(segments: List[Segment], path: Path):
    def fmt(ts: float) -> str:
        hours = int(ts // 3600)
        minutes = int((ts % 3600) // 60)
        secs = ts % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")

    with path.open("w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for idx, seg in enumerate(segments, 1):
            f.write(f"{idx}\n")
            f.write(f"{fmt(seg.start)} --> {fmt(seg.end)}\n")
            speaker = re.sub(r"\s+", "_", seg.speaker.title())
            f.write(f"<v {speaker}>{seg.text}\n\n")


def validate_input_file(file_path: Path) -> None:
    """Validate input file for security and existence."""
    if not file_path.exists():
        raise ValidationError(f"Input file not found: {file_path}")
    
    if not file_path.is_file():
        raise ValidationError(f"Input path is not a file: {file_path}")
    
    # Security: Check file size (prevent extremely large files)
    file_size = file_path.stat().st_size
    max_size = 100 * 1024 * 1024  # 100MB limit
    if file_size > max_size:
        raise ValidationError(f"Input file too large: {file_size:,} bytes (max: {max_size:,})")
    
    # Security: Check file extension
    allowed_extensions = {'.md', '.txt', '.markdown'}
    if file_path.suffix.lower() not in allowed_extensions:
        raise ValidationError(
            f"Unsupported file extension: {file_path.suffix}. "
            f"Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Security: Check file content (basic validation)
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            raise ValidationError("Input file is empty")
        
        # Basic content validation - ensure it's text
        if len(content) > 10_000_000:  # 10M character limit
            raise ValidationError("Input file content too large")
            
    except UnicodeDecodeError:
        raise ValidationError("Input file is not valid UTF-8 text")
    except Exception as err:
        raise ValidationError(f"Error reading input file: {err}") from err


def validate_output_dir(output_dir: Path) -> None:
    """Validate output directory for security."""
    # Security: Normalize path to prevent directory traversal
    try:
        resolved_path = output_dir.resolve()
    except Exception as err:
        raise ValidationError(f"Invalid output path: {err}") from err
    
    # Security: Ensure we're not writing to system directories
    forbidden_patterns = ['/bin', '/sbin', '/usr', '/etc', '/sys', '/proc', '/dev']
    resolved_str = str(resolved_path)
    
    for pattern in forbidden_patterns:
        if resolved_str.startswith(pattern):
            raise ValidationError(f"Output directory not allowed: {resolved_path}")
    
    # Security: Check if parent directory exists and is writable
    try:
        parent = resolved_path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        
        # Test write permissions
        test_file = parent / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
    except Exception as err:
        raise ValidationError(f"Cannot write to output directory: {err}") from err


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for security."""
    if not filename:
        return "output"
    
    # Remove path separators and dangerous characters
    dangerous_chars = ['/', '\\', '..', '\0', '|', ';', '&', '$', '`', '(', ')', '[', ']', '{', '}', '<', '>', '"', "'"]
    sanitized = filename
    
    for char in dangerous_chars:
        sanitized = sanitized.replace(char, '_')
    
    # Remove control characters
    sanitized = ''.join(char for char in sanitized if ord(char) >= 32)
    
    # Limit length and ensure it's not empty
    sanitized = sanitized[:100]
    return sanitized or "output"


def validate_cli_arguments(args) -> None:
    """Validate CLI arguments for security and correctness."""
    if args.pause_ms < 0:
        raise ValidationError("Pause duration must be non-negative")
    
    if args.pause_ms > 10000:  # 10 second limit
        raise ValidationError("Pause duration too long (max: 10,000ms)")
    
    if args.supertonic_speed <= 0:
        raise ValidationError("Speech speed must be positive")
    
    if args.supertonic_speed > 10:  # Reasonable upper limit
        raise ValidationError("Speech speed too high (max: 10.0)")
    
    if args.supertonic_steps < 1 or args.supertonic_steps > 100:
        raise ValidationError("Supertonic steps must be between 1 and 100")
    
    # Security: Validate image file if provided
    if args.image_file:
        try:
            validate_image_file(args.image_file)
        except ValidationError:
            raise
        except Exception as err:
            raise ValidationError(f"Invalid image file: {err}") from err


def validate_image_file(image_path: str) -> bool:
    """Validate that the image file exists and is a supported format."""
    if not image_path:
        raise ValidationError("Image path cannot be empty")

    path = Path(image_path)
    if not path.exists():
        raise ValidationError(f"Image file not found: {path}")

    supported_formats = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
    if path.suffix.lower() not in supported_formats:
        raise ValidationError(
            f"Unsupported image format: {path.suffix}. Supported: {', '.join(supported_formats)}"
        )

    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception as err:
        raise ValidationError(f"Invalid image file {path}: {err}") from err

    path = Path(image_path)
    if not path.exists():
        logger.error("Image file not found: %s", path)
        return False

    supported_formats = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
    if path.suffix.lower() not in supported_formats:
        logger.error("Unsupported image format: %s. Supported: %s", path.suffix, ", ".join(supported_formats))
        return False

    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception as err:
        logger.error("Invalid image file %s: %s", path, err)
        return False


def create_video_with_static_image(
    image_path: str, audio_path: Path, output_path: Path, video_format: Literal["mp4", "avi", "mov"] = "mp4"
) -> bool:
    """Create a video file by combining a static image with audio using FFmpeg."""
    if not shutil.which("ffmpeg"):
        raise DependencyError("ffmpeg not found on PATH – required for video export")

    try:
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-loop",
            "1",  # Loop image
            "-i",
            image_path,  # Input image
            "-i",
            str(audio_path),  # Input audio
            "-c:v",
            "libx264",  # Video codec
            "-tune",
            "stillimage",  # Optimize for still images
            "-c:a",
            "aac",  # Audio codec
            "-b:a",
            "192k",  # Audio bitrate
            "-pix_fmt",
            "yuv420p",  # Pixel format for compatibility
            "-shortest",  # Finish when audio ends
            str(output_path),
        ]

        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Video exported: %s", output_path)
        return True

    except subprocess.CalledProcessError as err:
        raise FFmpegError(f"Video creation failed: {err.stderr}") from err
    except Exception as err:
        raise FFmpegError(f"Unexpected error during video creation: {err}") from err

    try:
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-loop",
            "1",  # Loop the image
            "-i",
            image_path,  # Input image
            "-i",
            str(audio_path),  # Input audio
            "-c:v",
            "libx264",  # Video codec
            "-tune",
            "stillimage",  # Optimize for still images
            "-c:a",
            "aac",  # Audio codec
            "-b:a",
            "192k",  # Audio bitrate
            "-pix_fmt",
            "yuv420p",  # Pixel format for compatibility
            "-shortest",  # Finish when audio ends
            str(output_path),
        ]

        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Video exported: %s", output_path)
        return True

    except subprocess.CalledProcessError as err:
        logger.error("Video creation failed: %s", err.stderr)
        return False
    except Exception as err:
        logger.error("Unexpected error during video creation: %s", err)
        return False


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
        logger.error("pydub not available – install requirements via `pip install -r requirements.txt`")
        return 1
    if shutil.which("ffmpeg") is None:
        logger.warning("ffmpeg not found on PATH – MP3 export will fail; install ffmpeg to enable MP3 output")

    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Podcast Markdown -> Audio via Supertonic (English dialogue synthesis)"
    )
    parser.add_argument("input_file", help="Markdown file with dialogue")
    parser.add_argument("--language", "-l", default=DEFAULT_LANGUAGE, help="Language code (en)")
    parser.add_argument("--output-dir", default="output_supertonic", help="Output directory")
    parser.add_argument("--output-prefix", default=None, help="Optional base name (default: input stem)")
    parser.add_argument("--pause-ms", type=int, default=750, help="Base pause between segments (ms)")
    parser.add_argument(
        "--pause-jitter-ms",
        type=int,
        default=120,
        help="Random jitter added/subtracted from pauses between speakers (ms, default: 120)",
    )
    parser.add_argument(
        "--pause-seed",
        type=int,
        default=0,
        help="Random seed for pause jitter to keep timings reproducible",
    )
    parser.add_argument("--mock", action="store_true", help="Force mock (no real synthesis, silence)")
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
        default=0.93,
        help="Playback speed multiplier for Supertonic (default: 0.93)",
    )
    parser.add_argument(
        "--supertonic-steps",
        type=int,
        default=10,
        help="Denoising steps for Supertonic (1-100, default: 10)",
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
        default=0.15,
        help="Silence inserted between internal chunks (seconds, default: 0.15)",
    )
    parser.add_argument(
        "--supertonic-speeds-json",
        default=None,
        help="JSON mapping speaker names to speed multipliers (e.g., 0.94, 0.92)",
    )
    # Output / Struktur-Optionen
    parser.add_argument(
        "--suppress-warnings",
        action="store_true",
        default=True,
        help="Suppress future/deprecation warnings (disable with --no-suppress-warnings)",
    )
    parser.add_argument("--no-suppress-warnings", action="store_false", dest="suppress_warnings")
    parser.add_argument(
        "--structured-output",
        action="store_true",
        default=True,
        help="Hierarchical layout: <out>/<language>/<topic>/(final|segments) " "(disable with --no-structured-output)",
    )
    parser.add_argument("--no-structured-output", action="store_false", dest="structured_output")
    parser.add_argument(
        "--reuse-existing-segments",
        action="store_true",
        default=True,
        help="Reuse existing segment WAVs when present " "(disable with --no-reuse-existing-segments)",
    )
    parser.add_argument(
        "--no-reuse-existing-segments",
        action="store_false",
        dest="reuse_existing_segments",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging (DEBUG)")
    
    # Caching Options
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Directory for audio segment caching (default: <output_dir>/.cache)",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear audio cache before synthesis",
    )
    
    # Video Export Options
    parser.add_argument(
        "--image-file", default=None, help="Path to static image file for video generation (e.g., cover.jpg)"
    )
    parser.add_argument(
        "--export-video", action="store_true", help="Export video file combining static image with audio"
    )
    parser.add_argument(
        "--video-format", default="mp4", choices=["mp4", "avi", "mov"], help="Video format for export (default: mp4)"
    )

    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Security: Validate CLI arguments
    try:
        validate_cli_arguments(args)
    except ValidationError as err:
        logger.error("Validation failed: %s", err)
        return 1

    language = args.language.lower()
    if language not in SUPPORTED_LANGS:
        logger.warning(
            "Language %s untested – falling back to %s",
            language,
            DEFAULT_LANGUAGE,
        )
        language = DEFAULT_LANGUAGE

    input_path = Path(args.input_file)
    
    # Security: Validate input file
    try:
        validate_input_file(input_path)
    except ValidationError as err:
        logger.error("Input validation failed: %s", err)
        return 1
    
    output_root = Path(args.output_dir)
    
    # Security: Validate output directory
    try:
        validate_output_dir(output_root)
    except ValidationError as err:
        logger.error("Output validation failed: %s", err)
        return 1
    output_root.mkdir(parents=True, exist_ok=True)

    base_name = args.output_prefix or input_path.stem

    # Setup cache directory
    cache_dir = Path(args.cache_dir) if args.cache_dir else output_root / ".cache"
    if args.clear_cache:
        cache = AudioSegmentCache(cache_dir)
        cache.clear_cache()
        logger.info("Cleared audio cache")

    # Prepare structured output layout if requested
    if args.structured_output:
        topic = base_name
        structured_base = output_root / language / topic
        final_dir = structured_base / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Structured output enabled: %s", structured_base)
    else:
        final_dir = output_root

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
    if args.pause_ms < 0:
        logger.error("--pause-ms must be non-negative")
        return 1
    if args.pause_jitter_ms < 0:
        logger.error("--pause-jitter-ms must be >= 0")
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
    try:
        supertonic_speed_map = load_speaker_speed_map(args.supertonic_speeds_json)
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
            "Supertonic backend unavailable%s. " "Install via `pip install supertonic` or run with --mock.",
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
        speaker_speed_map=supertonic_speed_map,
        cache_dir=cache_dir,
    )

    if synthesizer.mock and not args.mock:
        logger.warning("Falling back to mock synthesis. Check Supertonic installation or pass --mock explicitly.")

    assembler = PodcastAssembler(pause_ms=args.pause_ms, pause_jitter_ms=args.pause_jitter_ms, seed=args.pause_seed)

    # Synthesis loop
    audio_segments: List[AudioSegmentType] = []
    pauses_ms: List[int] = []
    current_time = 0.0

    try:
        for idx, seg in enumerate(segments):
            logger.debug("Synthesize segment %d (%s) ...", seg.index, seg.speaker)
            audio = synthesizer.synthesize(seg.text, seg.speaker)
            logger.debug(
                "Synthesized new audio for segment %d",
                seg.index,
            )

            duration_sec = len(audio) / 1000.0
            if idx > 0:
                pause_duration = assembler.next_pause_duration()
                pauses_ms.append(pause_duration)
                current_time += pause_duration / 1000.0
            seg.start = current_time
            seg.end = current_time + duration_sec
            current_time = seg.end
            audio_segments.append(audio)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user – stopping synthesis early")
        return 1
    except (SynthesisError, ValidationError, FFmpegError) as err:
        logger.error("Processing failed: %s", err)
        return 1
    except Exception as err:
        logger.error("Unexpected error during synthesis: %s", err)
        return 1

    # Assemble final podcast
    combined = assembler.assemble(audio_segments, pauses_ms=pauses_ms)

    # Export final assets
    mp3_path = final_dir / f"{base_name}.mp3"
    combined.export(str(mp3_path), format="mp3", bitrate="256k")
    logger.info("MP3 exported: %s (%.1fs)", mp3_path, len(combined) / 1000.0)

    vtt_path = final_dir / f"{base_name}.vtt"
    export_webvtt(segments, vtt_path)
    logger.info("VTT exported: %s", vtt_path)

    # Video export if requested
    if args.export_video:
        if not args.image_file:
            logger.error("--image-file required when --export-video is specified")
            return 1

        try:
            validate_image_file(args.image_file)

            video_path = final_dir / f"{base_name}.{args.video_format}"
            success = create_video_with_static_image(
                args.image_file, mp3_path, video_path, args.video_format
            )

            if not success:
                logger.error("Video export failed")
                return 1
        except (ValidationError, FFmpegError) as err:
            logger.error("Video processing failed: %s", err)
            return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
