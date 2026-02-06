#!/usr/bin/env bash
# Clone the ABCD dataset into data/abcd/ if not already present.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data/abcd"

if [ -d "$DATA_DIR/data" ]; then
    echo "ABCD dataset already present at $DATA_DIR"
    exit 0
fi

echo "Cloning ABCD dataset..."
git clone https://github.com/asappresearch/abcd.git "$DATA_DIR"
echo "Done. Dataset at $DATA_DIR/data/"
