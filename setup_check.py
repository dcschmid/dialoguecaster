#!/usr/bin/env python3
"""Project status & setup check (Supertonic edition)
====================================================

Verifies basic structure & dependencies for the local Supertonic ONNX pipeline.
"""

import os
import sys

def check_project_structure():
    """Validate required project structure."""
    print("🔍 PROJECT STRUCTURE CHECK")
    print("=" * 50)
    
    required_files = [
        "generate_podcast.py",
        "requirements.txt",
        "README.md",
        "LICENSE",
    ]
    
    missing_files = []
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path}")
            missing_files.append(file_path)
    
    print("\n📁 DIRECTORIES:")
    directories = ["podscripts", "output"]
    
    for directory in directories:
        if os.path.exists(directory):
            files = os.listdir(directory)
            print(f"✅ {directory}/ ({len(files)} files)")
        else:
            print(f"❌ {directory}/")
            missing_files.append(f"{directory}/")
    
    print("\n" + "=" * 50)
    
    if missing_files:
        print(f"⚠️ {len(missing_files)} missing files/directories:")
        for item in missing_files:
            print(f"   - {item}")
        return False
    else:
        print("🎉 Structure OK")
        return True

def check_dependencies():
    """Check installed runtime dependencies."""
    print("\n🔧 DEPENDENCY CHECK")
    print("=" * 50)
    
    dependencies = [
        ("pydub", "Audio Processing"),
        ("dotenv", "Environment Variables"),
        ("numpy", "Scientific Computing"),
        ("supertonic", "Supertonic TTS"),
        ("onnxruntime", "ONNX Runtime (CPU backend)"),
    ]
    
    missing_deps = []
    
    for module, description in dependencies:
        try:
            __import__(module)
            print(f"✅ {module} - {description}")
        except ImportError:
            print(f"❌ {module} - {description}")
            missing_deps.append(module)
    
    if missing_deps:
        print(f"\n⚠️ Missing dependencies: {', '.join(missing_deps)}")
        print("💡 Install with: pip install -r requirements.txt")
        return False
    else:
        print("\n🎉 All dependencies installed")
        return True

def show_quick_start():
    """Display quick start instructions (local, no API keys)."""
    print("\n🚀 QUICK START")
    print("=" * 50)
    print("1. Create Python virtual environment:")
    print("   python -m venv tts-env")
    print("   source tts-env/bin/activate  # Linux/Mac")
    print("   # or: tts-env\\Scripts\\activate  # Windows")
    print()
    print("2. Install dependencies:")
    print("   pip install -r requirements.txt")
    print()
    print("3. (Optional) create .env:")
    print("   cp .env.example .env  # optional defaults only")
    print()
    print("4. Mock test (no model download):")
    print("   python generate_podcast.py podscripts/decades/1980s.md --language en --mock --output-dir out_test")
    print()
    print("5. Real synthesis (first run downloads Supertonic models automatically):")
    print("   python generate_podcast.py podscripts/decades/1980s.md --language en --output-dir out_real")

def main():
    """Entry point."""
    print("🎙️ PODCAST TTS - PROJECT STATUS (SUPERTONIC)")
    print("=" * 60)
    
    structure_ok = check_project_structure()
    deps_ok = check_dependencies()
    
    show_quick_start()
    
    print("\n" + "=" * 60)
    
    if structure_ok and deps_ok:
        print("🎉 PROJECT READY – no API keys required")
        print("🎯 Next: run mock or real synthesis")
    else:
        print("⚠️ INCOMPLETE PROJECT SETUP")
        print("🔧 Follow instructions above to resolve")

if __name__ == "__main__":
    main()
