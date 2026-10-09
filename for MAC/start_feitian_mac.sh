#!/usr/bin/env bash
# ==============================================================================
# start_feitian_mac.sh
# macOS launcher for Feitian SCR501 / ROCKEY 531 PC/SC Bridge
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo "============================================================="
echo "  Starting Feitian SCR501 macOS PC/SC Bridge..."
echo "  Press Ctrl+C to stop."
echo "============================================================="

python3 "${SCRIPT_DIR}/scripts/feitian_mac_bridge.py" "$@"
