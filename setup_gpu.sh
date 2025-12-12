#!/bin/bash

# GPU Setup Script for Piper / Markdown-to-Podcast
# Installs CUDA-enabled onnxruntime-gpu and verifies that Piper can access the CUDA provider.

set -euo pipefail

echo "=========================================="
echo "GPU Setup for Piper (onnxruntime-gpu)"
echo "=========================================="
echo ""

# Check if virtual environment is activated
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "❌ Error: No virtual environment detected."
    echo ""
    echo "Please activate your environment first, e.g.:"
    echo "  source podcast-tts-env/bin/activate"
    echo ""
    exit 1
fi

echo "✓ Virtual environment active: $VIRTUAL_ENV"
echo ""

# Check if nvidia-smi is available
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "⚠️  Warning: nvidia-smi not found."
    echo ""
    echo "This means either:"
    echo "  1. No NVIDIA GPU is available, or"
    echo "  2. NVIDIA drivers are not installed"
    echo ""
    echo "Installing CPU-only onnxruntime..."
    pip install --upgrade onnxruntime piper-tts
    echo ""
    echo "✓ CPU-only runtime installed."
    echo "  Run: python chatterbox_tts.py script.md --mock --output-dir out_mock"
    exit 0
fi

echo "✓ NVIDIA GPU detected"
echo ""

# GPU info
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
CUDA_VERSION=$(nvidia-smi | grep "CUDA Version" | awk '{print $9}')
DRIVER_VERSION=$(nvidia-smi | grep "Driver Version" | awk '{print $3}')

echo "GPU Information:"
echo "  Name:           $GPU_NAME"
echo "  Driver Version: $DRIVER_VERSION"
echo "  CUDA Version:   $CUDA_VERSION"
echo ""

echo "The PyPI onnxruntime-gpu wheels target CUDA 12.2+. Keep drivers up-to-date (>= 525.xx)."
echo ""
read -p "Install/upgrade onnxruntime-gpu now? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo ""
echo "Installing CUDA-enabled onnxruntime..."
pip install --upgrade onnxruntime-gpu piper-tts

echo ""
echo "=========================================="
echo "Verifying CUDA provider..."
echo "=========================================="
echo ""

python3 <<'EOF'
import sys
import onnxruntime as ort

providers = ort.get_available_providers()
print("Available providers:", providers)

if "CUDAExecutionProvider" not in providers:
    print("\n❌ CUDA provider missing – ensure the NVIDIA driver is >= 525.xx and reinstall onnxruntime-gpu.")
    sys.exit(1)

try:
    from piper import PiperVoice
except ImportError as err:
    print(f"\n⚠️ Piper not installed: {err}")
    sys.exit(2)

print("\n✓ CUDA provider detected. Piper can now run with --piper-use-cuda.")
EOF

VERIFY_STATUS=$?

echo ""
if [ $VERIFY_STATUS -eq 0 ]; then
    echo "=========================================="
    echo "✓ GPU Setup Complete!"
    echo "=========================================="
    echo ""
    echo "Run Piper with GPU acceleration via:"
    echo "  python chatterbox_tts.py script.md --piper-voice /path/to/voice.onnx --piper-use-cuda --output-dir output"
    echo ""
    echo "Need a voice? Download one with:"
    echo "  python -m piper.download_voices en_US-lessac-medium"
elif [ $VERIFY_STATUS -eq 2 ]; then
    echo "Install piper-tts manually via 'pip install --upgrade piper-tts' and rerun this script."
else
    echo "=========================================="
    echo "❌ GPU Setup Failed"
    echo "=========================================="
    echo ""
    echo "Possible issues:"
    echo "  - Driver too old for CUDA 12.2 wheels"
    echo "  - Multiple Python versions active (verify your venv)"
    echo "  - onnxruntime-gpu install failed (check pip output)"
    exit 1
fi
