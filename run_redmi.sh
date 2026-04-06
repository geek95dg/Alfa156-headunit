#!/usr/bin/env bash
# BCM v8.5 — Alfa Romeo 156 Head Unit — Redmi Note 8 Pro (Ubuntu Touch) launcher
#
# This script launches BCM on a Redmi Note 8 Pro running Ubuntu Touch.
# The phone acts as the main 7" touchscreen display, with all GPIO-dependent
# modules offloaded to an Arduino sensor hub via USB-C OTG.
#
# Usage:
#   ./run_redmi.sh                     # Full system (HTML5 frontend)
#   ./run_redmi.sh --desk              # Desk testing (no sensor hub needed)
#   ./run_redmi.sh --modules obd,dashboard  # Specific modules only
#   ./run_redmi.sh --headless          # Backend only, web viewer on :5002
#
# Prerequisites:
#   - Ubuntu Touch installed on Redmi Note 8 Pro (begonia)
#   - Libertine container or native Python 3 environment
#   - USB-C OTG hub connected (for production use)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Detect environment ──────────────────────────────────────────────────────

# Check if running on Ubuntu Touch
IS_UT=false
if [ -d "/etc/ubuntu-touch-session.d" ] || [ -d "/android/data" ]; then
    IS_UT=true
fi

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "[run_redmi] Using venv: $(which python3)"
elif command -v python3 &>/dev/null; then
    echo "[run_redmi] Using system python3: $(which python3)"
else
    echo "[run_redmi] ERROR: Python 3 not found"
    exit 1
fi

# ── Parse arguments ─────────────────────────────────────────────────────────

MODE="frontend"
DESK_MODE=false
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --desk)
            DESK_MODE=true
            ;;
        --headless)
            MODE="headless"
            ;;
        *)
            PASSTHROUGH_ARGS+=("$arg")
            ;;
    esac
done

# Build argument list
ARGS=("--platform" "redmi" "--frontend")
ARGS+=("--config" "config/bcm_config_redmi.yaml")

if [ "$MODE" = "headless" ]; then
    ARGS+=("--headless")
fi

ARGS+=("${PASSTHROUGH_ARGS[@]}")

# ── Environment variables for Ubuntu Touch ──────────────────────────────────

if [ "$IS_UT" = true ]; then
    # Ubuntu Touch Halium environment
    export UBUNTU_TOUCH=1
    # PulseAudio socket on UT
    export PULSE_SERVER="unix:/run/user/$(id -u)/pulse/native"
fi

# ── Clean shutdown ──────────────────────────────────────────────────────────

cleanup() {
    echo ""
    echo "[run_redmi] Shutting down..."
    if [ -n "${PID:-}" ]; then
        kill -TERM "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    echo "[run_redmi] Stopped."
}
trap cleanup SIGTERM SIGINT

# ── Banner ──────────────────────────────────────────────────────────────────

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   BCM v8.5 — Alfa Romeo 156 Head Unit           ║"
echo "  ║   Platform: Redmi Note 8 Pro (Ubuntu Touch)      ║"
echo "  ╠══════════════════════════════════════════════════╣"

if [ "$DESK_MODE" = true ]; then
    echo "  ║   Mode: DESK TESTING (no sensor hub required)    ║"
    echo "  ║   Demo data generators active                    ║"
else
    echo "  ║   Mode: Production / Car Install                 ║"
    echo "  ║   Sensor hub: Arduino via USB-C OTG              ║"
fi

echo "  ║                                                  ║"
echo "  ║   Main display: http://localhost:5002             ║"
echo "  ║   Small display: http://localhost:5003            ║"
echo "  ║                                                  ║"
echo "  ║   Phone screen = 7\" touch (A1-A8 + Settings)     ║"
echo "  ║   Second screen via USB-C HDMI adapter (4.3\")    ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

if [ "$IS_UT" = true ]; then
    echo "[run_redmi] Running on Ubuntu Touch (Halium)"
else
    echo "[run_redmi] Not on Ubuntu Touch — using simulation mode"
fi

if [ "$DESK_MODE" = true ]; then
    echo "[run_redmi] Desk testing mode — all sensors simulated"
fi

echo "[run_redmi] Starting BCM..."
echo ""

python3 main.py "${ARGS[@]}" &
PID=$!
wait "$PID"
