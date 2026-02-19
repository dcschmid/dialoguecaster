#!/usr/bin/env python3
"""DialogueCaster - Podcast Generator with KOKORO-TTS
----------------------------------------------------

Convert Markdown dialogue scripts into audio (MP3) plus WebVTT subtitles.

- 100% local with KOKORO-TTS (hexgrad/kokoro)
- Language: US English
- Dialogue format: "Name: Text" per line
- Configurable pauses between segments
- Outputs: MP3 + .vtt
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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING, Any, TypedDict
from dotenv import load_dotenv
import json

# Optional imports for audio processing
AudioSegment = None
try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None

# KOKORO-TTS (hexgrad/kokoro) - Primary TTS Backend
HAS_KOKORO = False
KOKORO_IMPORT_ERROR: Optional[Exception] = None
KPipeline = None
sf = None
np = None
try:
    from kokoro import KPipeline as _KPipeline
    import numpy as _np
    import soundfile as _sf

    HAS_KOKORO = True
    KPipeline = _KPipeline
    sf = _sf
    np = _np
except Exception as err:
    KOKORO_IMPORT_ERROR = err


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


class DependencyError(DialogueCasterError):
    """Raised when required dependencies are missing."""

    pass


# Text normalization mappings
# Applied for all text (safe punctuation normalization)
COMMON_REPLACEMENTS = {
    "\u201c": '"',  # left double quote (")
    "\u201d": '"',  # right double quote (")
    "\u2018": "'",  # left single quote (')
    "\u2019": "'",  # right single quote (')
    "\u201b": "'",  # apostrophe (')
    "\u2013": "-",  # en dash (–)
    "\u2014": "-",  # em dash (—)
    "\u2026": "...",  # ellipsis (…)
    "\u20ac": "Euro",  # euro sign (€)
    "\u00a3": "pounds",  # pound sign (£)
    "\u00a9": "(c)",  # copyright (©)
    "\u00ae": "(r)",  # registered trademark (®)
    "\u2122": "(tm)",  # trademark (™)
}

# Applied only for ASCII-only synthesis
ASCII_ONLY_REPLACEMENTS = {
    "\u00f0": "th",  # eth (ð)
    "\u00fe": "th",  # thorn (þ)
    "\u00e6": "ae",  # ash (æ)
    "\u0153": "oe",  # oe ligature (œ)
    "\u00f8": "o",  # o with stroke (ø)
    "\u00e5": "a",  # a with ring (å)
    "\u00e4": "ae",  # a umlaut (ä)
    "\u00f6": "oe",  # o umlaut (ö)
    "\u00fc": "ue",  # u umlaut (ü)
    "\u00df": "ss",  # eszett (ß)
}

# Pre-compiled translation table for O(n) text normalization
_COMMON_TRANSLATION_TABLE = str.maketrans(COMMON_REPLACEMENTS)
_ASCII_TRANSLATION_TABLE = str.maketrans(ASCII_ONLY_REPLACEMENTS)


def normalize_text(text: str, ascii_only: bool = True) -> str:
    """Normalize text by replacing unsupported characters with ASCII equivalents.

    Uses pre-compiled translation table for O(n) performance.

    Args:
        text: Input text to normalize
        ascii_only: If True, force ASCII-safe output (for English pipelines)

    Returns:
        Normalized ASCII text
    """
    # Always normalize punctuation/symbols first.
    normalized = text.translate(_COMMON_TRANSLATION_TABLE)

    if not ascii_only:
        return normalized

    # ASCII-only mode for strict pipelines.
    normalized = normalized.translate(_ASCII_TRANSLATION_TABLE)
    return "".join(char if ord(char) < 128 else " " for char in normalized)


if TYPE_CHECKING:
    from pydub import AudioSegment as AudioSegmentType
else:
    AudioSegmentType = Any

# Logging Setup
LOG_LEVEL = os.getenv("CHATTERBOX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dialoguecaster")

# =============================================================================
# Module Constants
# =============================================================================

# Language configuration (English-only)
DEFAULT_LANGUAGE = "en"
DEFAULT_LANGUAGE_NAME = "English (US)"
DEFAULT_LANG_CODE = "a"  # KOKORO-TTS lang_code for American English
DEFAULT_SAMPLE_RATE = 24000
MIN_PYTHON = (3, 10, 0)  # Minimum Python version for KOKORO-TTS

# Voice defaults (best quality voices for English)
BEST_VOICES = {"male": "am_michael", "female": "af_heart"}
DEFAULT_MALE_VOICE = "am_michael"
DEFAULT_FEMALE_VOICE = "af_heart"
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
        """Generate SHA256 cache key from synthesis parameters.

        The key includes all parameters that affect audio output, ensuring
        cached segments are only reused when they would produce identical audio.
        """
        content = f"{text}|{speaker}|{voice}|{speed}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get_cached_segment(self, text: str, speaker: str, voice: str, speed: float) -> Optional[AudioSegmentType]:
        """Retrieve cached audio segment if available.

        Returns:
            AudioSegment if cache hit, None if cache miss or load error.
        """
        cache_key = self._get_cache_key(text, speaker, voice, speed)
        cache_file = self.cache_dir / f"{cache_key}.wav"

        if cache_file.exists() and AudioSegment is not None:
            try:
                return AudioSegment.from_file(str(cache_file))
            except Exception as err:
                logger.debug("Failed to load cached segment: %s", err)
        return None

    def cache_segment(self, text: str, speaker: str, voice: str, speed: float, segment: AudioSegmentType) -> None:
        """Cache an audio segment with atomic write for safety.

        Uses temp file + os.replace() to prevent corrupted cache files on crash.
        """
        if AudioSegment is None:
            return

        cache_key = self._get_cache_key(text, speaker, voice, speed)
        cache_file = self.cache_dir / f"{cache_key}.wav"
        temp_file = self.cache_dir / f".{cache_key}.tmp.wav"

        try:
            segment.export(str(temp_file), format="wav")
            os.replace(temp_file, cache_file)
            logger.debug("Cached segment: %s", cache_key[:8])
        except Exception as err:
            logger.debug("Failed to cache segment: %s", err)
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

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
    """Represents a single dialogue segment with timing metadata.

    Attributes:
        index: 1-based segment position in the dialogue
        speaker: Speaker name (normalized to lowercase)
        text: The spoken text content
        start: Start time in seconds (populated during synthesis)
        end: End time in seconds (populated during synthesis)
    """

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


def _load_json_mapping(path_str: Optional[str], name: str, required: bool = False) -> Dict:
    """Generic JSON mapping loader.

    Args:
        path_str: Path to JSON file
        name: Human-readable name for error messages
        required: If True, raise error when file not found

    Returns:
        Parsed JSON dict or empty dict
    """
    if not path_str:
        return {}
    path = Path(path_str)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"{name} JSON missing: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"{name} JSON invalid: {err}") from err
    if not isinstance(data, dict):
        raise ValueError(f"{name} JSON must contain an object mapping")
    return data


def load_speaker_voice_map(path_str: Optional[str], required: bool = False) -> Dict[str, str]:
    """Load speaker voice mapping from JSON file.

    JSON format: { "daniel": "am_michael", "annabelle": "af_heart" }
    """
    data = _load_json_mapping(path_str, "Voice", required)
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
        logger.info("Voices loaded for: %s", ", ".join(sorted(result.keys())))
    return result


def load_speaker_speed_map(path_str: Optional[str]) -> Dict[str, float]:
    """Load speaker speed mapping from JSON file.

    JSON format: { "daniel": 0.95, "annabelle": 1.05 }
    """
    data = _load_json_mapping(path_str, "Speed", required=False)
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
        logger.info("Speeds loaded for: %s", ", ".join(sorted(result.keys())))
    return result


def build_speaker_mapping(
    overrides: Optional[Dict[str, str]],
    default_male: Optional[str] = None,
    default_female: Optional[str] = None,
    male_aliases: Optional[List[str]] = None,
    female_aliases: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Return speaker -> voice mapping with sensible defaults."""
    default_male = default_male or BEST_VOICES["male"]
    default_female = default_female or BEST_VOICES["female"]
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
    """Determine voice for a speaker using explicit mapping or gender heuristics.

    Resolution order:
        1. Exact match in mapping dict
        2. Gender detection from speaker name markers
        3. Default to male voice

    Args:
        name: Speaker name from dialogue script
        mapping: Speaker-to-voice mapping (from build_speaker_mapping)

    Returns:
        Voice identifier (e.g., "am_michael", "af_heart")
    """
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
    """Parse comma-separated alias string into a cleaned list.

    Args:
        raw: Comma-separated string (e.g., "daniel,male,host") or None
        defaults: Fallback list if raw is empty/None

    Returns:
        List of cleaned aliases, or defaults if parsing yields empty list
    """
    if raw is None:
        return defaults
    aliases: List[str] = []
    for part in raw.split(","):
        cleaned = part.strip()
        if cleaned:
            aliases.append(cleaned)
    return aliases or defaults


