#!/usr/bin/env bash
# ==============================================================================
# test_gp_mac.sh
# Diagnostic test runner for GlobalPlatform on macOS
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo "============================================================="
echo "  GlobalPlatform Diagnostic Test Runner (macOS)"
echo "============================================================="

# 1. Run Automated Pipeline Test Suite
echo "[Test 1] Running Automated Pipeline Unit Tests..."
python3 "${SCRIPT_DIR}/tools/test_mac_pipeline.py"

echo ""
# 2. Run GlobalPlatformPro via Direct Socket Wrapper
echo "[Test 2] Running GlobalPlatformPro (-info & -l)..."
if [ -f "${SCRIPT_DIR}/gp_mac.sh" ]; then
    "${SCRIPT_DIR}/gp_mac.sh" -info
    echo ""
    "${SCRIPT_DIR}/gp_mac.sh" -l
fi

echo ""
echo "============================================================="
echo "✅ Diagnostic completed successfully."
echo "============================================================="
