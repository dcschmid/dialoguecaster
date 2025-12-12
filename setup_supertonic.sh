#!/usr/bin/env bash
# Setup helper for the Supertonic podcast pipeline.
# Creates a virtualenv, installs deps, checks ffmpeg, and runs a mock smoke test.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
DEFAULT_VENV_NAME="supertonic_env"

log() {
    echo "==> $*"
}

# Pick a Python interpreter (prefer 3.11)
detect_python() {
    if command -v python3.11 >/dev/null 2>&1; then
        echo "python3.11"
    elif command -v python3 >/dev/null 2>&1; then
        echo "python3"
    else
        echo "python"  # fallback; may fail if not present
    fi
}

PYTHON_BIN="${PYTHON_BIN:-$(detect_python)}"
VENV_NAME="${VENV_NAME:-$DEFAULT_VENV_NAME}"
VENV_PATH="$PROJECT_ROOT/$VENV_NAME"

log "Using Python interpreter: $PYTHON_BIN"
log "Creating virtualenv: $VENV_PATH"
"$PYTHON_BIN" -m venv "$VENV_PATH"

# Activate the environment
# shellcheck disable=SC1090
source "$VENV_PATH/bin/activate"

log "Upgrading pip"
pip install --upgrade pip

log "Installing requirements"
pip install -r "$PROJECT_ROOT/requirements.txt"

# Check ffmpeg availability (needed for MP3 export)
if command -v ffmpeg >/dev/null 2>&1; then
    log "ffmpeg detected: $(command -v ffmpeg)"
else
    echo "⚠️  ffmpeg not found on PATH – MP3 export will fail. Install ffmpeg to enable MP3 output."
fi

# Optional mock smoke test (no real synthesis download)
SMOKE_INPUT="$PROJECT_ROOT/podscripts/decades/1980s.md"
SMOKE_OUT="$PROJECT_ROOT/out_setup_test"
if [[ -f "$SMOKE_INPUT" ]]; then
    log "Running mock smoke test (no model download)"
    python "$PROJECT_ROOT/generate_podcast.py" \
        "$SMOKE_INPUT" \
        --mock \
        --output-dir "$SMOKE_OUT" \
        --no-save-segments-wav \
        --no-export-wav
    log "Smoke test finished. Outputs in: $SMOKE_OUT"
else
    echo "ℹ️  Smoke test skipped (missing $SMOKE_INPUT)."
fi

log "Setup complete. Activate with: source \"$VENV_PATH/bin/activate\""
