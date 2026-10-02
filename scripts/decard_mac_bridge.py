#!/usr/bin/env python3
"""
DeCard T6 / T10 Dual-Interface (Contact & Contactless) PC/SC Bridge for macOS.
Native Python implementation using libhidapi. Fully cross-platform (Apple Silicon & Intel).
No Windows DLLs required. Listens as TCP Server (default 127.0.0.1:35963) to serve both:
1. Direct GPTool / GPDirect.java sessions (bypassing PC/SC and system drivers)
2. macOS VPCD / ifd-vpcd driver for system-wide Apple SmartCardServices

Includes real-time background watchdog for:
- Card tap / insertion detection with hardware audio beep (beep on tap!)
- macOS desktop banner notifications
- Automatic card removal detection and RF carrier resetting
"""

import sys
import os
import time
import socket
import argparse
import threading
import subprocess
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mac_drivers.decard_hid import DeCardHIDDriver
from mac_drivers.mock_card import MockJavaCard

class DecardMacBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 35963, 
                 use_mock: bool = False, auto_mock: bool = True,
                 priority: str = "RfFirst", enable_notify: bool = True):
        self.host = host
        self.port = port
        self.use_mock = use_mock
        self.auto_mock = auto_mock
        self.priority = priority
        self.enable_notify = enable_notify
        self.driver = DeCardHIDDriver()
        self.mock_card = MockJavaCard() if (use_mock or auto_mock) else None
        self.active_medium = "None"
        self.current_atr = b""
        self.lock = threading.Lock()
        self.watchdog_running = True
        self.last_apdu_time = 0.0

    def log(self, tag: str, msg: str):
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{tag} {now}] {msg}")

    def _notify_macos(self, title: str, message: str):
        if not self.enable_notify:
            return
        try:
            cmd = f'display notification "{message}" with title "{title}" sound name "Glass"'
            subprocess.run(["osascript", "-e", cmd], capture_output=True, timeout=1)
        except Exception:
            pass

    def _card_watchdog_loop(self):
        """Active background watchdog detecting card insertion/removal with beep and notifications."""
        self.log("Watchdog", "Active Card Watchdog started (polling: 250ms, idle probe: 800ms)...")
        while self.watchdog_running:
            if self.use_mock:
                time.sleep(1.0)
                continue

            with self.lock:
                if self.active_medium == "None":
                    # 1. Probe for card insertion
                    detected = False
                    atr = None

                    if self.priority == "RfFirst":
                        ok, atr = self.driver.activate_rf_card()
                        if ok and atr:
                            self.active_medium = "Contactless"
                            detected = True
                        elif self.driver.contact_check_status():
                            atr = self.driver.contact_reset()
                            if atr:
                                self.active_medium = "Contact"
                                detected = True
                    else:
                        if self.driver.contact_check_status():
                            atr = self.driver.contact_reset()
                            if atr:
                                self.active_medium = "Contact"
                                detected = True
                        if not detected:
                            ok, atr = self.driver.activate_rf_card()
                            if ok and atr:
                                self.active_medium = "Contactless"
                                detected = True

                    if detected and atr:
                        self.current_atr = atr
                        self.driver.beep(10)  # Hardware Beep!
                        uid = self.driver.card_uid.hex().upper() if (self.driver.card_uid and self.active_medium == "Contactless") else "Slot 0"
                        self.log("Card", f">>> [{self.active_medium.upper()} CARD INSERTED (BEEP!)] UID: {uid} ATR: {atr.hex().upper()}")
                        self._notify_macos("智能卡已接入", f"{self.active_medium} (UID: {uid})")

                else:
                    # 2. Check if card was removed (only when idle)
                    now = time.time()
                    if (now - self.last_apdu_time) >= 1.0:
                        if self.active_medium == "Contact":
                            if not self.driver.contact_check_status():
                                self.log("Card", ">>> [CONTACT CARD REMOVED]")
                                self.active_medium = "None"
                                self.current_atr = b""
                                self._notify_macos("智能卡已拔出", "接触式卡已移出插槽")

                        elif self.active_medium == "Contactless":
                            probe = bytes.fromhex("00 C0 00 00 00")
                            resp = self.driver.transmit_rf_apdu(probe, timeout=7)
                            if resp is None:
                                time.sleep(0.08)
                                resp = self.driver.transmit_rf_apdu(probe, timeout=7)
                            if resp is None:
                                self.log("Card", ">>> [CONTACTLESS CARD REMOVED]")
                                self.active_medium = "None"
                                self.current_atr = b""
                                self.driver.rf_reset_field(20)
                                self._notify_macos("智能卡已拔出", "非接触卡已离开感应区")

            # Sleep interval depends on state: fast when waiting for card, relaxed when card is present
            if self.active_medium == "None":
                time.sleep(0.25)
            else:
                time.sleep(0.8)

    def transmit_apdu(self, apdu: bytes) -> bytes:
        """Transmits an APDU to the currently active card under lock."""
        with self.lock:
            self.last_apdu_time = time.time()
            if self.use_mock:
                return self.mock_card.process_apdu(apdu)

            if self.active_medium == "Contactless":
                resp = self.driver.transmit_rf_apdu(apdu)
                if resp:
                    return resp
                # If transmission failed, try re-activating once in case card fluttered
                ok, _ = self.driver.activate_rf_card()
                if ok:
                    resp = self.driver.transmit_rf_apdu(apdu)
                    if resp:
                        return resp
                return bytes([0x6F, 0x00])

            elif self.active_medium == "Contact":
                resp = self.driver.contact_transmit_apdu(apdu)
                return resp if resp else bytes([0x6F, 0x00])

            return bytes([0x6F, 0x00])

    def run(self):
        print("=============================================================")
        print(f"  DeCard macOS Unified Dual-Interface Bridge Server")
        print(f"  Listening on: {self.host}:{self.port} (TCP)")
        print("  Supported HW: DeCard T6 / T10 / D3 / D8 (USB HID)")
        print("  Channels    : Contact (ISO 7816) + Contactless RF (ISO 14443-4)")
        print(f"  Priority    : {self.priority} | Mock Mode: {'ENABLED' if self.use_mock else 'AUTO'}")
        print("=============================================================\n")

        # 1. Hardware Initialization
        connected = False
        if not self.use_mock:
            self.log("Bridge", "Scanning for DeCard USB-HID Reader (VID: 0x0471)...")
            connected = self.driver.connect()

        if connected:
            self.log("Bridge", f"Hardware connected! VID: 0x{self.driver.vid:04X} PID: 0x{self.driver.pid:04X}")
        else:
            if self.use_mock or self.auto_mock:
                self.log("Bridge", "⚠️ No physical DeCard reader detected. Starting in MOCK SIMULATOR mode.")
                self.log("Bridge", "Virtual JavaCard with GlobalPlatform ISD will be presented.")
                self.use_mock = True
                self.active_medium = "Virtual JavaCard"
                self.current_atr = self.mock_card.get_atr()
            else:
                self.log("Bridge", "ERROR: DeCard reader not found and mock mode disabled. Exiting.")
                return

        # 2. Start Background Watchdog Thread
        watchdog_thread = threading.Thread(target=self._card_watchdog_loop, daemon=True)
        watchdog_thread.start()

        # 3. Bind TCP Server
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)
        self.log("Server", f"Ready and listening for connections on {self.host}:{self.port}...\n")

        # 4. Connection Accept Loop
        while True:
            try:
                client_sock, client_addr = server_sock.accept()
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.log("Client", f"Connected from {client_addr[0]}:{client_addr[1]}")
                self._handle_client(client_sock)

            except KeyboardInterrupt:
                self.log("Bridge", "Shutting down on user interrupt.")
                break
            except Exception as e:
                self.log("Bridge", f"Server error: {e}")
                time.sleep(0.5)

        self.watchdog_running = False
        server_sock.close()
        self.driver.close()

    def _handle_client(self, client_sock: socket.socket):
        """Processes requests from a connected client (GPDirect or VPCD)."""
        client_sock.settimeout(60.0)
        try:
            while True:
                hdr = client_sock.recv(2)
                if not hdr or len(hdr) < 2:
                    break

                length = (hdr[0] << 8) | hdr[1]
                if length == 0:
                    continue

                payload = bytearray()
                while len(payload) < length:
                    chunk = client_sock.recv(length - len(payload))
                    if not chunk:
                        raise ConnectionResetError("Socket closed during payload transfer")
                    payload.extend(chunk)

                if length == 1:
                    cmd = payload[0]
                    if cmd == 4:  # VPCD_CTRL_ATR
                        self.log("Ctrl", "Host requested ATR")
                        with self.lock:
                            if self.active_medium != "None" and self.current_atr:
                                resp_hdr = len(self.current_atr).to_bytes(2, "big")
                                client_sock.sendall(resp_hdr + self.current_atr)
                            else:
                                # No card present: return length 0
                                client_sock.sendall(b"\x00\x00")

                    elif cmd in (1, 2):  # POWER_UP (1) or RESET (2)
                        self.log("Ctrl", f"Host requested {'POWER_UP' if cmd == 1 else 'RESET'}")
                        with self.lock:
                            if self.use_mock:
                                self.mock_card.reset()
                            elif self.active_medium == "Contactless":
                                self.driver.rf_reset_field(20)
                                self.driver.activate_rf_card()

                    elif cmd == 0:  # POWER_DOWN
                        self.log("Ctrl", "Host requested POWER_DOWN")
                        with self.lock:
                            if not self.use_mock and self.active_medium == "Contactless":
                                self.driver.rf_reset_field(10)
                            self.active_medium = "None"

                else:
                    apdu_bytes = bytes(payload)
                    self.log("APDU In", f"[{self.active_medium}] {apdu_bytes.hex().upper()}")
                    resp = self.transmit_apdu(apdu_bytes)
                    self.log("APDU Out", f"[{self.active_medium}] {resp.hex().upper()}")
                    resp_hdr = len(resp).to_bytes(2, "big")
                    client_sock.sendall(resp_hdr + resp)

        except (ConnectionResetError, BrokenPipeError, socket.timeout):
            pass
        except Exception as e:
            self.log("Client", f"Session exception: {e}")
        finally:
            client_sock.close()
            self.log("Client", "Session closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeCard macOS PC/SC Bridge Server")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=35963, help="Server port (default: 35963)")
    parser.add_argument("--priority", choices=["ContactFirst", "RfFirst"], default="RfFirst")
    parser.add_argument("--mock", action="store_true", help="Force Mock JavaCard simulation mode")
    parser.add_argument("--no-auto-mock", action="store_true", help="Disable fallback to mock mode if reader is missing")
    parser.add_argument("--no-notify", action="store_true", help="Disable macOS desktop notifications")

    args = parser.parse_args()
    bridge = DecardMacBridge(
        host=args.host,
        port=args.port,
        use_mock=args.mock,
        auto_mock=not args.no_auto_mock,
        priority=args.priority,
        enable_notify=not args.no_notify
    )
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\n[Bridge] Exiting on user interrupt.")
