#!/usr/bin/env python3
"""
Automated Pipeline Test Suite for macOS SmartCard Bridge.
Verifies all components, packet framing, mock simulation, and socket IPC without hardware.
"""

import sys
import os
import time
import socket
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mac_drivers.hid_transport import HIDDevice, get_hid_lib
from mac_drivers.decard_hid import DeCardHIDDriver
from mac_drivers.mock_card import MockJavaCard
from scripts.decard_mac_bridge import DecardMacBridge

class TestMacSmartCardPipeline(unittest.TestCase):

    def test_01_hid_library_loaded(self):
        """Verify libhidapi.dylib loads and initializes cleanly."""
        lib = get_hid_lib()
        self.assertIsNotNone(lib)
        devs = HIDDevice.enumerate_devices()
        self.assertIsInstance(devs, list)
        print(f"  [PASS] libhidapi loaded, enumerated {len(devs)} HID devices.")

    def test_02_decard_framing_and_checksum(self):
        """Verify DeCard link-layer framing and XOR checksum calculation."""
        driver = DeCardHIDDriver()
        # Test command: Beep (0xC8 0x00 0x05)
        payload = bytes([0xC8, 0x00, 0x05])
        frame = driver._build_frame(payload)
        self.assertEqual(frame[0], 0x02)  # STX
        self.assertEqual(frame[1], 0x00)  # Station
        self.assertEqual(frame[2], len(payload) + 1)  # Length
        self.assertEqual(frame[3], len(payload) + 1)  # Length (duplicated)
        self.assertEqual(frame[4:7], payload)
        self.assertEqual(frame[-1], 0x03) # ETX

        # Verify BCC
        bcc = 0
        for b in frame[:-2]:
            bcc ^= b
        self.assertEqual(frame[-2], bcc)
        print("  [PASS] DeCard STX/ETX framing and XOR checksum verified.")

    def test_03_ats_to_atr_converter(self):
        """Verify ISO 14443-4 ATS to PC/SC ATR translation."""
        driver = DeCardHIDDriver()
        # Simulated ATS from Mifare DESFire / JavaCard
        ats = bytes.fromhex("06 75 77 81 02 80")
        atr = driver.build_atr_from_ats(ats)
        self.assertEqual(atr[0], 0x3B)
        self.assertEqual(atr[2], 0x80)
        self.assertEqual(atr[3], 0x01)
        print(f"  [PASS] ATS to ATR conversion passed: {atr.hex().upper()}")

    def test_04_mock_javacard_apdus(self):
        """Verify Virtual JavaCard simulator responses."""
        card = MockJavaCard()
        # 1. SELECT ISD
        sel = card.process_apdu(bytes.fromhex("00 A4 04 00 08 A0 00 00 01 51 00 00 00"))
        self.assertTrue(sel.endswith(bytes([0x90, 0x00])))
        self.assertEqual(sel[0], 0x6F)  # FCI template

        # 2. GET DATA (CPLC)
        cplc = card.process_apdu(bytes.fromhex("80 CA 00 66 00"))
        self.assertTrue(cplc.endswith(bytes([0x90, 0x00])))

        # 3. INITIALIZE UPDATE
        init_up = card.process_apdu(bytes.fromhex("80 50 00 00 08 01 02 03 04 05 06 07 08"))
        self.assertTrue(init_up.endswith(bytes([0x90, 0x00])))
        self.assertEqual(len(init_up), 30)  # 28 bytes data + SW
        print("  [PASS] Mock JavaCard ISO 7816 & GlobalPlatform APDUs verified.")

    def test_05_bridge_server_loopback(self):
        """Verify end-to-end TCP socket bridge server with mock card."""
        test_port = 35975
        bridge = DecardMacBridge(host="127.0.0.1", port=test_port, use_mock=True)

        # Start bridge server loop in background thread
        bridge_thread = threading.Thread(target=bridge.run, daemon=True)
        bridge_thread.start()
        time.sleep(0.3)

        # Connect client (simulating GPDirect or VPCD)
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", test_port))

        # Send VPCD_CTRL_ATR (cmd 4)
        client.sendall(bytes([0x00, 0x01, 0x04]))
        hdr = client.recv(2)
        resp_len = (hdr[0] << 8) | hdr[1]
        atr_resp = client.recv(resp_len)
        self.assertEqual(atr_resp, bridge.mock_card.get_atr())

        # Send APDU: SELECT ISD
        apdu = bytes.fromhex("00 A4 04 00 08 A0 00 00 01 51 00 00 00")
        client.sendall(len(apdu).to_bytes(2, "big") + apdu)
        hdr = client.recv(2)
        resp_len = (hdr[0] << 8) | hdr[1]
        card_resp = client.recv(resp_len)
        self.assertTrue(card_resp.endswith(bytes([0x90, 0x00])))

        client.close()
        print("  [PASS] Full TCP socket bridge server session verified.")

if __name__ == "__main__":
    print("\n=============================================================")
    print("  Running macOS China SmartCard PCSC Pipeline Test Suite")
    print("=============================================================\n")
    unittest.main(verbosity=1)
