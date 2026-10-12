"""Offline serial/VPCD regression tests. No card or serial port is opened."""
import ctypes
from contextlib import contextmanager
import io
import socket
import threading
import time
import unittest
from unittest.mock import patch
from serial_transport import DCB, WindowsSerial, PortInfo, normalize_port
from serial_reader import (Link, ProtocolError, CardLost, Profile, SerialCard, bcc, packet,
                           ats_to_atr, rf_reset_atr, identify, valid_apdu)
from serial_bridge import choose_port, receive_frame, send_frame, Session, DetectionBeep, main

RF_RESET=bytes.fromhex('0048880494968E24CA7B18903920137877710280318066B0840C016E0183009000')
ATR=bytes.fromhex('3B8E800180318066B0840C016E01830090001D')
FW=b'WATCH crw-x 1.8605 05003'
PROFILE=Profile(FW.decode(),0x12)

def response(nad,body):
 h=bytes([((nad&15)<<4)|(nad>>4)])+len(body).to_bytes(2,'big')+body
 return h+bytes([bcc(h)])

class SerialFake:
 baudrate=9600
 def __init__(self, replies=(), fail=None, stale=0):
  self.replies=list(replies);self.fail=fail;self.writes=[];self.data=bytearray();self.stale=stale;self.deadlines=[]
 def check_errors(self):return self.stale
 def write_all(self,data,deadline):
  self.writes.append(data);self.deadlines.append(deadline)
  if self.fail:raise self.fail
  self.data+=self.replies.pop(0)
 def read_exact(self,n,deadline):
  self.deadlines.append(deadline)
  if len(self.data)<n:raise TimeoutError('incomplete simulated frame')
  b=bytes(self.data[:n]);del self.data[:n];return b

class FakeLink:
 def __init__(self,replies):self.replies=list(replies);self.calls=[]
 def exchange(self,nad,c,timeout=None):
  self.calls.append((nad,c))
  value=self.replies.pop(0)
  if isinstance(value,Exception):raise value
  return value