class KokoroSynthesizer:
    """KOKORO-TTS wrapper for US English synthesis."""

    def __init__(
        self,
        default_voice: Optional[str],
        speed: float,
        speaker_voice_map: Dict[str, str],
        speaker_speed_map: Optional[Dict[str, float]] = None,
        cache_dir: Optional[Path] = None,
        mock: bool = False,
    ):
        self.sample_rate = 24000  # KOKORO-TTS sample rate

        self.lang_code = DEFAULT_LANG_CODE
        self.default_male_voice = BEST_VOICES["male"]
        self.default_female_voice = BEST_VOICES["female"]
        self.default_voice = default_voice or self.default_male_voice

        self.speed = speed
        self.mock = mock or not HAS_KOKORO

        self.speaker_voice_map = {k.lower(): v for k, v in speaker_voice_map.items()}
        self.speaker_speed_map: Dict[str, float] = {}
        for key, value in (speaker_speed_map or {}).items():
            try:
                speed_val = float(value)
            except (TypeError, ValueError):
                continue
            if speed_val > 0:
                self.speaker_speed_map[key.lower()] = speed_val

        # Initialize audio cache
        if cache_dir:
            self.cache = AudioSegmentCache(cache_dir)
        else:
            self.cache = None

        # Initialize KPipeline (lazy - only when needed)
        self._pipeline = None

        if self.mock and not mock:
            logger.warning("KOKORO-TTS backend unavailable – using mock silence.")
            if KOKORO_IMPORT_ERROR:
                logger.warning("Install with: pip install kokoro>=0.9.4")
        else:
            logger.info(
                "KOKORO-TTS ready (language=%s, lang_code=%s, male=%s, female=%s)",
                DEFAULT_LANGUAGE_NAME,
                self.lang_code,
                self.default_male_voice,
                self.default_female_voice,
            )

    @property
    def pipeline(self):
        """Lazy initialization of KPipeline."""
        if self._pipeline is None and not self.mock and KPipeline is not None:
            logger.info("Initializing KPipeline with lang_code='%s'", self.lang_code)
            self._pipeline = KPipeline(lang_code=self.lang_code)
        return self._pipeline

    def synthesize(self, text: str, speaker_name: str) -> AudioSegmentType:
        """Synthesize audio from text using KOKORO-TTS."""
        # English-only mode uses ASCII-safe text normalization.
        ascii_only = True
        normalized_text = normalize_text(text, ascii_only=ascii_only)

        if not normalized_text.strip():
            logger.debug("Empty text after normalization, returning silence")
            require_audio()
            return AudioSegment.silent(duration=250)

        # Skip text that contains only symbols/punctuation (no speakable content)
        if not any(c.isalnum() for c in normalized_text):
            logger.debug("Text contains only symbols, returning silence: %s", normalized_text[:50])
            require_audio()
            return AudioSegment.silent(duration=100)

        # Warn about very long segments (may be slow)
        if len(normalized_text) > 2000:
            logger.warning(
                "Long segment detected (%d chars for speaker '%s') - synthesis may be slow",
                len(normalized_text),
                speaker_name,
            )

        voice_key = self._voice_for_speaker(speaker_name)
        spk = (speaker_name or "").strip().lower()
        speed = self.speaker_speed_map.get(spk, self.speed)

        # Check cache first (use normalized text for cache key)
        if self.cache and not self.mock:
            cached_segment = self.cache.get_cached_segment(normalized_text, spk, voice_key, speed)
            if cached_segment:
                logger.debug("Using cached segment for %s", spk)
                return cached_segment

        if self.mock:
            audio = self._mock_audio(normalized_text)
        else:
            try:
                logger.debug(
                    "Synthesizing: speaker='%s', voice='%s', lang='%s', text_len=%d",
                    speaker_name,
                    voice_key,
                    self.lang_code,
                    len(normalized_text),
                )
                audio = self._synthesize_direct(normalized_text, voice_key, speed)
            except Exception as err:
                logger.error("Synthesis failed for speaker '%s' with voice '%s': %s", speaker_name, voice_key, err)
                raise SynthesisError(f"KOKORO-TTS synthesis failed for {speaker_name or 'unknown'}: {err}") from err

        # Cache synthesized segment (using normalized text)
        if self.cache and not self.mock:
            self.cache.cache_segment(normalized_text, spk, voice_key, speed, audio)

        return audio

    def _synthesize_direct(self, text: str, voice: str, speed: float) -> AudioSegmentType:
        """Synthesize audio directly using KPipeline (no subprocess!)."""
        require_audio()

        if self.pipeline is None:
            raise SynthesisError("KPipeline not initialized")

        # Use temp file for audio output
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Generate audio using KPipeline
            logger.debug("Calling pipeline with voice='%s', speed=%.2f", voice, speed)
            audio_segments = []
            for i, result in enumerate(self.pipeline(text, voice=voice, speed=speed)):
                if result.audio is not None:
                    audio_segments.append(result.audio)
                else:
                    logger.debug(
                        "Segment %d returned no audio (text: %s)",
                        i,
                        result.graphemes if hasattr(result, "graphemes") else "N/A",
                    )

            if not audio_segments:
                # Provide more context for debugging
                logger.error(
                    "No audio generated (len=%d, voice=%s, text_sha256=%s)",
                    len(text),
                    voice,
                    hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
                )
                raise SynthesisError(f"No audio generated for voice '{voice}'. Text may be empty or voice unavailable.")

            # Concatenate all segments and save to temp file
            if sf is None or np is None:
                raise DependencyError("soundfile or numpy not available")

            combined_audio = np.concatenate(audio_segments)
            sf.write(tmp_path, combined_audio, self.sample_rate)

            # Load as AudioSegment
            audio = AudioSegment.from_wav(tmp_path)
            return audio

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _voice_for_speaker(self, speaker_name: Optional[str]) -> str:
        """Pick the best voice for a speaker based on language and gender detection."""
        normalized = (speaker_name or "").strip().lower()

        # 1. Check explicit voice mapping first
        if self.speaker_voice_map and normalized in self.speaker_voice_map:
            return self.speaker_voice_map[normalized]

        # 2. Detect gender from speaker name and use best voice for language
        if self._is_female_speaker(normalized):
            return self.default_female_voice
        else:
            return self.default_male_voice

    def _is_female_speaker(self, speaker_name: str) -> bool:
        """Detect if a speaker name indicates female gender."""
        female_markers = [
            "female",
            "woman",
            "girl",
            "lady",
            "mrs",
            "ms",
            "miss",
            "her",
            "she",
            "annabelle",
            "sarah",
            "emma",
            "jessica",
            "nicole",
            "sara",
            "dora",
            "alice",
            "lily",
            "isabella",
            "bella",
            "sophia",
            "olivia",
            "xiaoxiao",
            "xiaoni",
            "alpha",
            "nezumi",
            "siwis",
            "heart",  # af_heart is the best female voice
        ]
        male_markers = [
            "male",
            "man",
            "boy",
            "mr",
            "his",
            "him",
            "he",
            "sir",
            "daniel",
            "michael",
            "george",
            "alex",
            "nicola",
            "kumo",
            "eric",
            "liam",
            "fable",
            "lewis",
            "santa",
            "puck",
            "echo",
            "omega",
            "yunxi",
        ]

        speaker_lower = speaker_name.lower()

        # Check for female markers
        for marker in female_markers:
            if marker in speaker_lower:
                # But exclude if male marker is also present
                has_male = any(m in speaker_lower for m in male_markers)
                if not has_male:
                    return True

        return False

    def _mock_audio(self, text: str) -> AudioSegmentType:
        """Generate mock audio (silence)."""
        require_audio()
        words = max(1, len(text.split()))
        seconds = min(8.0, 0.5 * words)
        return AudioSegment.silent(duration=int(seconds * 1000))


