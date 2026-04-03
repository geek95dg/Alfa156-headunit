#!/usr/bin/env bash
# BCM v8 — Alfa Romeo 156 Head Unit — x86 launcher
# Supports both Pygame (legacy) and HTML5/Tailwind frontend modes.
#
# Usage:
#   ./run_x86.sh                  # HTML5 frontend (default) — open http://localhost:5002
#   ./run_x86.sh --frontend       # Same as above (explicit)
#   ./run_x86.sh --pygame         # Legacy Pygame renderer
#   ./run_x86.sh --headless       # Backend only, no display (web viewer on :5002)
#   ./run_x86.sh --modules obd,dashboard   # Specific modules only

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

# Default mode: frontend (HTML5/Tailwind)
MODE="frontend"

# Build argument list
ARGS=("--platform" "x86")

# Parse our own flags before passing to main.py
PASSTHROUGH_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --pygame)
            MODE="pygame"
            ;;
        --frontend)
            MODE="frontend"
            ;;
        --headless)
            MODE="headless"
            ARGS+=("--headless")
            ;;
        *)
            PASSTHROUGH_ARGS+=("$arg")
            ;;
    esac
done

# Auto-detect headless if no DISPLAY and not explicitly set
if [ "$MODE" != "headless" ] && [ -z "${DISPLAY:-}" ]; then
    echo "[run_x86] No \$DISPLAY detected — using frontend mode (no Pygame)"
    MODE="frontend"
fi

# Set mode-specific flags
if [ "$MODE" = "frontend" ]; then
    ARGS+=("--frontend")
elif [ "$MODE" = "headless" ]; then
    ARGS+=("--frontend")
fi

# Append passthrough arguments
ARGS+=("${PASSTHROUGH_ARGS[@]}")

# Clean shutdown on SIGTERM/SIGINT
cleanup() {
    echo ""
    echo "[run_x86] Shutting down..."
    if [ -n "${PID:-}" ]; then
        kill -TERM "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    echo "[run_x86] Stopped."
}
trap cleanup SIGTERM SIGINT

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   BCM v8 — Alfa Romeo 156 Head Unit             ║"
echo "  ╠══════════════════════════════════════════════════╣"

if [ "$MODE" = "frontend" ]; then
    echo "  ║   Mode: HTML5/Tailwind Frontend                  ║"
    echo "  ║                                                  ║"
    echo "  ║   Main display (7/8\" touch): http://localhost:5002║"
    echo "  ║   Small display (4.3\"):      http://localhost:5003║"
    echo "  ║   (AA + BT integrated on port 5002)              ║"
    echo "  ║                                                  ║"
    echo "  ║   Main: A1-A8 + Settings (3 themes)              ║"
    echo "  ║   Small: Stats carousel + reverse camera         ║"
elif [ "$MODE" = "pygame" ]; then
    echo "  ║   Mode: Pygame Renderer (legacy)                 ║"
    echo "  ║                                                  ║"
    echo "  ║   Dashboard:    Pygame window (800x480)          ║"
    echo "  ║   Web Viewer:   http://localhost:5002             ║"
    echo "  ║   (AA + BT integrated on port 5002)              ║"
elif [ "$MODE" = "headless" ]; then
    echo "  ║   Mode: Headless (backend + web frontend)        ║"
    echo "  ║                                                  ║"
    echo "  ║   Dashboard:    http://localhost:5002             ║"
    echo "  ║   (AA + BT integrated on port 5002)              ║"
fi

echo "  ╚══════════════════════════════════════════════════╝"
echo ""

python3 main.py "${ARGS[@]}" &
PID=$!
wait "$PID"
