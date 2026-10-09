#!/usr/bin/env bash
# ==============================================================================
# build_macos_vpcd.sh
# Compiles the open-source ifd-vpcd driver into a native macOS driver bundle:
# /usr/local/libexec/SmartCardServices/drivers/ifd-vpcd.bundle
# Compatible with macOS Big Sur, Monterey, Ventura, Sonoma, Sequoia (Apple Silicon & Intel)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${ROOT_DIR}/build_vpcd"
BUNDLE_DIR="${BUILD_DIR}/ifd-vpcd.bundle"

echo "============================================================="
echo "  Building macOS ifd-vpcd Driver Bundle"
echo "  Target: /usr/local/libexec/SmartCardServices/drivers/ifd-vpcd.bundle"
echo "============================================================="

# 1. Ensure source files are available
SRC_DIR="/tmp/vsmartcard/virtualsmartcard"
if [ ! -d "$SRC_DIR" ]; then
    echo "[Build] Cloning vsmartcard repository..."
    git clone --depth 1 https://github.com/frankmorgner/vsmartcard.git /tmp/vsmartcard
fi

rm -rf "$BUILD_DIR"
mkdir -p "${BUNDLE_DIR}/Contents/MacOS"

# 2. Compile native Mach-O bundle dynamic library
echo "[Build] Compiling ifd-vpcd with clang..."
clang -bundle -fPIC \
  -O2 \
  -DVPCDHOST='"127.0.0.1"' \
  -DVPCDSLOTS=2 \
  -DVPCDPORT=35963 \
  -DPCSCLITE_MAX_READERS_CONTEXTS=16 \
  -I"${SRC_DIR}/src/ifd-vpcd" \
  -I"${SRC_DIR}/src/vpcd" \
  -I"${SRC_DIR}/MacOSX" \
  -I"${SRC_DIR}/src/pcsclite-vpcd/PCSC" \
  "${SRC_DIR}/src/ifd-vpcd/ifd-vpcd.c" \
  "${SRC_DIR}/src/vpcd/vpcd.c" \
  "${SRC_DIR}/src/vpcd/lock.c" \
  -o "${BUNDLE_DIR}/Contents/MacOS/libifd-vpcd.dylib"

# Also compile standalone libpcsclite_vpcd.dylib
clang -shared -fPIC \
  -O2 \
  -DVPCDHOST='"127.0.0.1"' \
  -DVPCDSLOTS=2 \
  -DVPCDPORT=35963 \
  -DPCSCLITE_MAX_READERS_CONTEXTS=16 \
  -I"${SRC_DIR}/src/pcsclite-vpcd" \
  -I"${SRC_DIR}/src/pcsclite-vpcd/PCSC" \
  -I"${SRC_DIR}/src/ifd-vpcd" \
  -I"${SRC_DIR}/src/vpcd" \
  -I"${SRC_DIR}/MacOSX" \
  "${SRC_DIR}/src/pcsclite-vpcd/winscard.c" \
  "${SRC_DIR}/src/ifd-vpcd/ifd-vpcd.c" \
  "${SRC_DIR}/src/vpcd/vpcd.c" \
  "${SRC_DIR}/src/vpcd/lock.c" \
  -o "${BUILD_DIR}/libpcsclite_vpcd.dylib"

# 3. Create Info.plist with device VID/PID triggers
echo "[Build] Generating Info.plist..."
cat << 'EOF' > "${BUNDLE_DIR}/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>English</string>
	<key>CFBundleExecutable</key>
	<string>libifd-vpcd.dylib</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>ifd-vpcd</string>
	<key>CFBundlePackageType</key>
	<string>BNDL</string>
	<key>CFBundleSignature</key>
	<string>????</string>
	<key>CFBundleVersion</key>
	<string>0.8</string>
	<key>CFBundleShortVersionString</key>
	<string>0.8</string>
	<key>CFBundleIdentifier</key>
	<string>com.vsmartcard.virtualsmartcard.mac.ifd-vpcd</string>

	<key>ifdManufacturerString</key>
	<string>Virtual Smart Card Architecture</string>
	<key>ifdProductString</key>
	<string>Virtual PCD</string>

	<key>ifdCapabilities</key>
	<string>0x00000000</string>
	<key>ifdProtocolSupport</key>
	<string>0x00000001</string>
	<key>ifdVersionNumber</key>
	<string>0x00000001</string>

	<key>ifdVendorID</key>
	<array>
		<!-- DeCard Readers -->
		<string>0x0471</string>
		<string>0x0471</string>
		<!-- Feitian SCR501 / ROCKEY 531 -->
		<string>0x096e</string>
		<string>0x096e</string>
	</array>

	<key>ifdProductID</key>
	<array>
		<!-- DeCard T6 / T10 -->
		<string>0xa112</string>
		<string>0xa120</string>
		<!-- Feitian SCR501 -->
		<string>0x0603</string>
		<string>0x0601</string>
	</array>

	<key>ifdFriendlyName</key>
	<array>
		<string>Virtual PCD</string>
		<string>Virtual PCD</string>
		<string>Virtual PCD</string>
		<string>Virtual PCD</string>
	</array>
</dict>
</plist>
EOF

echo ""
echo "✅ Build completed successfully!"
echo "Bundle output: ${BUNDLE_DIR}"
echo ""
echo "To install into macOS SmartCardServices system-wide (requires sudo):"
echo "  sudo mkdir -p /usr/local/libexec/SmartCardServices/drivers"
echo "  sudo cp -r \"${BUNDLE_DIR}\" /usr/local/libexec/SmartCardServices/drivers/"
echo "  sudo killall -SIGKILL -m .com.apple.ifdreader 2>/dev/null || true"
echo ""