class PodcastAssembler:
    """Assembles individual audio segments into a final podcast track.

    Handles pause insertion with optional random jitter for more natural
    conversation flow. Uses seeded RNG for reproducible pause patterns.
    """

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
        require_audio()
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


def require_audio() -> None:
    """Raise DependencyError if pydub AudioSegment is not available."""
    if AudioSegment is None:
        raise DependencyError("pydub not available – install requirements via `pip install -r requirements.txt`")


def load_audio_file(
    audio_path: str,
    combined: AudioSegmentType,
    prepend: bool = True,
    disabled: bool = False,
    log_name: str = "audio",
) -> tuple[AudioSegmentType, float]:
    """Load audio file and append/prepend to combined audio.

    Args:
        audio_path: Path to audio file (MP3/WAV)
        combined: Existing combined audio
        prepend: If True, add audio before; if False, add after
        disabled: If True, skip loading
        log_name: Name for logging (e.g., "intro", "outro")

    Returns:
        Tuple of (combined_audio, duration_seconds)
    """
    if disabled or not audio_path:
        return combined, 0.0

    path = Path(audio_path)
    if not path.exists():
        # Only warn if user specified a non-default path
        if audio_path not in ("audio/intro.mp3", "audio/outro.mp3"):
            logger.warning("%s audio file not found: %s", log_name.title(), audio_path)
        return combined, 0.0

    require_audio()
    try:
        audio = AudioSegment.from_file(str(path))
        duration_sec = len(audio) / 1000.0
        if prepend:
            result = audio + combined
        else:
            result = combined + audio
        logger.info("%s audio added: %s (%.1fs)", log_name.title(), path.name, duration_sec)
        return result, duration_sec
    except Exception as err:
        logger.warning("Failed to load %s audio: %s", log_name, err)
        return combined, 0.0


