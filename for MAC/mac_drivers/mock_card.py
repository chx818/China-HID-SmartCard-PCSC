"""
Virtual Mock Smart Card Simulator (JavaCard / GlobalPlatform).
Allows full software and pipeline testing on macOS without any physical reader connected.
"""

import binascii
from typing import Optional

class MockJavaCard:
    """Simulates an ISO 7816-4 / JavaCard 3.0 with GlobalPlatform 2.2 ISD."""

    ATR = bytes.fromhex("3B 8E 80 01 80 31 80 66 B0 84 0C 01 6E 01 83 00 90 00 1D")
    ISD_AID = bytes.fromhex("A0 00 00 01 51 00 00 00")

    def __init__(self):
        self.is_selected = False
        self.security_level = 0
        self.card_challenge = bytes.fromhex("11 22 33 44 55 66 77 88")

    def get_atr(self) -> bytes:
        return self.ATR

    def reset(self):
        self.is_selected = False
        self.security_level = 0

    def process_apdu(self, apdu: bytes) -> bytes:
        """Processes standard GlobalPlatform & ISO 7816 APDU commands."""
        if len(apdu) < 4:
            return bytes([0x67, 0x00])  # Wrong length

        cla, ins, p1, p2 = apdu[0], apdu[1], apdu[2], apdu[3]

        # 1. SELECT command (00 A4 ...)
        if cla == 0x00 and ins == 0xA4:
            if p1 == 0x04:  # Select by name (AID)
                lc = apdu[4] if len(apdu) > 4 else 0
                aid = apdu[5:5 + lc]
                # Default ISD or empty AID
                if aid == self.ISD_AID or lc == 0:
                    self.is_selected = True
                    # Return FCI Template (6F)
                    # 84: AID (A000000151000000), A5: Proprietary data (Card Management details)
                    fci = bytes.fromhex("6F 17 84 08 A0 00 00 01 51 00 00 00 A5 0B 73 04 06 07 2A 86 48 86 FC 6B 01")
                    return fci + bytes([0x90, 0x00])
                else:
                    return bytes([0x6A, 0x82])  # File/Applet not found

        # 2. GET DATA (80 CA ...)
        if cla in (0x80, 0x00) and ins == 0xCA:
            tag = (p1 << 8) | p2
            if tag == 0x0066:  # Card Data
                # CPLC mock (Card Production Life Cycle data)
                cplc = bytes.fromhex(
                    "66 2B "
                    "9F 65 01 FF "  # Card configuration
                    "9F 6E 07 12 34 56 78 90 12 34 "  # Fabricator info
                    "DF 25 02 01 02 "  # OS release
                    "01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16"
                )
                return cplc + bytes([0x90, 0x00])
            elif tag == 0x0042:  # Issuer Identification Number (IIN)
                return bytes.fromhex("42 04 40 00 00 01 90 00")
            elif tag == 0x0045:  # Card Image Number (CIN)
                return bytes.fromhex("45 08 12 34 56 78 90 AB CD EF 90 00")

        # 3. INITIALIZE UPDATE (80 50 ...)
        if cla in (0x80, 0x84) and ins == 0x50:
            # P1 = Key Version, P2 = Key Index
            host_challenge = apdu[5:13] if len(apdu) >= 13 else bytes(8)
            # Response: Key Diversification (10B) + Key Info (2B) + Card Challenge (8B) + Card Cryptogram (8B)
            diversification = bytes.fromhex("00 00 11 22 33 44 55 66 77 88")
            key_info = bytes.fromhex("01 02")  # SCP02, version 1
            card_cryptogram = bytes.fromhex("AA BB CC DD EE FF 00 11")
            resp = diversification + key_info + self.card_challenge + card_cryptogram
            return resp + bytes([0x90, 0x00])

        # 4. EXTERNAL AUTHENTICATE (84 82 ...)
        if cla == 0x84 and ins == 0x82:
            self.security_level = p1
            return bytes([0x90, 0x00])

        # 5. GET STATUS (80 F2 ... / 84 F2 ...)
        if ins == 0xF2:
            # List applications / packages / security domains
            card_state = bytes.fromhex(
                "E3 1C "
                "4F 08 A0 00 00 01 51 00 00 00 "  # ISD AID
                "9F 70 01 07 "                    # Life cycle: OP_READY (0x07)
                "C5 01 01 "                       # Card Privileges
                "CE 06 01 02 03 04 05 06"
            )
            return card_state + bytes([0x90, 0x00])

        # Default fallback: SW_SUCCESS
        return bytes([0x90, 0x00])
