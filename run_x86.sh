#!/usr/bin/env bash
# BCM v7 — Alfa Romeo 156 Head Unit — x86 launcher
# Auto-detects headless environment and activates venv if present.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "[run_x86] Using venv: $(which python3)"
else
    echo "[run_x86] No .venv found, using system python3"
fi

# Build argument list
ARGS=("--platform" "x86")

# Auto-detect headless (no DISPLAY set)
if [ -z "${DISPLAY:-}" ]; then
    echo "[run_x86] No \$DISPLAY detected — enabling --headless mode"
    ARGS+=("--headless")
fi

# Append any extra arguments passed to this script
ARGS+=("$@")

# Clean shutdown on SIGTERM/SIGINT
cleanup() {
    echo ""
    echo "[run_x86] Shutting down..."
    # Forward signal to the python process
    if [ -n "${PID:-}" ]; then
        kill -TERM "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    echo "[run_x86] Stopped."
}
trap cleanup SIGTERM SIGINT

echo "[run_x86] Starting BCM v7..."
echo "[run_x86] Dashboard WebViewer: http://localhost:5002"
echo "[run_x86] AA/BT Management:   http://localhost:5001"
echo "[run_x86] Android Auto (TCP):  port 5000 (autoapp)"
echo ""

python3 main.py "${ARGS[@]}" &
PID=$!
wait "$PID"
