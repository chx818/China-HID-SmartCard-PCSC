"""CRW-Xs serial protocol and VPCD card adapter; independent of USB/HID bridges."""
from __future__ import annotations
from dataclasses import dataclass
import threading
import time
from serial_transport import SerialError, WindowsSerial
from app_compat import ApplicationReads, parse_command

RESET = bytes.fromhex('0012000000')
VERSION = bytes.fromhex('0019000000')

class ProtocolError(SerialError):
    pass

class CardLost(SerialError):
    pass

def bcc(data: bytes) -> int:
    result = 0
    for b in data:
        result ^= b
    return result

def packet(nad: int, command: bytes) -> bytes:
    if not 0 <= nad <= 255 or not 1 <= len(command) <= 65535:
        raise ValueError('Invalid serial NAD or command length')
    frame = bytes([nad]) + len(command).to_bytes(2, 'big') + command
    return frame + bytes([bcc(frame)])

class Link:
    def __init__(self, serial, timeout=30.0):
        self.serial, self.timeout = serial, timeout
        self.poisoned = False
        self.lock = threading.Lock()

    def exchange(self, nad: int, command: bytes, timeout: float | None = None) -> bytes:
        frame = packet(nad, bytes(command))
        with self.lock:
            if self.poisoned:
                raise ProtocolError('Serial stream is untrusted after an earlier error; reopen required')
            started = time.monotonic()
            timeout = self.timeout if timeout is None else timeout
            # Reserve wire time separately from card computation. 8E1 uses 11 bits per byte.
            wire_byte = 11.0 / self.serial.baudrate
            deadline = started + timeout + len(frame) * wire_byte
            try:
                if self.serial.check_errors():
                    raise ProtocolError('Unsolicited/stale serial data before command; refusing to associate it with a new APDU')
                self.serial.write_all(frame, deadline)
                header = self.serial.read_exact(3, deadline)
                expected = ((nad & 15) << 4) | (nad >> 4)
                if header[0] != expected:
                    raise ProtocolError(f'Wrong response NAD 0x{header[0]:02X}, expected 0x{expected:02X}')
                count = int.from_bytes(header[1:], 'big')
                if count < 2:
                    raise ProtocolError('Response does not contain SW1/SW2')
                if count > 8192:
                    raise ProtocolError('Unqualified response/control-frame length; refusing an unbounded wait')
                deadline += (count + 4) * wire_byte
                tail = self.serial.read_exact(count + 1, deadline)
                if bcc(header + tail) != 0:
                    raise ProtocolError('BCC mismatch; response rejected')
                return tail[:-1]
            except (OSError, ValueError):
                # A partially written/read frame has no usable request identity. Never replay.
                self.poisoned = True
                raise

def ats_to_atr(ats: bytes) -> bytes:
    if not ats or ats[0] != len(ats) or len(ats) > 20:
        raise ProtocolError('Invalid ATS length')
    offset = 1
    if len(ats) > 1:
        t0 = ats[1]; offset = 2
        if t0 & 0x80 or (t0 & 15) > 8:
            raise ProtocolError('Invalid ATS T0/FSCI')
        for bit in (0x10, 0x20, 0x40):
            if t0 & bit:
                if offset >= len(ats):
                    raise ProtocolError('Truncated ATS interface bytes')
                offset += 1
    history = ats[offset:]
    if len(history) > 15:
        raise ProtocolError('Too many ATS historical bytes')
    partial = bytes([0x3B, 0x80 | len(history), 0x80, 1]) + history
    return partial + bytes([bcc(partial[1:])])

def rf_reset_atr(data: bytes) -> bytes:
    # CRW-Xs returns ATQA + anticollision bytes + SAK + ATS; prefix length
    # varies with UID/cascade levels. Do not use a fixed offset or a canned ATR.
    candidates = []
    for offset in range(3, len(data)):
        if not data[offset - 1] & 0x20 or data[offset] != len(data) - offset:
            continue
        try:
            candidates.append(ats_to_atr(data[offset:]))
        except ProtocolError:
            continue
    if len(candidates) != 1:
        raise ProtocolError('RF reset is not an unambiguous Type A ISO-DEP ATS; this card/firmware is not qualified')
    return candidates[0]

@dataclass(frozen=True)
class Profile:
    firmware: str
    system_nad: int
    rf_nad: int = 0x15


def identify(link: Link) -> Profile:
    # The shipped VB API and the later W2160 PDF disagree about NAD 00/12.
    # Probe VERSION (read-only), and require the vendor identity before choosing a map.
    # Serial CRW-Xs system endpoint only. Do not probe a SAM or assume USB routing.
    for system in (0x12,):
        response = link.exchange(system, VERSION, timeout=1.0)
        if response[-2:] != b'\x90\0':
            continue
        data = response[:-2]
        if b'WATCH' not in data.upper() or not (b'CRW' in data.upper() or b'W2160' in data.upper()):
            continue
        firmware = data.decode('ascii', errors='replace').strip('\x00 ')
        return Profile(firmware, system)
    raise ProtocolError('Serial peer did not identify as a Watchdata CRW-X/W2160 reader')

