"""Audio synthesis and caching components."""
import hashlib
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

import numpy as np

from .exceptions import SynthesisError, DependencyError

if TYPE_CHECKING:
    from pydub import AudioSegment as AudioSegmentType
    from supertonic import TTS
else:
    AudioSegmentType = "AudioSegment"
    TTS = "TTS"

logger = logging.getLogger(__name__)

# Constants
DEFAULT_SAMPLE_RATE = 24000

# Optional dependencies
AudioSegment = None
try:
    from pydub import AudioSegment  # For combining segments & MP3 export
except Exception:  # pragma: no cover
    AudioSegment = None

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


@dataclass
class Segment:
    """Dialogue segment with timing information."""
    index: int
    speaker: str
    text: str
    start: float = 0.0
    end: float = 0.0


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


class PodcastAssembler:
    """Assemble audio segments with pauses."""

    def __init__(self, pause_ms: int = 500, pause_jitter_ms: int = 0, seed: int = 0):
        self.pause_ms = pause_ms
        self.pause_jitter_ms = pause_jitter_ms
        self._rng = random.Random(seed)

    def next_pause_duration(self) -> int:
        jitter = (
            self._rng.randint(-self.pause_jitter_ms, self.pause_jitter_ms)
            if self.pause_jitter_ms
            else 0
        )
        return max(250, self.pause_ms + jitter)

    def assemble(
        self, segments_audio: List[AudioSegmentType], pauses_ms: Optional[List[int]] = None
    ) -> AudioSegmentType:
        """Assemble audio segments with pauses."""
        if AudioSegment is None:
            raise DependencyError("pydub not available – install requirements via `pip install -r requirements.txt`")

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
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.default_voice = (default_voice or "M3").upper()
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
        self.style_cache: Dict[str, any] = {}

        # Initialize audio cache
        if cache_dir:
            self.cache = AudioSegmentCache(cache_dir)
        else:
            self.cache = None

        if not self.mock:
            try:
                self.tts = TTS(auto_download=True)
                self.sample_rate = int(
                    getattr(self.tts, "sample_rate", DEFAULT_SAMPLE_RATE)
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
            logger.warning("Supertonic backend unavailable – using mock silence.")

    def synthesize(self, text: str, speaker_name: str) -> AudioSegmentType:
        """Synthesize audio from text."""
        if not text.strip():
            if AudioSegment is not None:
                return AudioSegment.silent(duration=250)
            else:
                raise DependencyError("AudioSegment not available")

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
        """Pick a voice style for a given speaker name."""
        if self.speaker_voice_map:
            normalized = (speaker_name or "").strip().lower()
            if normalized in self.speaker_voice_map:
                return self.speaker_voice_map[normalized]
        return self.default_voice

    def _style_for_voice(self, voice_name: str):
        """Get voice style from Supertonic."""
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

    def _numpy_audio_to_segment(self, wav) -> AudioSegmentType:
        """Convert numpy audio to pydub AudioSegment."""
        if AudioSegment is None:
            raise DependencyError("AudioSegment not available")

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
        """Generate mock audio (silence)."""
        if AudioSegment is None:
            raise DependencyError("AudioSegment not available")

        words = max(1, len(text.split()))
        seconds = min(8.0, 0.5 * words)
        return AudioSegment.silent(duration=int(seconds * 1000))
