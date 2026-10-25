#!/usr/bin/env bash
set -euo pipefail
VENTOBSERVE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export VENTOBSERVE_DIR
PLATFORM_DIR="${OPENEGIZ_DIR:-$VENTOBSERVE_DIR/openegiz}"
cd "$PLATFORM_DIR"
exec python3 "$VENTOBSERVE_DIR/integration/start-platform.py" --platform-dir "$PLATFORM_DIR" "$@"
