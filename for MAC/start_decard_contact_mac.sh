#!/usr/bin/env bash
# ==============================================================================
# start_decard_contact_mac.sh
# macOS launcher for DeCard T6 / T10 Contact Smart Card Bridge
# Priority: Contact Slot (ISO 7816) First
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo "============================================================="
echo "  Starting DeCard T6 / T10 Contact Smart Card Bridge..."
echo "  Slot Priority: Contact Slot First (ISO 7816-3 T=0 / T=1)"
echo "  Press Ctrl+C to stop."
echo "============================================================="

python3 "${SCRIPT_DIR}/scripts/decard_mac_bridge.py" --priority ContactFirst "$@"
