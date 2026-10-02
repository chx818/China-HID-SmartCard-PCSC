"""
Native macOS USB-HID Driver for Feitian SCR501 / ROCKEY 531 Smart Card Readers.
Fully reverse-engineered from RK501API.dll.
Zero Windows DLL dependencies. Runs natively on Apple Silicon & Intel macOS.
"""

import time
from typing import Optional, Tuple
from .hid_transport import HIDDevice

FEITIAN_VID = 0x096E
FEITIAN_PIDS = [0x0603, 0x0601]

class FeitianHIDDriver:
    def __init__(self, vid: int = FEITIAN_VID, pid: Optional[int] = None):
        self.vid = vid
        self.pid = pid
        self.dev: Optional[HIDDevice] = None

    def connect(self) -> bool:
        """Find and connect to Feitian USB reader."""
        pids_to_try = [self.pid] if self.pid else FEITIAN_PIDS
        for p in pids_to_try:
            devices = HIDDevice.enumerate_devices(self.vid, p)
            if devices:
                self.pid = p
                self.dev = HIDDevice(self.vid, self.pid, devices[0][3])
                if self.dev.open():
                    self._init_reader()
                    return True
        return False

    def is_connected(self) -> bool:
        return self.dev is not None and self.dev.handle is not None

    def close(self):
        if self.dev:
            self.dev.close()
            self.dev = None

    def _build_packet(self, cmd_id: int, payload: bytes = b"") -> bytes:
        """Builds Feitian protocol packet: [STX=0x02, Seq=0x00, Len_H, Len_L, 0x80, Cmd, Payload..., BCC, ETX=0x03]"""
        inner = bytes([0x80, cmd_id & 0xFF]) + payload
        total_len = len(inner)
        hdr = bytes([0x02, 0x00, (total_len >> 8) & 0xFF, total_len & 0xFF])
        data = hdr + inner
        bcc = 0
        for b in data:
            bcc ^= b
        return data + bytes([bcc, 0x03])

    def _send_cmd(self, cmd_id: int, payload: bytes = b"", timeout_ms: int = 2500) -> Optional[bytes]:
        if not self.dev:
            return None

        pkt = self._build_packet(cmd_id, payload)
        report = bytes([0x00]) + pkt
        if len(report) < 65:
            report = report + bytes(65 - len(report))

        self.dev.write(report)

        resp = self.dev.read(65, timeout_ms)
        if not resp or len(resp) < 6:
            return None

        data = resp[1:] if resp[0] == 0x00 else resp
        if data[0] != 0x02:
            return None

        resp_len = (data[2] << 8) | data[3]
        if len(data) >= 4 + resp_len:
            # Strip link header and status bytes
            return data[4:4 + resp_len]
        return data[4:]

    def _init_reader(self):
        self.beep(1)
        self.rf_field_on()

    def beep(self, count: int = 1):
        """Beep command (0x01)."""
        self._send_cmd(0x01, bytes([0x0A, count & 0xFF, 0x00]), timeout_ms=300)

    def rf_field_on(self):
        """Turn on RF carrier field."""
        self._send_cmd(0x0C, bytes([0x01]), timeout_ms=300)

    def check_card_present(self) -> bool:
        """Card detection probe."""
        resp = self._send_cmd(0x0B, timeout_ms=200)
        return resp is not None and len(resp) > 0 and resp[0] == 0x00

    def activate_rf_card(self) -> Tuple[bool, Optional[bytes]]:
        """Request, Anticoll, Select and RATS for Feitian."""
        # 1. Type A Request (WUPA)
        req = self._send_cmd(0x10, bytes([0x52]), timeout_ms=200)
        if not req:
            return False, None

        # 2. Anticoll
        uid = self._send_cmd(0x11, bytes([0x93]), timeout_ms=200)
        if not uid:
            return False, None

        # 3. Select
        sel = self._send_cmd(0x12, uid[:4], timeout_ms=200)
        if not sel:
            return False, None

        # 4. RATS
        rats = self._send_cmd(0x13, bytes([0x50]), timeout_ms=500)
        atr = bytes.fromhex("3B 8E 80 01 80 31 80 66 B0 84 0C 01 6E 01 83 00 90 00 1D")
        return True, atr

    def transmit_rf_apdu(self, apdu: bytes, timeout_ms: int = 2500) -> Optional[bytes]:
        """Transmit ISO 14443-4 APDU."""
        resp = self._send_cmd(0x14, apdu, timeout_ms=timeout_ms)
        return resp
