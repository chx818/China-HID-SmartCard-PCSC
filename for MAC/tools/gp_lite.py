#!/usr/bin/env python3
"""
GlobalPlatform Lite (gp_lite.py)
Pure Python JavaCard & GlobalPlatform management tool.
Directly communicates with DeCard & Feitian USB-HID readers, bypassing PC/SC and VPCD completely!
"""

import sys
import os
import argparse
import binascii

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mac_drivers.decard_hid import DeCardHIDDriver
from mac_drivers.feitian_hid import FeitianHIDDriver
from mac_drivers.mock_card import MockJavaCard

class GPLite:
    def __init__(self, reader_type: str = "decard", mock: bool = False):
        self.mock = mock
        self.mock_card = MockJavaCard() if mock else None
        if reader_type == "decard":
            self.driver = DeCardHIDDriver()
        else:
            self.driver = FeitianHIDDriver()
        self.medium = "None"
        self.atr = b""

    def connect(self) -> bool:
        if self.mock:
            print("[GP Lite] Running in MOCK SIMULATOR mode (Virtual JavaCard).")
            self.medium = "Virtual Card"
            self.atr = self.mock_card.get_atr()
            print(f"[GP Lite] ATR: {self.atr.hex().upper()}")
            return True

        print(f"[GP Lite] Connecting to {self.driver.__class__.__name__} via USB-HID...")
        if not self.driver.connect():
            print("[GP Lite] No physical reader detected. Use --mock to test with virtual card.")
            return False

        print("[GP Lite] Reader connected! Detecting smart card...")

        # Contact check first (if DeCard)
        if isinstance(self.driver, DeCardHIDDriver):
            if self.driver.contact_check_status():
                atr = self.driver.contact_reset()
                if atr:
                    self.medium = "Contact"
                    self.atr = atr
                    print(f"[GP Lite] Contact card detected! ATR: {atr.hex().upper()}")
                    return True

            # RF Check
            ok, atr = self.driver.activate_rf_card()
            if ok and atr:
                self.medium = "Contactless"
                self.atr = atr
                uid_str = self.driver.card_uid.hex().upper() if self.driver.card_uid else "Unknown"
                print(f"[GP Lite] Contactless card detected! UID: {uid_str}")
                print(f"[GP Lite] ATR: {atr.hex().upper()}")
                return True
        else:
            ok, atr = self.driver.activate_rf_card()
            if ok and atr:
                self.medium = "Contactless"
                self.atr = atr
                print(f"[GP Lite] Contactless card detected! ATR: {atr.hex().upper()}")
                return True

        print("[GP Lite] ⚠️ No card detected in contact slot or on RF antenna!")
        return False

    def transmit(self, apdu: bytes) -> bytes:
        if self.mock:
            return self.mock_card.process_apdu(apdu)

        if self.medium == "Contact":
            resp = self.driver.contact_transmit_apdu(apdu)
            return resp if resp else bytes([0x6F, 0x00])
        elif self.medium == "Contactless":
            resp = self.driver.transmit_rf_apdu(apdu)
            return resp if resp else bytes([0x6F, 0x00])

        return bytes([0x6F, 0x00])

    def select_isd(self) -> bool:
        """Selects Issuer Security Domain (ISD)."""
        print(">> SELECT ISD (00 A4 04 00 08 A000000151000000)")
        cmd = bytes.fromhex("00 A4 04 00 08 A0 00 00 01 51 00 00 00")
        resp = self.transmit(cmd)
        sw = resp[-2:] if len(resp) >= 2 else b"\x00\x00"
        print(f"<< Response: {resp.hex().upper()} (SW: {sw.hex().upper()})")
        return sw in (b"\x90\x00", b"\x61\x00")

    def card_info(self):
        """Prints Card Data / CPLC details."""
        print("\n--- Card Details ---")
        if not self.select_isd():
            print("Failed to select ISD.")
            return

        # GET DATA: CPLC (80 CA 00 66 00)
        print(">> GET DATA (CPLC: 80 CA 00 66 00)")
        resp = self.transmit(bytes.fromhex("80 CA 00 66 00"))
        if len(resp) >= 2 and resp[-2:] == b"\x90\x00":
            print(f"<< CPLC Raw Data: {resp[:-2].hex().upper()}")
        else:
            print(f"<< CPLC Response: {resp.hex().upper()}")

    def list_applets(self):
        """Lists installed Applets and Packages via GET STATUS."""
        print("\n--- Installed Applets & Packages ---")
        if not self.select_isd():
            print("Failed to select ISD.")
            return

        # GET STATUS (ISD & Applications: 80 F2 80 00 02 4F 00 00)
        print(">> GET STATUS (80 F2 80 00 02 4F 00 00)")
        resp = self.transmit(bytes.fromhex("80 F2 80 00 02 4F 00 00"))
        if len(resp) >= 2 and resp[-2:] == b"\x90\x00":
            print(f"<< Status Data: {resp[:-2].hex().upper()}")
        else:
            print(f"<< Status Response: {resp.hex().upper()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GlobalPlatform Lite (Direct USB-HID / No PC/SC required)")
    parser.add_argument("-r", "--reader", choices=["decard", "feitian"], default="decard")
    parser.add_argument("-i", "--info", action="store_true", help="Print card info (CPLC / ISD)")
    parser.add_argument("-l", "--list", action="store_true", help="List applications & applets")
    parser.add_argument("-a", "--apdu", help="Send arbitrary APDU (hex string, e.g. '00A4040000')")
    parser.add_argument("--mock", action="store_true", help="Run with virtual mock card (for testing without hardware)")

    args = parser.parse_args()
    gp = GPLite(reader_type=args.reader, mock=args.mock)

    if not gp.connect():
        sys.exit(1)

    if args.apdu:
        raw_cmd = bytes.fromhex(args.apdu.replace(" ", ""))
        print(f">> {raw_cmd.hex().upper()}")
        resp = gp.transmit(raw_cmd)
        print(f"<< {resp.hex().upper()}")
    elif args.list:
        gp.list_applets()
    elif args.info:
        gp.card_info()
    else:
        gp.card_info()
        gp.list_applets()
