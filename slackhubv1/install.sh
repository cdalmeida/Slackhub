#!/usr/bin/env bash
set -euo pipefail

echo "🚀 Installing Slack Intelligence Hub..."
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not found. Please install Python 3.11+."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo "❌ Python 3.11+ required. Found Python $PYTHON_VERSION."
    exit 1
fi

echo "✓ Python $PYTHON_VERSION found"

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet

# Init DB
slack-hub db init

# Copy config template
if [ ! -f config/config.yaml ]; then
    cp config/config.example.yaml config/config.yaml
    echo "✓ Created config/config.yaml from template"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. source .venv/bin/activate"
echo "  2. slack-hub init          # Configure credentials"
echo "  3. slack-hub channels setup # Pick your channels"
echo "  4. slack-hub digest        # Run your first digest"
