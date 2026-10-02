#!/usr/bin/env python3
"""
Feitian SCR501 / ROCKEY 531 PC/SC Bridge for macOS.
Native Python implementation using libhidapi. Fully cross-platform (Apple Silicon & Intel).
No Windows DLLs required. Listens as TCP Server (default 127.0.0.1:35963) to serve both:
1. Direct GPTool / GPDirect.java sessions (bypassing PC/SC and system drivers)
2. macOS VPCD / ifd-vpcd driver for system-wide Apple SmartCardServices
"""

import sys
import os
import time
import socket
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mac_drivers.feitian_hid import FeitianHIDDriver
from mac_drivers.mock_card import MockJavaCard

class FeitianMacBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 35963, 
                 use_mock: bool = False, auto_mock: bool = True):
        self.host = host
        self.port = port
        self.use_mock = use_mock
        self.auto_mock = auto_mock
        self.driver = FeitianHIDDriver()
        self.mock_card = MockJavaCard() if (use_mock or auto_mock) else None
        self.active = False
        self.current_atr = b""

    def log(self, tag: str, msg: str):
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{tag} {now}] {msg}")

    def detect_and_activate(self) -> bool:
        if self.use_mock:
            self.active = True
            self.current_atr = self.mock_card.get_atr()
            return True

        if self.driver.check_card_present():
            ok, atr = self.driver.activate_rf_card()
            if ok and atr:
                self.active = True
                self.current_atr = atr
                self.log("Card", f"Feitian Contactless card activated (ATR: {atr.hex().upper()})")
                return True
        return False

    def transmit_apdu(self, apdu: bytes) -> bytes:
        if self.use_mock:
            return self.mock_card.process_apdu(apdu)

        resp = self.driver.transmit_rf_apdu(apdu)
        return resp if resp else bytes([0x6F, 0x00])

    def run(self):
        print("=============================================================")
        print(f"  Feitian SCR501 macOS Bridge Server")
        print(f"  Listening on: {self.host}:{self.port} (TCP)")
        print("  Supported HW: Feitian SCR501 / ROCKEY 531 (VID: 0x096E)")
        print(f"  Mock Mode   : {'ENABLED' if self.use_mock else 'AUTO'}")
        print("=============================================================\n")

        connected = False
        if not self.use_mock:
            self.log("Bridge", "Scanning for Feitian USB-HID Reader (VID: 0x096E)...")
            connected = self.driver.connect()

        if connected:
            self.log("Bridge", f"Hardware connected! VID: 0x{self.driver.vid:04X} PID: 0x{self.driver.pid:04X}")
            self.driver.beep(1)
        else:
            if self.use_mock or self.auto_mock:
                self.log("Bridge", "⚠️ No physical Feitian reader detected. Starting in MOCK SIMULATOR mode.")
                self.use_mock = True
            else:
                self.log("Bridge", "ERROR: Feitian reader not found and mock mode disabled. Exiting.")
                return

        # Pre-activate
        if not self.detect_and_activate():
            self.log("Bridge", "No card detected yet. Will detect on client connection.")

        # Bind server
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)
        self.log("Server", f"Ready and listening for connections on {self.host}:{self.port}...\n")

        while True:
            try:
                client_sock, client_addr = server_sock.accept()
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.log("Client", f"Connected from {client_addr[0]}:{client_addr[1]}")

                if not self.active:
                    self.detect_and_activate()

                self._handle_client(client_sock)

            except KeyboardInterrupt:
                self.log("Bridge", "Shutting down on user interrupt.")
                break
            except Exception as e:
                self.log("Bridge", f"Server error: {e}")
                time.sleep(0.5)

        server_sock.close()
        self.driver.close()

    def _handle_client(self, client_sock: socket.socket):
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
                        raise ConnectionResetError("Socket closed during payload read")
                    payload.extend(chunk)

                if length == 1:
                    cmd = payload[0]
                    if cmd == 4:  # VPCD_CTRL_ATR
                        self.log("Ctrl", "Host requested ATR")
                        if not self.active:
                            self.detect_and_activate()
                        resp_hdr = len(self.current_atr).to_bytes(2, "big")
                        client_sock.sendall(resp_hdr + self.current_atr)
                    elif cmd in (1, 2):
                        self.log("Ctrl", f"Host requested {'POWER_UP' if cmd == 1 else 'RESET'}")
                        if self.use_mock:
                            self.mock_card.reset()
                        else:
                            self.detect_and_activate()
                    elif cmd == 0:
                        self.log("Ctrl", "Host requested POWER_DOWN")
                        self.active = False
                else:
                    apdu_bytes = bytes(payload)
                    self.log("APDU In", f"[Contactless] {apdu_bytes.hex().upper()}")
                    resp = self.transmit_apdu(apdu_bytes)
                    self.log("APDU Out", f"[Contactless] {resp.hex().upper()}")
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
    parser = argparse.ArgumentParser(description="Feitian SCR501 macOS Bridge Server")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=35963, help="Server port (default: 35963)")
    parser.add_argument("--mock", action="store_true", help="Force Mock JavaCard simulation mode")
    parser.add_argument("--no-auto-mock", action="store_true", help="Disable fallback to mock mode")

    args = parser.parse_args()
    bridge = FeitianMacBridge(
        host=args.host,
        port=args.port,
        use_mock=args.mock,
        auto_mock=not args.no_auto_mock
    )
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\n[Bridge] Exiting on user interrupt.")
