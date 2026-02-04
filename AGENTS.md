# AGENTS.md - DialogueCaster Development Guide

This file contains essential information for agentic coding agents working on the DialogueCaster project.

## Build/Lint/Test Commands

### Core Commands
```bash
# Install dependencies
pip install -r requirements.txt

# Run main script with mock mode (fast test)
python generate_podcast.py podscripts/decades/1980s.md --mock --output-dir out_test

# Run with real synthesis (downloads models on first run)
python generate_podcast.py podscripts/decades/1980s.md --output-dir out_real

# Check project setup
python setup_check.py
```

### Testing
```bash
# Run all tests
pytest

# Run single test file
pytest tests/test_cli_mock.py

# Run specific test function
pytest tests/test_cli_mock.py::test_cli_mock_exports_vtt

# Run tests with verbose output
pytest -v

# Run tests in mock mode (faster)
pytest -v -k mock
```

### Linting and Formatting
```bash
# Check code style with ruff
ruff check .

# Auto-fix with ruff
ruff check --fix .

# Format code with black
black .

# Check black formatting
black --check .
```

## Code Style Guidelines

### Formatting
- **Line length**: 120 characters (configured in pyproject.toml)
- **Formatter**: Black (line-length = 120)
- **Linter**: Ruff (E, W, F rules enabled)

### Import Organization
```python
# Standard library imports first
import os
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING, Any

# Third-party imports
import numpy as np
import subprocess
from PIL import Image
from dotenv import load_dotenv

# Conditional imports with proper fallbacks
if TYPE_CHECKING:
    from pydub import AudioSegment as AudioSegmentType
    from supertonic import TTS
else:
    AudioSegmentType = Any
    TTS = Any

# Try-except for optional dependencies
try:
    from supertonic import TTS as _TTS_Runtime
    HAS_SUPERTONIC = True
except Exception as err:
    HAS_SUPERTONIC = False
    SUPERTONIC_IMPORT_ERROR = err
```

### Type Annotations
- Use `from typing import` for all type hints
- Use `TYPE_CHECKING` for circular imports
- Prefer `Optional[str]` over `str | None` for compatibility
- Use dataclasses for structured data
- Include return types for all public functions

### Naming Conventions
- **Functions**: `snake_case` with descriptive names
- **Classes**: `PascalCase` (e.g., `SupertonicSynthesizer`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_LANGUAGE`)
- **Variables**: `snake_case`
- **File names**: `snake_case.py`
- **Private methods**: prefix with `_` (e.g., `_mock_audio`)

### Error Handling
```python
# Validate inputs early
if not path.exists():
    logger.error("Input file missing: %s", path)
    return 1

# Use try-except for external dependencies
try:
    style = self.tts.get_voice_style(key)
except Exception as err:
    logger.warning("Voice style %s unavailable (%s)", key, err)
    return self._style_for_voice(self.default_voice)

# Graceful fallbacks for optional features
if not HAS_SUPERTONIC and not args.mock:
    logger.error("Supertonic backend unavailable. Install or use --mock.")
    return 1
```

### Logging
- Use the configured logger: `logger.info()`, `logger.warning()`, `logger.error()`, `logger.debug()`
- Include relevant context in log messages
- Use structured logging with parameters (not f-strings in format string)
- Debug level for detailed synthesis information

### Constants and Configuration
- Define constants at module level (e.g., `DEFAULT_LANGUAGE = "en"`)
- Use environment variables with `load_dotenv()`
- Centralize configuration in argument parser
- Provide sensible defaults for all options

### CLI Design Patterns
- Use `argparse.ArgumentParser` for CLI interface
- Group related options with descriptive help text
- Include validation for all numeric inputs
- Support both structured and flat output layouts
- Provide mock mode for testing without external dependencies

### File I/O
- Use `pathlib.Path` for all file operations
- Specify encoding explicitly (`encoding="utf-8"`)
- Create parent directories as needed: `path.mkdir(parents=True, exist_ok=True)`
- Handle file existence gracefully

### Audio Processing
- Use `pydub.AudioSegment` for audio manipulation
- Support both mock and real synthesis modes
- Export in multiple formats (MP3, WAV, WebVTT)
- Handle audio segment timing and pausing

### Testing Patterns
- Use `pytest` with `tmp_path` fixture for file operations
- Mock external dependencies with `monkeypatch`
- Test both success and error cases
- Include integration tests for CLI workflows
- Use `pytest` parameterization for multiple test cases

## Project Structure
```
generate_podcast.py      # Main CLI entry point
requirements.txt         # Python dependencies
pyproject.toml          # Black/Ruff configuration
tests/                   # Test suite
├── test_cli_mock.py    # CLI integration tests
├── test_mapping_fallbacks.py
├── test_scaling.py
└── test_sorting_algorithm.py
utils/                   # Helper utilities
├── genre_categorizer.py
└── image_utils.py
podscripts/             # Sample Markdown scripts
prompts/                # Prompt templates
Categories/             # Category definitions
```

## Key Dependencies
- **supertonic**: Local TTS synthesis (ONNX Runtime)
- **pydub**: Audio processing and MP3 export
- **Pillow**: Image processing for video export
- **numpy**: Numerical operations for audio data
- **ffmpeg**: Required for MP3/video export (system dependency)

## Development Workflow
1. Install dependencies: `pip install -r requirements.txt`
2. Run linting: `ruff check --fix . && black .`
3. Run tests: `pytest -v`
4. Test CLI: `python generate_podcast.py script.md --mock`
5. Verify real synthesis: `python generate_podcast.py script.md`
6. Check documentation updates when adding features

## Mock Mode Usage
Always test with `--mock` flag first to avoid downloading large models:
```bash
python generate_podcast.py script.md --mock --output-dir test_output
```

This enables fast iteration without external dependencies.