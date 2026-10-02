"""
Native macOS USB-HID Driver for DeCard Smart Card Readers (T6 / T10 / D3 / D8).
Fully reverse-engineered from dcic32.dll & dcrf32.dll.
Uses HID Feature Reports via libhidapi for 100% native macOS operation.
Zero Windows DLL dependencies. Compatible with Apple Silicon & Intel.
"""

import time
import ctypes
from typing import Optional, Tuple
from .hid_transport import HIDDevice, get_hid_lib

DECARD_VID = 0x0471
DECARD_PIDS = [0xA112, 0xA120]

class DeCardHIDDriver:
    def __init__(self, vid: int = DECARD_VID, pid: Optional[int] = None):
        self.vid = vid
        self.pid = pid
        self.dev: Optional[HIDDevice] = None
        self.lib = get_hid_lib()
        self.rf_block_num = 0
        self.card_uid = b""

        # Feature report function prototypes
        self.lib.hid_send_feature_report.restype = ctypes.c_int
        self.lib.hid_send_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        self.lib.hid_get_feature_report.restype = ctypes.c_int
        self.lib.hid_get_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]

    def connect(self) -> bool:
        """Find and connect to DeCard USB reader."""
        pids_to_try = [self.pid] if self.pid else DECARD_PIDS
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

    def _build_frame(self, cmd_bytes: bytes) -> bytes:
        """Constructs DeCard link-layer frame: [0x02, 0x00, len, len] + cmd_bytes + [BCC, 0x03]"""
        cmd_len = len(cmd_bytes) + 1
        raw_inner = bytes([0x02, 0x00, cmd_len, cmd_len]) + cmd_bytes
        bcc = 0
        for b in raw_inner:
            bcc ^= b
        return raw_inner + bytes([bcc, 0x03])

    def _send_cmd(self, cmd_bytes: bytes, timeout_ms: int = 1500) -> Tuple[int, bytes]:
        """
        Sends DeCard command via HID Feature Reports with multi-report streaming support.
        Packet frame: [0x02, 0x00, cmd_len, cmd_len] + cmd_bytes + [BCC, 0x03]
        Multi-report flag: 0x82 if more reports follow, 0x02 for final report.
        """
        if not self.dev or not self.dev.handle:
            return -1, b""

        frame = self._build_frame(cmd_bytes)

        # Send in 31-byte chunks via Feature Reports
        offset = 0
        while offset < len(frame):
            chunk = frame[offset:offset + 31]
            offset += len(chunk)
            flag = 0x82 if offset < len(frame) else 0x02
            report = bytes([0x00, flag]) + chunk
            if len(report) < 33:
                report = report + bytes(33 - len(report))
            res = self.lib.hid_send_feature_report(self.dev.handle, report, len(report))
            if res < 0:
                return -1, b""

        time.sleep(0.012)

        # Receive feature reports with reassembly
        assembled = bytearray()
        while True:
            rx_buf = ctypes.create_string_buffer(33)
            rx_buf[0] = 0
            g = self.lib.hid_get_feature_report(self.dev.handle, rx_buf, 33)
            if g < 3:
                return -1, b""
            data = rx_buf.raw[:g]
            flag = data[1]
            assembled.extend(data[2:33])
            if flag == 0x82:
                continue
            break

        if len(assembled) >= 4 and assembled[0] == 0x02:
            status = assembled[1]
            length = assembled[2]
            payload = assembled[3:3 + length]
            return status, bytes(payload)

        return -1, b""

    def _init_reader(self):
        """Initial hardware setup: Beep and RF power on."""
        self.beep(5)
        self.rf_reset_field(20)

    def beep(self, beeptime: int = 5):
        """Opcode 0xC8."""
        self._send_cmd(bytes([0xC8, 0x00, beeptime & 0xFF]))

    # ========================================================
    # Contact Smart Card (ISO 7816) Methods
    # ========================================================
    def contact_check_status(self) -> bool:
        """Checks if contact card is physically inserted (Opcode 0x99)."""
        st, payload = self._send_cmd(bytes([0x99]))
        return st == 0 and len(payload) > 0 and payload[0] in (0x82, 0x86)

    def contact_reset(self, slot: int = 0) -> Optional[bytes]:
        """CPU Reset: Opcode 0xA3. Returns card ATR."""
        cmd = bytes([0x21, 0xA3, (slot & 0x0F) << 4, 0x00])
        st, payload = self._send_cmd(cmd)
        if st == 0 and len(payload) >= 2:
            atr_len = payload[1]
            return payload[2:2 + atr_len]
        return None

    def contact_transmit_apdu(self, apdu: bytes, slot: int = 0) -> Optional[bytes]:
        """Transmit APDU to Contact Smart Card (Opcode 0xA4)."""
        cmd = bytes([0x21, 0xA4, (slot & 0x0F) << 4, len(apdu) & 0xFF]) + apdu
        st, payload = self._send_cmd(cmd)
        if st == 0 and len(payload) >= 2:
            rlen = payload[1]
            return payload[2:2 + rlen]
        return None

    # ========================================================
    # Contactless RF (ISO 14443-4 Type A / T=CL) Methods
    # ========================================================
    def rf_reset_field(self, msec: int = 20):
        """Opcode 0xDC + Opcode 0xE0 (Config Card)."""
        self._send_cmd(bytes([0xDC, 0x00, msec & 0xFF]))
        time.sleep(0.02)
        self._send_cmd(bytes([0xE0, 0x41]))
        time.sleep(0.02)

    def rf_request(self, mode: int = 1) -> Optional[bytes]:
        """WUPA (mode=1) or REQA (mode=0): Opcode 0xD0."""
        st, payload = self._send_cmd(bytes([0xD0, mode & 0x01]))
        if st == 0 and len(payload) >= 2:
            return payload
        return None

    def rf_anticoll(self) -> Optional[bytes]:
        """Anticoll Level 1: Opcode 0xD1."""
        st, payload = self._send_cmd(bytes([0xD1, 0x00]))
        if st == 0 and len(payload) >= 4:
            return payload[:4]
        return None

    def rf_select(self, uid: bytes) -> Optional[int]:
        """Select Level 1: Opcode 0xD2."""
        st, payload = self._send_cmd(bytes([0xD2]) + uid[:4])
        if st == 0 and len(payload) >= 1:
            return payload[0]
        return None

    def rf_anticoll2(self) -> Optional[bytes]:
        """Anticoll Level 2: Opcode 0xE4."""
        st, payload = self._send_cmd(bytes([0xE4, 0x00]))
        if st == 0 and len(payload) >= 4:
            return payload[:4]
        return None

    def rf_select2(self, uid: bytes) -> Optional[int]:
        """Select Level 2: Opcode 0xE5."""
        st, payload = self._send_cmd(bytes([0xE5]) + uid[:4])
        if st == 0 and len(payload) >= 1:
            return payload[0]
        return None

    def rf_rats(self) -> Optional[bytes]:
        """ISO 14443-4 RATS (Request for Answer to Select). Returns ATS."""
        # Opcode 0xDF, timeout=7, slen=2, [0xE0, 0x50]
        st, payload = self._send_cmd(bytes([0xDF, 0x07, 0x02, 0xE0, 0x50]))
        if st == 0 and len(payload) >= 1:
            return payload
        return None

    @staticmethod
    def build_atr_from_ats(ats: bytes) -> bytes:
        """Converts ISO 14443 Type A ATS to standard PC/SC ATR."""
        if not ats or len(ats) < 2:
            return bytes.fromhex("3B 8E 80 01 80 31 80 66 B0 84 0C 01 6E 01 83 00 90 00 1D")

        tl = ats[0]
        t0 = ats[1] if len(ats) > 1 else 0
        offset = 2
        if (t0 & 0x10) and offset < len(ats): offset += 1
        if (t0 & 0x20) and offset < len(ats): offset += 1
        if (t0 & 0x40) and offset < len(ats): offset += 1

        k = max(0, min(15, len(ats) - offset))
        historical = ats[offset:offset + k]

        atr = bytearray([0x3B, 0x80 | (k & 0x0F), 0x80, 0x01])
        atr.extend(historical)
        tck = 0
        for b in atr[1:]:
            tck ^= b
        atr.append(tck)
        return bytes(atr)

    def activate_rf_card(self) -> Tuple[bool, Optional[bytes]]:
        """Full ISO 14443 Type A Activation (WUPA -> Anticoll -> Select -> Cascade -> RATS)."""
        # 1. WUPA (Request 1)
        atqa = self.rf_request(1)
        if not atqa:
            atqa = self.rf_request(0)
        if not atqa:
            return False, None

        # 2. Anticoll Level 1
        uid1 = self.rf_anticoll()
        if not uid1:
            return False, None

        # 3. Select Level 1
        sak1 = self.rf_select(uid1)
        if sak1 is None:
            return False, None

        final_sak = sak1
        full_uid = bytearray()

        # Cascade Level 2 (Bit 2 / Bit 3 / Tag 0x88)
        if (sak1 & 0x04) or uid1[0] == 0x88:
            full_uid.extend(uid1[1:4])
            uid2 = self.rf_anticoll2()
            if not uid2:
                return False, None
            sak2 = self.rf_select2(uid2)
            if sak2 is None:
                return False, None
            final_sak = sak2
            full_uid.extend(uid2)
        else:
            full_uid.extend(uid1)

        self.card_uid = bytes(full_uid)

        # 4. RATS for T=CL (ISO 14443-4)
        if final_sak & 0x20:
            ats = self.rf_rats()
            atr = self.build_atr_from_ats(ats if ats else b"")
            self.rf_block_num = 0
            return True, atr
        else:
            # Memory / Mifare Classic fallback
            atr = bytes.fromhex("3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 01 00 00 00 00 68")
            self.rf_block_num = 0
            return True, atr

    def transmit_rf_apdu(self, apdu: bytes, timeout: int = 10) -> Optional[bytes]:
        """
        Wrap APDU in ISO 14443-4 I-Block framing and transmit via Opcode 0xDF.
        Handles S(WTX) Waiting Time Extensions and Chaining.
        """
        pcb = 0x02 | (self.rf_block_num & 1)
        frame = bytes([pcb]) + apdu
        cmd = bytes([0xDF, timeout & 0xFF, len(frame) & 0xFF]) + frame

        st, raw_resp = self._send_cmd(cmd)
        if st != 0 or not raw_resp or len(raw_resp) < 1:
            return None

        full_resp = bytearray()
        in_frame = raw_resp

        while True:
            in_pcb = in_frame[0]

            # 1. S(WTX) Request
            if (in_pcb & 0xF2) == 0xF2:
                wtx_resp = bytes([in_pcb, in_frame[1] if len(in_frame) > 1 else 1])
                cmd_wtx = bytes([0xDF, timeout & 0xFF, len(wtx_resp) & 0xFF]) + wtx_resp
                st, in_frame = self._send_cmd(cmd_wtx)
                if st != 0 or not in_frame or len(in_frame) < 1:
                    return None
                continue

            # 2. Chaining: Bit 4 (0x10) is set
            if in_pcb & 0x10:
                full_resp.extend(in_frame[1:])
                self.rf_block_num ^= 1
                r_ack = bytes([0xA2 | (self.rf_block_num & 1)])
                cmd_ack = bytes([0xDF, timeout & 0xFF, len(r_ack) & 0xFF]) + r_ack
                in_frame = None
                for _ in range(5):
                    time.sleep(0.015)
                    st, in_frame = self._send_cmd(cmd_ack)
                    if st == 0 and in_frame and len(in_frame) >= 1:
                        break
                if not in_frame or len(in_frame) < 1:
                    return None
                continue

            # 3. Final block
            full_resp.extend(in_frame[1:])
            self.rf_block_num ^= 1
            break

        return bytes(full_resp)
