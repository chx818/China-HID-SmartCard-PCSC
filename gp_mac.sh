#!/usr/bin/env bash
# ==============================================================================
# gp_mac.sh
# GlobalPlatform CLI for macOS using DeCard & Feitian USB-HID readers.
# Direct user-mode execution bypassing PC/SC daemon and system drivers.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAR_PATH="${SCRIPT_DIR}/tools/gp.jar"
JAVA_CLASS_DIR="${SCRIPT_DIR}/tools"

# 1. Check Java
if ! command -v java >/dev/null 2>&1; then
    echo "❌ Error: 'java' command not found."
    echo "Please install Java (e.g., brew install openjdk@17)"
    exit 1
fi

# 2. Check if bridge server is running on port 35963
if ! nc -z 127.0.0.1 35963 2>/dev/null; then
    echo "⚠️ DeCard / Feitian bridge server is not running on 127.0.0.1:35963."
    echo "Starting bridge in background..."
    python3 "${SCRIPT_DIR}/scripts/decard_mac_bridge.py" >/dev/null 2>&1 &
    BRIDGE_PID=$!
    sleep 1.2
    if ! nc -z 127.0.0.1 35963 2>/dev/null; then
        echo "❌ Failed to connect to bridge server."
        echo "Please run './start_decard_mac.sh' manually in another terminal to view logs."
        exit 1
    fi
    echo "✅ Bridge server auto-started (PID: ${BRIDGE_PID})."
fi

# 3. Ensure GPDirect is compiled
if [ ! -f "${JAVA_CLASS_DIR}/GPDirect.class" ]; then
    echo "Compiling GPDirect wrapper..."
    javac -cp "${JAR_PATH}" "${JAVA_CLASS_DIR}/GPDirect.java"
fi

# 4. Execute GlobalPlatformPro command
java -cp "${JAR_PATH}:${JAVA_CLASS_DIR}" GPDirect "$@"