class TransportTests(unittest.TestCase):
 def test_x64_dcb_native_layout(self):
  self.assertEqual(ctypes.sizeof(DCB),28)
  self.assertEqual(DCB.BaudRate.offset,4);self.assertEqual(DCB.ByteSize.offset,18)
 def test_normalize_com_not_arbitrary_path(self):
  self.assertEqual(normalize_port(' com123 '),'COM123')
  for name in ('COM0','COM-1','COM3;del','\\.\\COM3','LPT1'):
   with self.assertRaises(ValueError):normalize_port(name)
 def test_reader_slot_version_packet(self):self.assertEqual(packet(0x12,bytes.fromhex('0019000000')),bytes.fromhex('12000500190000000E'))
 def test_command_length_16bit_and_payload_unchanged(self):
  p=packet(0x15,bytes(range(256))+b'\0'*5);self.assertEqual(p[1:3],b'\x01\x05');self.assertEqual(bcc(p),0)
 def test_wrong_nad_rejected_before_payload(self):
  f=SerialFake([response(0,b'\x90\0')]);l=Link(f)
  with self.assertRaises(ProtocolError):l.exchange(0x15,b'\0\xa4\0\0')
  self.assertTrue(l.poisoned)
 def test_bad_bcc_rejected_not_warning(self):
  r=response(0x15,b'\x90\0');f=SerialFake([r[:-1]+bytes([r[-1]^1])]);l=Link(f)
  with self.assertRaises(ProtocolError):l.exchange(0x15,b'\0\xa4\0\0')
 def test_minimum_status_length(self):
  l=Link(SerialFake([response(0x15,b'\x90')]))
  with self.assertRaises(ProtocolError):l.exchange(0x15,b'\0\xa4\0\0')
 def test_truncated_response_no_replay(self):
  f=SerialFake([response(0x15,b'\x90\0')[:-1]]);l=Link(f)
  with self.assertRaises(TimeoutError):l.exchange(0x15,b'\0\xda\0\0\x01\xaa')
  with self.assertRaises(ProtocolError):l.exchange(0x15,b'\0\xda\0\0\x01\xaa')
  self.assertEqual(len(f.writes),1)
 def test_write_failure_no_replay(self):
  f=SerialFake(fail=OSError('write failed'));l=Link(f)
  with self.assertRaises(OSError):l.exchange(0x15,b'\0\xda\0\0\x01\xaa')
  self.assertEqual(len(f.writes),1);self.assertTrue(l.poisoned)
 def test_stale_input_refuses_new_command(self):
  f=SerialFake(stale=7);l=Link(f)
  with self.assertRaises(ProtocolError):l.exchange(0x15,b'\0\xa4\0\0')
  self.assertEqual(f.writes,[])
 def test_response_larger_than_old_512_buffer(self):
  data=bytes(range(256))*4+b'\x90\0';f=SerialFake([response(0x15,data)])
  self.assertEqual(Link(f).exchange(0x15,b'\0\xca\0\0\0'),data)
 def test_declared_lengths_not_arbitrary_sleep(self):
  f=SerialFake([response(0x15,b'A'*700+b'\x90\0')]);Link(f).exchange(0x15,b'\0\xca\0\0\0')
  self.assertGreater(f.deadlines[-1],f.deadlines[0]);self.assertLess(f.deadlines[-1]-f.deadlines[0],1)
 def test_control_length_not_misread_as_32kb_response(self):
  f=SerialFake([bytes.fromhex('518000D1')]);l=Link(f)
  with self.assertRaises(ProtocolError):l.exchange(0x15,bytes.fromhex('00A4040000'))
  self.assertTrue(l.poisoned)
 def test_input_too_long_never_sent(self):
  with self.assertRaises(ValueError):packet(0x15,b'\0'*65536)
 def test_empty_payload_never_sent(self):
  with self.assertRaises(ValueError):packet(0x15,b'')

