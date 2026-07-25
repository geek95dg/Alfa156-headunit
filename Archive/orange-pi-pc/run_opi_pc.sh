#!/usr/bin/env bash
# BCM v8.5 — Alfa Romeo 156 Head Unit — Orange Pi PC 1.2 launcher
#
# This is a CONVENIENCE script for manual development/debugging.
# In production (test rig), the system uses systemd services:
#   - bcm-ignition-watcher.service  (starts at boot, watches GPIO)
#   - bcm-headunit.service          (started by ignition watcher)
#   - bcm-kiosk.service             (Chromium on HDMI)
#
# Usage:
#   ./run_opi_pc.sh                     # Full system (web frontend on HDMI)
#   ./run_opi_pc.sh --simulate          # Simulated ignition (no GPIO)
#   ./run_opi_pc.sh --no-watcher        # Start BCM directly (skip ignition)
#   ./run_opi_pc.sh --modules obd,dashboard  # Specific modules only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "[run_opi_pc] Using venv: $(which python3)"
elif [ -f "/opt/bcm/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source /opt/bcm/venv/bin/activate
    echo "[run_opi_pc] Using system venv: $(which python3)"
else
    echo "[run_opi_pc] No venv found, using system python3"
fi

# Parse arguments
NO_WATCHER=false
SIMULATE=false
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --no-watcher)
            NO_WATCHER=true
            ;;
        --simulate)
            SIMULATE=true
            ;;
        *)
            PASSTHROUGH_ARGS+=("$arg")
            ;;
    esac
done

# Clean shutdown
cleanup() {
    echo ""
    echo "[run_opi_pc] Shutting down..."
    if [ -n "${PID:-}" ]; then
        kill -TERM "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    echo "[run_opi_pc] Stopped."
}
trap cleanup SIGTERM SIGINT

# Banner
echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   BCM v8.5 — Alfa Romeo 156 Head Unit           ║"
echo "  ║   Platform: Orange Pi PC 1.2 (H3, 1GB RAM)      ║"
echo "  ╠══════════════════════════════════════════════════╣"

if [ "$NO_WATCHER" = true ]; then
    echo "  ║   Mode: Direct start (no ignition watcher)       ║"
    echo "  ║   Web frontend: http://localhost:5002             ║"
    echo "  ║   Small display: http://localhost:5003            ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo ""

    python3 main.py \
        --platform opi_pc \
        --config config/bcm_config_opi_pc.yaml \
        --frontend \
        "${PASSTHROUGH_ARGS[@]}" &
    PID=$!
    wait "$PID"
else
    if [ "$SIMULATE" = true ]; then
        echo "  ║   Mode: Ignition watcher (SIMULATED GPIO)       ║"
        echo "  ║   Create /tmp/bcm_ignition_on to start BCM      ║"
        echo "  ║   Remove /tmp/bcm_ignition_on to stop BCM       ║"
    else
        echo "  ║   Mode: Ignition watcher (real GPIO)             ║"
        echo "  ║   Waiting for 12V ignition signal on GPIO...     ║"
    fi
    echo "  ╚══════════════════════════════════════════════════╝"
    echo ""

    WATCHER_ARGS=(
        --config config/bcm_config_opi_pc.yaml
        --service "bcm-headunit.service"
    )
    if [ "$SIMULATE" = true ]; then
        WATCHER_ARGS+=(--simulate)
    fi

    python3 -m src.power.ignition_watcher "${WATCHER_ARGS[@]}" &
    PID=$!
    wait "$PID"
fi
