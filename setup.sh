#!/bin/bash
# Setup script for DialogueCaster with KOKORO-TTS (English-only)

set -e

echo "╔══════════════════════════════════════════╗"
echo "║     DialogueCaster Setup (KOKORO-TTS)    ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

echo "📋 Checking prerequisites..."
echo "   Python version: $PYTHON_VERSION"

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo "❌ ERROR: Python 3.10+ required (detected $PYTHON_VERSION)"
    echo "   Please upgrade your Python version."
    exit 1
fi

if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -gt 12 ]; then
    echo "❌ ERROR: Python 3.13+ is NOT supported by KOKORO-TTS"
    echo "   Please use Python 3.10, 3.11, or 3.12"
    echo ""
    echo "   Recommended: Create a virtual environment with Python 3.12"
    echo "   conda create -n dialoguecaster python=3.12 -y"
    echo "   conda activate dialoguecaster"
    exit 1
fi

echo "   ✓ Python version OK"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "   ⚠️  ffmpeg not found (required for MP3 export)"
    echo "      Install with: sudo apt install ffmpeg (Ubuntu)"
    echo "                   brew install ffmpeg (macOS)"
else
    echo "   ✓ ffmpeg found"
fi

echo ""
echo "📦 Installing dependencies..."

# Core dependencies
pip install -r requirements.txt

echo "   ✓ Core dependencies installed"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           ✅ Setup Complete!             ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "🎙️  Quick Start:"
echo ""
echo "   Test with mock mode (no TTS needed):"
echo "   $ python generate_podcast.py podscripts/en/decades/1980s.md --mock"
echo ""
echo "   Real synthesis:"
echo "   $ python generate_podcast.py podscripts/en/decades/1980s.md"
echo ""
echo "🌍 Language mode:"
echo "   en      American English (default, only supported language)"
echo ""
echo "📝 Examples:"
echo "   $ python generate_podcast.py script.md"
echo ""
