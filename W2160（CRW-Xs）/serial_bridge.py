"""Watchdata CRW-Xs serial -> Windows VPCD. Run without --port for interactive selection."""
from __future__ import annotations
import argparse
import ipaddress
import select
import socket
import struct
import sys
import time
from serial_transport import SerialError, available_ports, normalize_port
from serial_reader import CardLost, ProtocolError, SerialCard, connect_reader


def choose_port(ports, input_fn=input, output=print):
    if not ports:
        raise SerialError('No available COM ports found. Connect the serial adapter and retry.')
    output('Available serial ports (not opened during enumeration):')
    for i, port in enumerate(ports, 1):
        output(f'  {i}. {port.name}  {port.description}')
    names = {p.name for p in ports}
    while True:
        try:
            answer = input_fn('Select number or COM name; Q to cancel: ').strip()
        except EOFError as ex:
            raise ValueError('No interactive input; specify --port COM3 for automation') from ex
        if answer.lower() == 'q':
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(ports):
            return ports[int(answer) - 1].name
        try:
            name = normalize_port(answer)
        except ValueError:
            name = ''
        if name in names:
            return name
        output('Invalid selection; choose one of the listed ports.')


def receive_frame(sock, timeout=3.0):
    deadline = time.monotonic() + timeout
    def read(n):
        data = bytearray()
        while len(data) < n:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('VPCD partial-frame deadline')
            sock.settimeout(remaining)
            part = sock.recv(n - len(data))
            if not part:
                raise EOFError('VPCD closed by peer')
            data.extend(part)
        return bytes(data)
    try:
        length = struct.unpack('!H', read(2))[0]
        if length == 0:
            raise ProtocolError('Empty VPCD frame')
        return read(length)
    finally:
        sock.settimeout(None)


def send_frame(sock, payload):
    if not 1 <= len(payload) <= 65535:
        raise ProtocolError('VPCD response length out of bounds')
    sock.settimeout(3)
    try:
        sock.sendall(struct.pack('!H', len(payload)) + payload)
    finally:
        sock.settimeout(None)


class Session:
    def __init__(self, card):
        self.card = card
        self.frames = 0
        self.last_request = 'none'

    def handle(self, data):
        self.frames += 1
        self.last_request = f'CTRL({data[0]})' if len(data) == 1 else f'APDU(len={len(data)})'
        if len(data) == 1:
            if data[0] == 0:
                self.card.power_off()
                return None
            if data[0] in (1, 2):
                self.card.reset()
                return None
            if data[0] == 4:
                if not self.card.powered:
                    self.card.reset()
                return self.card.atr
            raise ProtocolError('Unknown VPCD control')
        return self.card.transmit(data)

    def run(self, sock, stop):
        last_activity = time.monotonic()
        while not stop():
            readable, _, _ = select.select([sock], [], [], .05)
            if readable:
                payload = receive_frame(sock)
                reply = self.handle(payload)
                if reply is not None:
                    send_frame(sock, reply)
                # ATR requests do not count as card business and must not starve USB/serial removal checks.
                if payload != b'\x04':
                    last_activity = time.monotonic()
            elif time.monotonic() - last_activity >= 5:
                self.card.reader_alive()
                last_activity = time.monotonic()


def endpoint(value):
    if value.lower() == 'localhost':
        return '127.0.0.1'
    try:
        address = ipaddress.ip_address(value)
    except ValueError as ex:
        raise argparse.ArgumentTypeError('Invalid loopback address') from ex
    if not address.is_loopback:
        raise argparse.ArgumentTypeError('VPCD address must be loopback')
    return str(address)


class DetectionBeep:
    """One notification per detection, before any VPCD connect. Explicit host fallback."""
    def __init__(self, emit=print, host_beep=None):
        self.emit = emit
        self.supported = None
        self.host_beep = host_beep or self._host

    @staticmethod
    def _host():
        import winsound
        try:
            winsound.Beep(1600, 80)
        except RuntimeError:
            winsound.MessageBeep(winsound.MB_OK)

    def detected(self, link, profile):
        if self.supported is not False:
            response = link.exchange(profile.system_nad, bytes.fromhex('B0F2010000'), timeout=1)
            if response[-2:] == b'\x90\0':
                self.supported = True
                return
            if self.supported is None:
                self.emit('Reader rejected the documented buzzer command (SW=' + response[-2:].hex().upper() + '); using PC speaker for detection beep.')
            self.supported = False
        try:
            self.host_beep()
        except (RuntimeError, OSError) as ex:
            self.emit('Detection sound unavailable; card I/O continues (' + type(ex).__name__ + ').')