class CardTests(unittest.TestCase):
 def card(self,replies):return SerialCard(FakeLink(replies),PROFILE,cold_grace=0)
 def test_actual_reset_variable_prefix(self):self.assertEqual(rf_reset_atr(RF_RESET),ATR)
 def test_four_byte_uid_ats(self):self.assertEqual(rf_reset_atr(bytes.fromhex('00046c78e0ab5f28')+bytes.fromhex('0F78807502866500A708C046009000')),ats_to_atr(bytes.fromhex('0F78807502866500A708C046009000')))
 def test_truncated_ats_rejected(self):
  for data in (b'',b'\x02\x70',b'\x02\x09',b'\x04\0'):
   with self.assertRaises(ProtocolError):ats_to_atr(data)
 def test_missing_iso_dep_sak_rejected(self):
  with self.assertRaises(ProtocolError):rf_reset_atr(b'\0'*5+b'\x02\x08')
 def test_atr_tck(self):self.assertEqual(bcc(ats_to_atr(bytes.fromhex('1278B384008073C021C057597562694B6579'))[1:]),0)
 def test_identification_uses_only_reader_not_sam(self):
  l=FakeLink([FW+b'\x90\0']);self.assertEqual(identify(l),PROFILE);self.assertEqual(l.calls,[(0x12,bytes.fromhex('0019000000'))])
 def test_unknown_reader_rejected(self):
  for reply in [b'not-Watchdata\x90\0',b'\x6f\xf0']:
   with self.assertRaises(ProtocolError):identify(FakeLink([reply]))
 def test_sam_and_contact_modes_not_exposed(self):
  for mode in ('contact','sam','auto'):
   with self.assertRaises(ValueError):SerialCard(FakeLink([]),PROFILE,mode)
 def test_reset_absent(self):
  c=self.card([b'\x62\0']);self.assertFalse(c.activate());self.assertFalse(c.powered);self.assertEqual(c.atr,b'')
 def test_successful_reset_then_business(self):
  c=self.card([RF_RESET+b'\x90\0',b'\x90\0']);self.assertTrue(c.activate());self.assertEqual(c.atr,ATR)
  cmd=bytes.fromhex('84DA00000401020304');self.assertEqual(c.transmit(cmd),b'\x90\0');self.assertEqual(c.link.calls[-1],(0x15,cmd))
 def test_61_and_6c_transparent(self):
  c=self.card([RF_RESET+b'\x90\0',b'\x61\x80',b'\x6c\x10']);c.activate()
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F00')),b'\x61\x80');self.assertEqual(c.transmit(bytes.fromhex('00CA004F00')),b'\x6c\x10');self.assertEqual(len(c.link.calls),3)
 def test_card_failure_disconnects_no_duplicate_write(self):
  c=self.card([RF_RESET+b'\x90\0',b'\x6f\xf0']);c.activate()
  with self.assertRaises(CardLost):c.transmit(bytes.fromhex('00DA000001AA'))
  self.assertEqual(len(c.link.calls),2);self.assertFalse(c.powered)
 def test_bad_apdu_rejected_without_serial_write(self):
  c=self.card([RF_RESET+b'\x90\0']);c.activate();self.assertEqual(c.transmit(b'\0\xa4'),b'\x67\0');self.assertEqual(len(c.link.calls),1)
 def test_over_firmware_command_limit_not_sent(self):
  c=self.card([RF_RESET+b'\x90\0']);c.activate()
  cmd=bytes.fromhex('00DA000000012C')+b'A'*300
  self.assertEqual(c.transmit(cmd),b'\x67\0');self.assertEqual(len(c.link.calls),1)
 def test_extended_read_cannot_return_truncated_success(self):
  c=self.card([RF_RESET+b'\x90\0']);c.activate()
  self.assertEqual(c.transmit(bytes.fromhex('80CA0000000200')),b'\x67\0');self.assertEqual(len(c.link.calls),1)
 def test_firmware_reserved_8010_cannot_falsely_report_write_success(self):
  c=self.card([RF_RESET+b'\x90\0']);c.activate()
  self.assertEqual(c.transmit(bytes.fromhex('801000000401020304')),b'\x6d\0');self.assertEqual(len(c.link.calls),1)
 def test_extended_apdu_shape(self):
  self.assertTrue(valid_apdu(bytes.fromhex('00CA0000000100')))
  self.assertFalse(valid_apdu(bytes.fromhex('00CA000000AA')))
 def test_poweroff_invalidates_then_atr_resets(self):
  c=self.card([RF_RESET+b'\x90\0',RF_RESET+b'\x90\0']);c.activate();session=Session(c)
  self.assertIsNone(session.handle(b'\0'));self.assertFalse(c.powered)
  self.assertEqual(session.handle(b'\4'),ATR);self.assertEqual(len(c.link.calls),2)
 def test_reset_failure_does_not_reuse_cached_atr(self):
  c=self.card([RF_RESET+b'\x90\0',b'\x6f\xf0']);c.activate()
  with self.assertRaises(CardLost):Session(c).handle(b'\2')
  self.assertEqual(c.atr,b'');self.assertFalse(c.powered)
 def test_unknown_control(self):
  with self.assertRaises(ProtocolError):Session(self.card([])).handle(b'\x7f')
 def test_health_does_not_reset_or_touch_sam(self):
  c=self.card([FW+b'\x90\0']);c.reader_alive();self.assertEqual(c.link.calls,[(0x12,bytes.fromhex('0019000000'))])
 def test_cold_grace_waits_only_remaining_time(self):
  c=self.card([b'\x90\0']);c.atr=ATR;c.medium='rf';c.powered=True;c.ready_at=100.4
  with patch('serial_reader.time.monotonic',return_value=100.1),patch('serial_reader.time.sleep') as sleep:
   c.transmit(bytes.fromhex('00A4040000'));self.assertAlmostEqual(sleep.call_args.args[0],.3)

