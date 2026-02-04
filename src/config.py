"""Configuration and validation utilities for DialogueCaster."""
import argparse
from pathlib import Path
from typing import List, Optional, TypedDict

from .exceptions import ValidationError


class VoiceStyleConfig(TypedDict, total=False):
    """Configuration for voice style mapping."""
    voice: str
    id: str
    name: str


class SpeedConfig(TypedDict):
    """Configuration for speaker speed mapping."""
    speed: float


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
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception as err:
        raise ValidationError(f"Invalid image file {path}: {err}") from err


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


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Podcast Markdown -> Audio via Supertonic (English dialogue synthesis)"
    )
    parser.add_argument("input_file", help="Markdown file with dialogue")
    parser.add_argument("--language", "-l", default="en", help="Language code (en)")
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
        default="M3",
        help="Default Supertonic voice style (e.g., M3)",
    )
    parser.add_argument(
        "--supertonic-female-voice",
        default="F3",
        help="Fallback voice style for female speakers (default: F3)",
    )
    parser.add_argument(
        "--male-aliases",
        default="daniel,male,host",
        help="Comma-separated speaker names mapped to the default male voice (default: daniel,male,host)",
    )
    parser.add_argument(
        "--female-aliases",
        default="annabelle,female,guest",
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
        "--image-file",
        default=None,
        help="Path to static image file for video generation (e.g., cover.jpg)",
    )
    parser.add_argument(
        "--export-video",
        action="store_true",
        help="Export video file combining static image with audio",
    )
    parser.add_argument(
        "--video-format",
        default="mp4",
        choices=["mp4", "avi", "mov"],
        help="Video format for export (default: mp4)",
    )

    return parser
