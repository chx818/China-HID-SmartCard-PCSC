#!/usr/bin/env bash
# ==============================================================================
# start_decard_mac.sh
# macOS launcher for DeCard T6 / T10 Unified PC/SC Bridge
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo "============================================================="
echo "  Starting DeCard macOS Unified PC/SC Bridge..."
echo "  Press Ctrl+C to stop."
echo "============================================================="

python3 "${SCRIPT_DIR}/scripts/decard_mac_bridge.py" "$@"