class EntryTests(unittest.TestCase):
 def test_number_choice_with_multiple_ports(self):self.assertEqual(choose_port([PortInfo('COM3','x'),PortInfo('COM10','y')],lambda _: '2',lambda _:None),'COM10')
 def test_single_port_still_requires_choice(self):
  seen=[]
  self.assertEqual(choose_port([PortInfo('COM3','x')],lambda prompt:seen.append(prompt) or 'COM3',lambda _:None),'COM3');self.assertEqual(len(seen),1)
 def test_reprompt_invalid_selection(self):
  answers=iter(['0','COM9','garbage','1']);self.assertEqual(choose_port([PortInfo('COM3','x')],lambda _:next(answers),lambda _:None),'COM3')
 def test_cancel(self):self.assertIsNone(choose_port([PortInfo('COM3','x')],lambda _:'q',lambda _:None))
 def test_empty_ports(self):
  with self.assertRaises(OSError):choose_port([],lambda _:'1',lambda _:None)
 def test_closed_stdin_requires_explicit_port(self):
  def eof(_):raise EOFError()
  with self.assertRaises(ValueError):choose_port([PortInfo('COM3','x')],eof,lambda _:None)
 def test_beep_unsupported_cached_host_fallback_each_detection(self):
  l=FakeLink([b'\x6f\xf0']);sounds=[];logs=[];b=DetectionBeep(logs.append,lambda:sounds.append(1))
  b.detected(l,PROFILE);b.detected(l,PROFILE);self.assertEqual(len(sounds),2);self.assertEqual(len(l.calls),1);self.assertIn('PC speaker',logs[0])
 def test_reader_beep_success_no_fallback(self):
  sounds=[];b=DetectionBeep(lambda _:None,lambda:sounds.append(1));b.detected(FakeLink([b'\x90\0']),PROFILE);self.assertEqual(sounds,[])
 def test_sound_failure_does_not_fail_card_detection(self):
  def fail():raise RuntimeError('no audio')
  logs=[];b=DetectionBeep(logs.append,fail);b.supported=False;b.detected(FakeLink([]),PROFILE)
  self.assertIn('I/O continues',logs[0])
 def test_no_sam_cli_option(self):
  with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit):main(['--mode','contact'])

@contextmanager
def socketpair():
 a,b=socket.socketpair()
 try:
  yield a,b
 finally:
  a.close();b.close()

class SocketTests(unittest.TestCase):
 def test_network_byte_order_and_roundtrip(self):
  with socketpair() as (a,b):send_frame(a,b'\x90\0');self.assertEqual(receive_frame(b),b'\x90\0')
 def test_partial_header_timeout(self):
  with socketpair() as (a,b):
   a.sendall(b'\0')
   with self.assertRaises(TimeoutError):receive_frame(b,.03)
 def test_eof_during_body(self):
  with socketpair() as (a,b):
   a.sendall(b'\0\x05\0');a.shutdown(socket.SHUT_WR)
   with self.assertRaises(EOFError):receive_frame(b)
 def test_coalesced_frames_remain_distinct(self):
  with socketpair() as (a,b):
   a.sendall(b'\0\1\4\0\1\2');self.assertEqual(receive_frame(b),b'\4');self.assertEqual(receive_frame(b),b'\2')
 def test_zero_length_rejected(self):
  with socketpair() as (a,b):
   a.sendall(b'\0\0')
   with self.assertRaises(ProtocolError):receive_frame(b)
 def test_fragmented_message(self):
  with socketpair() as (a,b):
   def writer():
    for v in b'\0\x05\0\xa4\4\0\0':a.sendall(bytes([v]));time.sleep(.003)
   t=threading.Thread(target=writer);t.start()
   try:self.assertEqual(receive_frame(b,1),bytes.fromhex('00A4040000'))
   finally:t.join()

if __name__=='__main__':unittest.main(verbosity=2)
