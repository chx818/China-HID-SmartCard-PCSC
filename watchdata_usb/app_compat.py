"""Narrow PIV/OpenPGP read adapter for the short-APDU-only serial firmware.

Only explicitly selected known applications and read-only instructions qualify.
Secure messaging, key operations, PIN commands and arbitrary applets stay untouched.
"""
from dataclasses import dataclass

PIV = bytes.fromhex('A00000030800001000')
OPENPGP = bytes.fromhex('D27600012401')
FIDO = bytes.fromhex('A0000006472F0001')

class ReadMappingError(OSError):
    pass

@dataclass(frozen=True)
class Command:
    header: bytes
    data: bytes
    le: int | None
    extended: bool


def parse_command(c: bytes) -> Command | None:
    if not 4 <= len(c) <= 65535:
        return None
    if len(c) == 4:
        return Command(c, b'', None, False)
    if len(c) == 5:
        return Command(c[:4], b'', c[4] or 256, False)
    if c[4]:
        lc = c[4]
        if len(c) not in (5 + lc, 6 + lc):
            return None
        return Command(c[:4], c[5:5+lc], (c[-1] or 256) if len(c) == 6+lc else None, False)
    if len(c) < 7:
        return None
    value = int.from_bytes(c[5:7], 'big')
    if len(c) == 7:
        return Command(c[:4], b'', value or 65536, True)
    if not value or len(c) not in (7+value, 9+value):
        return None
    return Command(c[:4], c[7:7+value], (int.from_bytes(c[-2:], 'big') or 65536) if len(c) == 9+value else None, True)


def application_aid(data: bytes) -> str | None:
    if 6 <= len(data) <= 16 and data.startswith(OPENPGP):
        return 'openpgp'
    if 9 <= len(data) <= 16 and data.startswith(PIV):
        return 'piv'
    if data == FIDO:
        return 'fido'
    return None


def select_target(command: Command) -> str | None:
    if command.header[:3] == b'\0\xa4\4' and command.header[3] in (0, 0x0C):
        return application_aid(command.data)
    return None


class ApplicationReads:
    def __init__(self):
        self.selected = None

    def reset(self):
        self.selected = None

    def observe(self, command: Command, response: bytes):
        # Any SELECT (including failed/unknown or another logical channel) invalidates
        # the cached application assumption. Never use the previous app's policy.
        if command.header[1] == 0xA4:
            self.selected = select_target(command) if response[-2:] == b'\x90\0' or response[-2] == 0x61 else None
        if command.header[1] == 0x70:
            self.selected = None

    def allowed(self, c: Command) -> bool:
        if not c.extended or c.header[0] != 0 or c.le is None or len(c.data) > 255:
            return False
        if select_target(c) in ('piv', 'openpgp'):
            return True
        if self.selected == 'openpgp':
            return (c.header[1] == 0xCA and not c.data) or (
                c.header[1:4] == b'\x47\x81\0' and c.data in (b'\xb6\0', b'\xb8\0', b'\xa4\0', b'\xb6', b'\xb8', b'\xa4'))
        if self.selected == 'piv' and c.header[1:] == b'\xcb\x3f\xff':
            return len(c.data) >= 3 and c.data[0] == 0x5C and c.data[1] == len(c.data)-2
        return False

    def extended_read(self, c: Command, exchange) -> bytes:
        if not self.allowed(c):
            return b'\x67\0'
        requested = min(c.le, 65533)
        amount = min(requested, 256)
        wire = c.header + (bytes([len(c.data)]) + c.data if c.data else b'') + bytes([amount % 256])
        response = self._read_once(wire, amount, exchange)
        output = bytearray()
        for round_no in range(257):
            if len(response) < 2:
                raise ReadMappingError('Mapped read received a truncated status')
            data, sw = response[:-2], response[-2:]
            if len(output) + len(data) > requested:
                raise ReadMappingError('Mapped read exceeded requested length')
            output.extend(data)
            if sw[0] != 0x61 or len(output) == requested:
                result = bytes(output) + sw
                if sw == b'\x90\0':
                    self._check_object(c, bytes(output))
                return result
            if round_no and not data:
                raise ReadMappingError('Mapped GET RESPONSE made no progress')
            if round_no == 256:
                raise ReadMappingError('Mapped GET RESPONSE limit reached')
            amount = min(requested - len(output), sw[1] or 256, 256)
            response = self._read_once(b'\0\xc0\0\0'+bytes([amount % 256]), amount, exchange)
        raise AssertionError('unreachable')

    @staticmethod
    def _read_once(wire: bytes, amount: int, exchange) -> bytes:
        response = exchange(wire)
        # Only correct an explicit read Le once; never infer a retry after I/O failure.
        if len(response) == 2 and response[0] == 0x6C:
            corrected = response[1] or 256
            if corrected <= amount:
                response = exchange(wire[:-1]+response[1:])
        return response

    def _check_object(self, c: Command, data: bytes):
        # Detect a claimed successful but incomplete single BER object. Do not demand
        # TLV encoding from raw DOs (e.g. OpenPGP AID, historical bytes or certificates).
        tag = None
        if self.selected == 'piv' and c.header[1:] == b'\xcb\x3f\xff':
            tag = b'\x53'
        elif self.selected == 'openpgp' and c.header[1:] == b'\x47\x81\0':
            tag = b'\x7f\x49'
        elif self.selected == 'openpgp' and c.header[1] == 0xCA:
            tag = {b'\0\x6e': b'\x6e', b'\x7f\x66': b'\x7f\x66'}.get(c.header[2:])
        if tag is None:
            return
        if not data:
            raise ReadMappingError('Reader reported empty success for a required BER object')
        if not data.startswith(tag) or len(data) <= len(tag):
            raise ReadMappingError('Unexpected object tag in mapped response')
        offset = len(tag)
        first = data[offset]; offset += 1
        if first & 0x80:
            count = first & 0x7F
            if count < 1 or count > 3 or offset + count > len(data):
                raise ReadMappingError('Invalid object length in mapped response')
            size = int.from_bytes(data[offset:offset+count], 'big'); offset += count
        else:
            size = first
        if offset + size != len(data):
            raise ReadMappingError('Reader reported 9000 for incomplete/mismatched BER object')
