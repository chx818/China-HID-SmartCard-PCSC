"""Read-only FIDO/PIV/OpenPGP check for the serial CRW-Xs.

No PIN verification, key generation, ECC operations, credentials, signing,
decryption or writes. Missing objects are reported separately from transport errors.
"""
import argparse
import json
import sys
import time
from serial_transport import available_ports, normalize_port
from serial_reader import connect_reader, SerialCard
from serial_bridge import choose_port


def complete(card, command):
    response = card.transmit(bytes.fromhex(command))
    output = bytearray()
    for _ in range(257):
        if len(response) < 2:
            raise OSError('Missing APDU status')
        output.extend(response[:-2])
        if len(output) > 65533:
            raise OSError('Read response limit')
        if response[-2] != 0x61:
            return bytes(output) + response[-2:]
        if not response[:-2] and output:
            raise OSError('GET RESPONSE made no progress')
        response = card.transmit(bytes.fromhex('00C00000')+response[-1:])
    raise OSError('GET RESPONSE round limit')


def inspect(card):
    report = {'firmware': card.profile.firmware, 'scope': 'public reads only', 'applications': {}}
    configs = [
        ('fido', '00A4040008A0000006472F000100', [('u2f_version', '0003000000')]),
        ('piv', '00A4040009A0000003080000100000', [
            ('ccc', '00CB3FFF0000055C035FC1071000'),
            ('chuid', '00CB3FFF0000055C035FC1021000'),
            ('authentication_certificate', '00CB3FFF0000055C035FC1051000'),
            ('signature_certificate', '00CB3FFF0000055C035FC10A1000'),
            ('key_management_certificate', '00CB3FFF0000055C035FC10B1000')]),
        ('openpgp', '00A4040006D2760001240100', [
            ('application_data', '00CA006E000400'),
            ('extended_capabilities', '00CA7F66000400'),
            ('cardholder_data', '00CA0065000400'),
            ('existing_signing_public_key', '00478100000002B6001000'),
            ('existing_decryption_public_key', '00478100000002B8001000')]),
    ]
    for name, select, reads in configs:
        selected = complete(card, select)
        item = {'select_sw': selected[-2:].hex().upper(), 'read_objects': {}}
        report['applications'][name] = item
        if selected[-2:] != b'\x90\0':
            item['state'] = 'not_selectable'
            continue
        item['state'] = 'selected'
        for label, command in reads:
            start = time.monotonic()
            response = complete(card, command)
            sw = response[-2:]
            state = 'read' if sw == b'\x90\0' else 'not_present' if sw in (b'\x6a\x82', b'\x6a\x88') else 'card_status'
            item['read_objects'][label] = {'state': state, 'sw': sw.hex().upper(), 'data_bytes': len(response)-2,
                                                 'ms': round((time.monotonic()-start)*1000, 1)}
    report['ctap2_8010'] = 'blocked: this firmware swallows the CTAP2 instruction; not a completed FIDO2 test'
    report['crypto_operations_tested'] = False
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Otherwise list COM ports and ask')
    args = parser.parse_args(argv)
    serial = None
    try:
        port = normalize_port(args.port) if args.port else choose_port(available_ports())
        if port is None:
            return 0
        serial, link, profile = connect_reader(port)
        card = SerialCard(link, profile)
        if not card.activate():
            raise OSError('No RF card detected')
        print(json.dumps(inspect(card), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as ex:
        print(str(ex), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if serial is not None:
            serial.close()

if __name__ == '__main__':
    raise SystemExit(main())