def run(args):
    ports = available_ports()
    if args.list_ports:
        for p in ports:
            print(f'{p.name}\t{p.description}')
        return 0
    port = normalize_port(args.port) if args.port else choose_port(ports)
    if port is None:
        print('Cancelled; no port opened.')
        return 0
    started = time.monotonic()
    stop = lambda: args.run_seconds > 0 and time.monotonic() - started >= args.run_seconds
    print(f'W2160 serial bridge: {port}; RF only; VPCD={args.host}:{args.vpcd_port}', flush=True)
    print('Short wire APDUs; PIV/OpenPGP extended read mapping; no payload logging. Reader status is monitored; idle card-removal notification is not qualified on this firmware.', flush=True)
    announced = False
    warned_vpcd = False
    notification = DetectionBeep()
    while not stop():
        serial, sock = None, None
        try:
            serial, link, profile = connect_reader(port, args.baudrate, args.parity, args.apdu_timeout)
            print(f'Reader connected: {port} {args.baudrate} 8{serial.parity}1; {profile.firmware}; system NAD={profile.system_nad:02X}', flush=True)
            announced = True
            card = SerialCard(link, profile)
            while not stop():
                if card.activate():
                    break
                time.sleep(.4)
            if stop():
                break
            notification.detected(link, profile)
            print(f'Card detected: {card.medium}; ATR={card.atr.hex().upper()}', flush=True)
            # Keep the activated card while VPCD is unavailable. Do not reset/beep it on each TCP retry.
            while not stop():
                try:
                    sock = socket.create_connection((args.host, args.vpcd_port), timeout=2)
                    break
                except OSError as ex:
                    if not warned_vpcd:
                        print(f'Waiting for VPCD: {ex}', flush=True); warned_vpcd = True
                    time.sleep(.5)
            if stop():
                break
            with sock:
                warned_vpcd = False
                sock.settimeout(None); sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print('Connected to VPCD; card ready.', flush=True)
                session = Session(card)
                try:
                    session.run(sock, stop)
                except (OSError, EOFError, ValueError) as ex:
                    print(f'Session ended: {ex}; medium={card.medium}; last={session.last_request}; frames={session.frames}', flush=True)
                    raise
        except (OSError, EOFError, ValueError) as ex:
            if not announced:
                print(f'Cannot start: {ex}', file=sys.stderr, flush=True)
                return 1
            print(f'Reconnecting {port}: {type(ex).__name__}', flush=True)
            if not stop():
                time.sleep(.5)
        finally:
            if sock is not None:
                sock.close()
            if serial is not None:
                serial.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='e.g. COM3; otherwise enumerate and ask before opening')
    parser.add_argument('--list-ports', action='store_true')
    parser.add_argument('--baudrate', type=int, choices=[9600,19200,38400,57600,115200], default=9600)
    parser.add_argument('--parity', choices=['auto','E','N'], default='auto')
    parser.add_argument('--host', type=endpoint, default='127.0.0.1')
    parser.add_argument('--vpcd-port', type=int, default=35963)
    parser.add_argument('--apdu-timeout', type=float, default=30)
    parser.add_argument('--run-seconds', type=float, default=0, help='0 runs until Ctrl+C; native I/O has bounded deadlines')
    args = parser.parse_args(argv)
    if not 1 <= args.vpcd_port <= 65535 or not 0 < args.apdu_timeout <= 300 or args.run_seconds < 0:
        parser.error('Invalid port or time limit')
    try:
        return run(args)
    except KeyboardInterrupt:
        print('\nStopped; serial handle released.')
        return 0
    except (ValueError, OSError) as ex:
        print(str(ex), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