class SerialCard:
    def __init__(self, link: Link, profile: Profile, mode='rf', cold_grace=.4):
        if mode != 'rf':
            raise ValueError('This serial reader has RF plus SAM; SAM access is not part of the bridge')
        self.link, self.profile, self.mode = link, profile, mode
        self.cold_grace = cold_grace
        self.medium = None
        self.atr = b''
        self.ready_at = 0.0
        self.generation = 0
        self.powered = False
        self.application_reads = ApplicationReads()

    @property
    def nad(self):
        if self.medium == 'rf':
            return self.profile.rf_nad
        raise CardLost('No active card interface')

    def _activate(self, medium):
        if medium != 'rf':
            raise ValueError('Only RF is supported by this entry')
        nad = self.profile.rf_nad
        result = self.link.exchange(nad, RESET, timeout=2.0)
        if result[-2:] in (b'\x62\0', b'\x62\x01', b'\x6f\xf0'):
            return False
        if result[-2:] != b'\x90\0':
            raise CardLost('Reset failed with SW=' + result[-2:].hex().upper())
        atr = rf_reset_atr(result[:-2])
        self.atr, self.medium, self.powered = atr, medium, True
        self.ready_at = time.monotonic() + (self.cold_grace if medium == 'rf' else 0)
        self.generation += 1
        return True

    def activate(self):
        self.application_reads.reset()
        self.atr, self.medium, self.powered = b'', None, False
        return self._activate('rf')

    def reset(self):
        self.application_reads.reset()
        medium = self.medium
        self.atr, self.powered = b'', False
        if medium is None or not self._activate(medium):
            raise CardLost('Card absent during reset')

    def power_off(self):
        self.application_reads.reset()
        # On this old firmware the documented RF-off command returns 6D00.
        # Invalidate the logical session now; the next ON/ATR does a real card reset.
        self.atr, self.powered = b'', False

    def transmit(self, command):
        if not self.powered:
            raise CardLost('Card is logically powered off')
        parsed = parse_command(command)
        if parsed is None:
            return b'\x67\0'
        if parsed.extended:
            try:
                response = self.application_reads.extended_read(parsed, self._raw_apdu)
            except OSError:
                self.application_reads.reset()
                raise
            self.application_reads.observe(parsed, response)
            return response
        if len(command) > 261:
            return b'\x67\0'
        # Verified on 1.8605: this reader absorbs 80 10, including CTAP2 GetInfo,
        # and returns empty 9000 without forwarding it. A status-only success is invalid CTAP.
        if self.profile.firmware.startswith('WATCH crw-x 1.8605') and command[:2] == b'\x80\x10':
            return b'\x6d\0'
        try:
            response = self._raw_apdu(command)
        except OSError:
            self.application_reads.reset()
            raise
        self.application_reads.observe(parsed, response)
        return response

    def _raw_apdu(self, command):
        delay = self.ready_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        response = self.link.exchange(self.nad, command)
        if response[-2:] == b'\x6f\xf0':
            self.atr, self.powered = b'', False
            raise CardLost('Reader reported card communication failure (6FF0); command not replayed')
        return response

    def reader_alive(self):
        # This checks the serial reader only, not physical card presence.
        result = self.link.exchange(self.profile.system_nad, VERSION, timeout=1)
        if result[-2:] != b'\x90\0' or result[:-2].decode('ascii', errors='replace').strip('\0 ') != self.profile.firmware:
            raise ProtocolError('Reader health/identity changed')


def valid_apdu(c: bytes) -> bool:
    if not 4 <= len(c) <= 65535:
        return False
    if len(c) <= 5:
        return True
    if c[4]:
        return len(c) in (5 + c[4], 6 + c[4])
    if len(c) < 7:
        return False
    if len(c) == 7:
        return True
    lc = int.from_bytes(c[5:7], 'big')
    return lc > 0 and len(c) in (7 + lc, 9 + lc)


def connect_reader(port, baudrate=9600, parity='auto', timeout=30.0):
    choices = ('E', 'N') if parity == 'auto' else (parity,)
    errors = []
    for current in choices:
        serial = WindowsSerial(port, baudrate, current)
        try:
            serial.open()
            link = Link(serial, timeout)
            profile = identify(link)
            return serial, link, profile
        except (OSError, ValueError) as ex:
            serial.close()
            errors.append(f'{current}: {ex}')
            # A busy/missing port is not a parity problem and must not be opened repeatedly.
            if isinstance(ex, OSError) and getattr(ex, 'errno', None) in (2, 5, 32):
                break
    raise SerialError('Reader connection failed: ' + '; '.join(errors))