def export_webvtt(segments: List[Segment], path: Path, time_offset: float = 0.0):
    """Export segments as WebVTT subtitles.

    Args:
        segments: List of Segment objects with start/end times
        path: Output file path
        time_offset: Seconds to add to all timestamps (e.g., for intro audio)
    """

    def fmt(ts: float) -> str:
        hours = int(ts // 3600)
        minutes = int((ts % 3600) // 60)
        secs = ts % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")

    with path.open("w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for idx, seg in enumerate(segments, 1):
            f.write(f"{idx}\n")
            f.write(f"{fmt(seg.start + time_offset)} --> {fmt(seg.end + time_offset)}\n")
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
    allowed_extensions = {".md", ".txt", ".markdown"}
    if file_path.suffix.lower() not in allowed_extensions:
        raise ValidationError(
            f"Unsupported file extension: {file_path.suffix}. Allowed: {', '.join(allowed_extensions)}"
        )

    # Security: Check file content (basic validation)
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            raise ValidationError("Input file is empty")

        # Basic content validation - ensure it's text
        if len(content) > 10_000_000:  # 10M character limit
            raise ValidationError("Input file content too large")

    except ValidationError:
        raise
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
    forbidden_patterns = ["/bin", "/sbin", "/usr", "/etc", "/sys", "/proc", "/dev"]
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
    dangerous_chars = ["/", "\\", "..", "\0", "|", ";", "&", "$", "`", "(", ")", "[", "]", "{", "}", "<", ">", '"', "'"]
    sanitized = filename

    for char in dangerous_chars:
        sanitized = sanitized.replace(char, "_")

    # Remove control characters
    sanitized = "".join(char for char in sanitized if ord(char) >= 32)

    # Limit length and ensure it's not empty
    sanitized = sanitized[:100]
    return sanitized or "output"


def validate_cli_arguments(args) -> None:
    """Validate CLI arguments for security and correctness."""
    if args.pause_ms < 0:
        raise ValidationError("Pause duration must be non-negative")

    if args.pause_ms > 10000:  # 10 second limit
        raise ValidationError("Pause duration too long (max: 10,000ms)")

    if args.kokoro_speed <= 0:
        raise ValidationError("Speech speed must be positive")

    if args.kokoro_speed > 10:  # Reasonable upper limit
        raise ValidationError("Speech speed too high (max: 10.0)")


def parse_cli_args() -> argparse.Namespace:
    """Build parser and return parsed CLI arguments."""
    parser = argparse.ArgumentParser(description="Podcast Markdown -> Audio via KOKORO-TTS (US English)")
    parser.add_argument("input_file", help="Markdown file with dialogue")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--output-prefix", default=None, help="Optional base name (default: input stem)")
    parser.add_argument("--pause-ms", type=int, default=620, help="Base pause between segments (ms, default: 620)")
    parser.add_argument(
        "--pause-jitter-ms",
        type=int,
        default=170,
        help="Random jitter added/subtracted from pauses between speakers (ms, default: 170)",
    )
    parser.add_argument(
        "--pause-seed",
        type=int,
        default=0,
        help="Random seed for pause jitter to keep timings reproducible",
    )
    parser.add_argument("--mock", action="store_true", help="Force mock (no real synthesis, silence)")
    parser.add_argument(
        "--kokoro-voice",
        default=None,
        help="Override default male voice (default: am_michael)",
    )
    parser.add_argument(
        "--kokoro-female-voice",
        default=None,
        help="Override default female voice (default: af_heart)",
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
        "--kokoro-voices-json",
        default=None,
        help="JSON mapping speaker names to KOKORO-TTS voices (e.g., am_michael, af_heart)",
    )
    parser.add_argument(
        "--kokoro-speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier for KOKORO-TTS (default: 1.0)",
    )
    parser.add_argument(
        "--kokoro-speeds-json",
        default=None,
        help="JSON mapping speaker names to speed multipliers (e.g., 0.99, 1.01)",
    )
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
        help="Hierarchical layout: <out>/en/<topic> (disable with --no-structured-output)",
    )
    parser.add_argument("--no-structured-output", action="store_false", dest="structured_output")
    parser.add_argument(
        "--reuse-existing-segments",
        action="store_true",
        default=True,
        help="Reuse existing segment WAVs when present (disable with --no-reuse-existing-segments)",
    )
    parser.add_argument(
        "--no-reuse-existing-segments",
        action="store_false",
        dest="reuse_existing_segments",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging (DEBUG)")
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
    parser.add_argument(
        "--intro-audio",
        default="audio/intro.mp3",
        help="Path to intro audio file (default: audio/intro.mp3, auto-detected)",
    )
    parser.add_argument(
        "--outro-audio",
        default="audio/outro.mp3",
        help="Path to outro audio file (default: audio/outro.mp3, auto-detected)",
    )
    parser.add_argument(
        "--no-intro",
        action="store_true",
        help="Disable automatic intro audio",
    )
    parser.add_argument(
        "--no-outro",
        action="store_true",
        help="Disable automatic outro audio",
    )
    return parser.parse_args()


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
    args = parse_cli_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Security: Validate CLI arguments
    try:
        validate_cli_arguments(args)
    except ValidationError as err:
        logger.error("Validation failed: %s", err)
        return 1

    output_lang = DEFAULT_LANGUAGE
    logger.info("Using language: %s (%s)", output_lang, DEFAULT_LANGUAGE_NAME)

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
        final_dir = output_root / output_lang / topic
        final_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Structured output enabled: %s", final_dir)
    else:
        final_dir = output_root

    content = input_path.read_text(encoding="utf-8")
    parser_md = MarkdownDialogueParser()
    segments = parser_md.parse(content)
    if not segments:
        logger.error("No segments detected – aborting")
        return 1
    logger.info("%d segments detected", len(segments))

    # KOKORO-TTS voice mapping
    # Only use CLI defaults if explicitly set, otherwise use English defaults.
    default_voice = args.kokoro_voice  # May be None, use default voice selection.
    default_female_voice = args.kokoro_female_voice  # May be None

    # Validation
    if args.kokoro_speed <= 0:
        logger.error("--kokoro-speed must be positive")
        return 1
    if args.pause_ms < 0:
        logger.error("--pause-ms must be non-negative")
        return 1
    if args.pause_jitter_ms < 0:
        logger.error("--pause-jitter-ms must be >= 0")
        return 1

    try:
        kokoro_voice_map = load_speaker_voice_map(args.kokoro_voices_json)
    except (FileNotFoundError, ValueError) as err:
        logger.error("%s", err)
        return 1
    try:
        kokoro_speed_map = load_speaker_speed_map(args.kokoro_speeds_json)
    except (FileNotFoundError, ValueError) as err:
        logger.error("%s", err)
        return 1

    male_aliases = parse_aliases(args.male_aliases, DEFAULT_MALE_ALIASES)
    female_aliases = parse_aliases(args.female_aliases, DEFAULT_FEMALE_ALIASES)

    # Build speaker voice mapping
    speaker_voice_map = build_speaker_mapping(
        kokoro_voice_map,
        default_male=default_voice,
        default_female=default_female_voice,
        male_aliases=male_aliases,
        female_aliases=female_aliases,
    )

    if args.suppress_warnings:
        warnings.filterwarnings("ignore", category=FutureWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        logger.info("Suppressing future/deprecation warnings (--suppress-warnings)")

    # Initialize KOKORO-TTS synthesizer
    if not HAS_KOKORO and not args.mock:
        detail = f" ({KOKORO_IMPORT_ERROR})" if KOKORO_IMPORT_ERROR else ""
        logger.error(
            "KOKORO-TTS backend unavailable%s. Install dependencies with `pip install -r requirements.txt`.",
            detail,
        )
        return 1

    synthesizer = KokoroSynthesizer(
        default_voice=default_voice,
        speed=args.kokoro_speed,
        speaker_voice_map=speaker_voice_map,
        speaker_speed_map=kokoro_speed_map,
        cache_dir=cache_dir,
        mock=args.mock,
    )

    if synthesizer.mock and not args.mock:
        logger.warning("Falling back to mock synthesis. Check KOKORO-TTS installation or pass --mock explicitly.")

    assembler = PodcastAssembler(pause_ms=args.pause_ms, pause_jitter_ms=args.pause_jitter_ms, seed=args.pause_seed)

    # Synthesis loop
    audio_segments: List[AudioSegmentType] = []
    pauses_ms: List[int] = []
    current_time = 0.0

    try:
        total_segments = len(segments)
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

            processed = idx + 1
            if processed % 25 == 0 or processed == total_segments:
                progress_pct = (processed / total_segments) * 100
                logger.info("Synthesis progress: %d/%d (%.1f%%)", processed, total_segments, progress_pct)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user – stopping synthesis early")
        return 1
    except (SynthesisError, ValidationError) as err:
        logger.error("Processing failed: %s", err)
        return 1
    except Exception as err:
        logger.error("Unexpected error during synthesis: %s", err)
        return 1

    # Assemble final podcast
    combined = assembler.assemble(audio_segments, pauses_ms=pauses_ms)

    # Load and add intro/outro audio (automatic if files exist)
    combined, intro_duration_sec = load_audio_file(
        args.intro_audio, combined, prepend=True, disabled=args.no_intro, log_name="intro"
    )
    combined, _ = load_audio_file(args.outro_audio, combined, prepend=False, disabled=args.no_outro, log_name="outro")

    # Export final assets
    mp3_path = final_dir / f"{base_name}.mp3"
    combined.export(str(mp3_path), format="mp3", bitrate="256k")
    logger.info("MP3 exported: %s (%.1fs)", mp3_path, len(combined) / 1000.0)

    vtt_path = final_dir / f"{base_name}.vtt"
    export_webvtt(segments, vtt_path, time_offset=intro_duration_sec)
    logger.info("VTT exported: %s (offset: +%.1fs for intro)", vtt_path, intro_duration_sec)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
