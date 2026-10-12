"""No hardware access. Tests the common Watchdata USB core and all critical boundaries."""
import ctypes as C
import socket
import threading
import time
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from watchdata_usb.transport import Device,Overlapped,HidTransport,Api
from watchdata_usb.protocol import encode,Link,ProtocolError,MAX_COMMAND
from watchdata_usb.card import parse_apdu,contact_atr,rf_atr,t0_transmit
from watchdata_usb.reader import Reader,CardLost,VERSION,RESET,RF_TYPE_A,RF_OFF,BEEP
from watchdata_usb.bridge import choose,receive,send,Session

RF=bytes.fromhex('0400C5841F78280F788071020031C173C84000009000')
ATR=bytes.fromhex('3B8A80010031C173C8400000900090')
CONTACT=bytes.fromhex('3B6E000080318066B0840C016E0183009000')
DEVICE=Device('test-device',0x0A1F,'Test W8298')

def reports(nad,data):
 return [bytes([0,(nad>>4)|((nad&15)<<4),n|(0x20 if start+61<len(data) else 0),len(data[start:start+61])])+data[start:start+61]+bytes(61-len(data[start:start+61])) for n,start in enumerate(range(0,len(data),61))]

class Transport:
 def __init__(self,rx):self.rx=list(rx);self.sent=[];self.deadlines=[]
 def write(self,r,d):self.sent.append(bytes(r));self.deadlines.append(d);return 65
 def read(self,d):
  self.deadlines.append(d)
  if not self.rx:raise TimeoutError('injected missing report')
  r=self.rx.pop(0)
  if isinstance(r,Exception):raise r
  return r

class FakeLink:
 def __init__(self,replies):self.replies=list(replies);self.sent=[];self.poisoned=False
 def exchange(self,n,c,timeout=None):
  self.sent.append((n,bytes(c)))
  r=self.replies.pop(0)
  if isinstance(r,Exception):raise r
  return r

class FramingTests(unittest.TestCase):
 def test_short_packet_layout(self):
  p=encode(0x15,bytes.fromhex('80100000010400'));self.assertEqual(len(p),1);self.assertEqual(p[0][:11],bytes.fromhex('0015000780100000010400'));self.assertEqual(len(p[0]),65)
 def test_61_62_and_976_byte_tx(self):
  for size,expected in [(61,1),(62,2),(976,16)]:
   payload=(bytes(range(256))*4)[:size];r=encode(0x12,payload);self.assertEqual(len(r),expected);self.assertEqual(b''.join(x[4:4+x[3]] for x in r),payload)
   for n,x in enumerate(r):self.assertEqual(x[2],n|(0x20 if n<expected-1 else 0))
 def test_unqualified_wrap_not_sent(self):
  with self.assertRaises(ValueError):encode(0x15,bytes(977))
 def test_no_sam_or_keyboard_commands(self):
  for n in [0x13,0x14,0x16,0x17,0x1A]:
   with self.assertRaises(ValueError):encode(n,b'1234')
 def test_empty_message_rejected(self):
  with self.assertRaises(ValueError):encode(0,b'')
 def test_reassembles_multiple_reports(self):
  body=b'A'*247+b'\x61\x47';t=Transport(reports(0x15,body));self.assertEqual(Link(t).exchange(0x15,b'1234'),body);self.assertEqual(len(t.deadlines),6)
 def test_one_deadline_for_complete_transaction(self):
  t=Transport(reports(0x15,b'A'*130+b'\x90\0'));Link(t).exchange(0x15,b'1234');self.assertEqual(len(set(t.deadlines)),1)
 def assert_bad(self,rx):
  t=Transport(rx);l=Link(t)
  with self.assertRaises(OSError):l.exchange(0x15,b'1234')
  self.assertTrue(l.poisoned)
  with self.assertRaises(ProtocolError):l.exchange(0x15,b'write')
  self.assertEqual(len(t.sent),1)
 def test_missing_final_fragment_no_partial_success(self):self.assert_bad(reports(0x15,b'A'*100+b'\x90\0')[:1])
 def test_wrong_nad(self):self.assert_bad(reports(0x12,b'\x90\0'))
 def test_wrong_report_id(self):
  r=bytearray(reports(0x15,b'\x90\0')[0]);r[0]=1;self.assert_bad([r])
 def test_short_hid_report(self):self.assert_bad([reports(0x15,b'\x90\0')[0][:-1]])
 def test_invalid_fragment_size(self):
  for n in (0,62,255):
   r=bytearray(reports(0x15,b'\x90\0')[0]);r[3]=n;self.assert_bad([r])
 def test_duplicate_skipped_sequence(self):
  for seq in (0,2):
   r=reports(0x15,b'A'*62+b'\x90\0');last=bytearray(r[1]);last[2]=seq;self.assert_bad([r[0],last])
 def test_unknown_flag(self):
  r=bytearray(reports(0x15,b'\x90\0')[0]);r[2]=0x40;self.assert_bad([r])
 def test_sw_split_between_reports(self):
  body=b'A'*60+b'\x90\0';self.assertEqual(Link(Transport(reports(0x15,body))).exchange(0x15,b'1234'),body)
 def test_max_response(self):
  body=b'A'*974+b'\x90\0';self.assertEqual(Link(Transport(reports(0x15,body))).exchange(0x15,b'1234'),body)
 def test_response_wrap_fails(self):
  r=reports(0x15,b'A'*976);r[-1]=r[-1][:2]+b'\x2f'+r[-1][3:];self.assert_bad(r)
 def test_single_status_byte(self):self.assert_bad(reports(0x15,b'\x90'))
 def test_timeout_not_replayed(self):self.assert_bad([TimeoutError('after command')])

class CardTests(unittest.TestCase):
 def test_real_contact_atr(self):self.assertEqual(contact_atr(CONTACT),(CONTACT,0))
 def test_t1_atr(self):self.assertEqual(contact_atr(bytes.fromhex('3B800181'))[1],1)
 def test_bad_atr(self):
  for h in ['3B80','0000','3B800180','3B0000','3B01']:
   with self.assertRaises(ProtocolError):contact_atr(bytes.fromhex(h))
 def test_actual_rf_atr(self):self.assertEqual(rf_atr(RF),ATR)
 def test_rf_unrecognized_frame_rejected(self):
  with self.assertRaises(ProtocolError):rf_atr(b'\0'*10)
 def test_parse_extended_and_unchanged_80_10(self):
  c=bytes.fromhex('80100000000001040000');p=parse_apdu(c);self.assertTrue(p.extended);self.assertEqual(p.data,b'\4');self.assertEqual(p.le,65536)
 def test_case1_normalized(self):
  sent=[];t0_transmit(bytes.fromhex('00840000'),lambda c:sent.append(c) or b'\x90\0');self.assertEqual(sent,[bytes.fromhex('0084000000')])
 def test_case4_and_61(self):
  sent=[];r=iter([b'\x61\3',b'ABC\x90\0'])
  response=t0_transmit(bytes.fromhex('00A4040002AABB00'),lambda c:sent.append(c) or next(r));self.assertEqual(response,b'ABC\x90\0');self.assertEqual(sent[0],bytes.fromhex('00A4040002AABB'))
 def test_case2_6c_once(self):
  sent=[];r=iter([b'\x6c\x10',b'\x6c\x20']);self.assertEqual(t0_transmit(bytes.fromhex('00CA004F00'),lambda c:sent.append(c) or next(r)),b'\x6c\x20');self.assertEqual(len(sent),2)
 def test_write_data_not_changed_for_6c(self):
  sent=[];c=bytes.fromhex('00DA000001AA');self.assertEqual(t0_transmit(c,lambda x:sent.append(x) or b'\x6c\1'),b'\x6c\1');self.assertEqual(sent,[c])
 def test_secure_message_never_automatically_continued(self):
  sent=[];c=bytes.fromhex('84DA000001AA');self.assertEqual(t0_transmit(c,lambda x:sent.append(x) or b'\x61\1'),b'\x61\1');self.assertEqual(sent,[c])
 def test_get_response_keeps_logical_channel(self):
  sent=[];r=iter([b'\x61\1',b'A\x90\0']);t0_transmit(bytes.fromhex('01CA004F00'),lambda c:sent.append(c) or next(r));self.assertEqual(sent[1][0],1)
 def test_zero_progress_detected(self):
  with self.assertRaises(ProtocolError):t0_transmit(bytes.fromhex('00CA004F00'),lambda c:b'\x61\1')
 def test_timeout_does_not_replay(self):
  calls=[]
  def fail(c):calls.append(c);raise TimeoutError('unknown outcome')
  with self.assertRaises(TimeoutError):t0_transmit(bytes.fromhex('00DA000001AA'),fail)
  self.assertEqual(len(calls),1)
 def test_extended_t0_not_truncated(self):
  c=bytes.fromhex('00CA006E000400');sent=[];t0_transmit(c,lambda x:sent.append(x) or b'\x90\0');self.assertEqual(sent,[c])

class ReaderTests(unittest.TestCase):
 def reader(self,replies):return Reader(FakeLink(replies),DEVICE)
 def test_identity(self):self.assertIn('W8298',self.reader([b'WATCH CRW-X W8298 2.7721 24017\x90\0']).identify())
 def test_wrong_identity_rejected(self):
  with self.assertRaises(ProtocolError):self.reader([b'WATCH W5181 2.8\x90\0']).identify()
 def test_contact_first(self):
  r=self.reader([CONTACT+b'\x90\0']);self.assertTrue(r.activate('auto','ContactFirst'));self.assertEqual(r.medium,'contact');self.assertEqual(r.link.sent,[(0x12,RESET)])
 def test_rf_first(self):
  r=self.reader([RF+b'\x90\0']);r.activate('auto','RfFirst');self.assertEqual(r.medium,'rf');self.assertEqual(r.link.sent,[(0x15,RF_TYPE_A)])
 def test_contact_absent_falls_back_rf(self):
  r=self.reader([b'\x62\0',RF+b'\x90\0']);self.assertTrue(r.activate('auto','ContactFirst'));self.assertEqual(r.medium,'rf')
 def test_rf_absent_falls_back_contact(self):
  r=self.reader([b'\x70\x13',CONTACT+b'\x90\0']);self.assertTrue(r.activate('auto','RfFirst'));self.assertEqual(r.medium,'contact')
 def test_fixed_contact_does_not_access_rf_or_sam(self):
  r=self.reader([b'\x62\0']);self.assertFalse(r.activate('contact','RfFirst'));self.assertEqual(r.link.sent,[(0x12,RESET)])
 def test_successful_fido_command_forwarded_without_serial_ban(self):
  r=self.reader([RF+b'\x90\0',b'\0\xa0\x90\0']);r.activate('rf','RfFirst');r.ready_at=0;c=bytes.fromhex('80100000010400');self.assertEqual(r.transmit(c),b'\0\xa0\x90\0');self.assertEqual(r.link.sent[-1],(0x15,c))
 def test_400ms_grace(self):
  r=self.reader([RF+b'\x90\0',b'\x90\0'])
  with patch('watchdata_usb.reader.time.monotonic',return_value=100):r.activate('rf','RfFirst')
  with patch('watchdata_usb.reader.time.monotonic',return_value=100.1),patch('watchdata_usb.reader.time.sleep') as wait:r.transmit(bytes.fromhex('00A4040000'));self.assertAlmostEqual(wait.call_args.args[0],.3)
 def test_rf_off_real_command(self):
  r=self.reader([RF+b'\x90\0',b'\x90\0']);r.activate('rf','RfFirst');r.power_off();self.assertFalse(r.powered);self.assertEqual(r.link.sent[-1],(0x15,RF_OFF))
 def test_contact_off_no_unknown_command(self):
  r=self.reader([CONTACT+b'\x90\0']);r.activate('contact','ContactFirst');r.power_off();self.assertEqual(len(r.link.sent),1)
 def test_failed_reset_clears_atr(self):
  r=self.reader([CONTACT+b'\x90\0',b'\x62\0']);r.activate('contact','ContactFirst')
  with self.assertRaises(CardLost):r.reset()
  self.assertEqual(r.atr,b'');self.assertFalse(r.powered)
 def test_card_loss_not_retried(self):
  r=self.reader([RF+b'\x90\0',b'\x6f\xf0']);r.activate('rf','RfFirst');r.ready_at=0
  with self.assertRaises(CardLost):r.transmit(bytes.fromhex('00DA000001AA'))
  self.assertEqual(len(r.link.sent),2)
 def test_unqualified_oversized_command_rejected(self):
  r=self.reader([RF+b'\x90\0']);r.activate('rf','RfFirst');c=bytes.fromhex('00DA00000003E8')+bytes(1000);self.assertEqual(r.transmit(c),b'\x67\0');self.assertEqual(len(r.link.sent),1)
 def test_beep_fires_only_when_called(self):
  r=self.reader([b'\x90\0',CONTACT+b'\x90\0',b'\x90\0']);r.beep();r.activate('contact','ContactFirst');r.beep();self.assertEqual(r.link.sent,[(0,BEEP),(0x12,RESET),(0,BEEP)])
 def test_beep_is_retried_after_transient_rejection(self):
  r=self.reader([b'\x6f\xf0',b'\x90\0']);self.assertFalse(r.beep());self.assertTrue(r.beep());self.assertEqual(r.link.sent,[(0,BEEP),(0,BEEP)])
 def test_health_only_queries_reader_and_retains_selection(self):
  r=self.reader([b'WATCH W8298 2.7\x90\0',CONTACT+b'\x90\0',b'WATCH W8298 2.7\x90\0']);r.identify();r.activate('contact','ContactFirst');r.health();self.assertTrue(r.powered);self.assertEqual(r.link.sent[-1],(0,VERSION))

@contextmanager
def pair():
 a,b=socket.socketpair()
 try:yield a,b
 finally:a.close();b.close()

class SessionTests(unittest.TestCase):
 def test_zero_frame(self):
  with pair() as(a,b):
   a.sendall(b'\0\0')
   with self.assertRaises(ProtocolError):receive(b)
 def test_partial_header_deadline(self):
  with pair() as(a,b):
   a.sendall(b'\0')
   with self.assertRaises(TimeoutError):receive(b,.02)
 def test_partial_body_eof(self):
  with pair() as(a,b):
   a.sendall(b'\0\5\0');a.shutdown(socket.SHUT_WR)
   with self.assertRaises(EOFError):receive(b)
 def test_coalesced_messages(self):
  with pair() as(a,b):a.sendall(b'\0\1\2\0\1\4');self.assertEqual(receive(b),b'\2');self.assertEqual(receive(b),b'\4')
 def test_response_roundtrip(self):
  with pair() as(a,b):send(a,b'A'*800+b'\x90\0');self.assertEqual(receive(b),b'A'*800+b'\x90\0')
 def test_off_atr_flow(self):
  r=Reader(FakeLink([CONTACT+b'\x90\0',CONTACT+b'\x90\0']),DEVICE);r.activate('contact','ContactFirst');s=Session(r);self.assertIsNone(s.handle(b'\0'));self.assertEqual(s.handle(b'\4'),CONTACT)
 def test_unknown_control(self):
  with self.assertRaises(ProtocolError):Session(Reader(FakeLink([]),DEVICE)).handle(b'\x7f')
 def test_device_selection_single(self):self.assertEqual(choose([DEVICE]),DEVICE)
 def test_multiple_device_requires_choice(self):
  b=Device('second',0x0A28,'W5181');self.assertEqual(choose([DEVICE,b],input_fn=lambda _:'2',output=lambda _:None),b)
 def test_device_token(self):self.assertEqual(choose([DEVICE],DEVICE.token),DEVICE)
 def test_selection_cancel(self):self.assertIsNone(choose([DEVICE,Device('second',0x0A28,'W5181')],input_fn=lambda _:'q',output=lambda _:None))

class CancellationTests(unittest.TestCase):
 def fake(self,wait):
  log=[]
  class K:
   def CreateEventW(self,*a):log.append('event');return 10
   def ReadFile(self,*a):log.append('read');return 0
   def WriteFile(self,*a):log.append('write');return 0
   def WaitForSingleObject(self,*a):log.append('wait');return wait
   def CancelIoEx(self,*a):log.append('cancel');return 1
   def GetOverlappedResult(self,h,ov,n,blocking):log.append('drain' if blocking else 'complete');n._obj.value=65;return 1
   def CloseHandle(self,*a):log.append('close');return 1
  class A:
   k=K()
   check=staticmethod(Api.check)
  t=HidTransport(DEVICE,A());t.handle=11;return t,log
 def test_overlapped_pointer_width(self):self.assertEqual(C.sizeof(Overlapped),32 if C.sizeof(C.c_void_p)==8 else 20)
 def test_timeout_cancels_and_drains_before_free(self):
  t,log=self.fake(258)
  with patch('ctypes.get_last_error',return_value=997),self.assertRaises(TimeoutError):t.read(time.monotonic()+.1)
  self.assertEqual(log,['event','read','wait','cancel','drain','close'])
 def test_success_completes_without_cancel(self):
  t,log=self.fake(0)
  with patch('ctypes.get_last_error',return_value=997):self.assertEqual(len(t.read(time.monotonic()+.1)),65)
  self.assertEqual(log,['event','read','wait','complete','close'])
 def test_wait_failure_also_drains(self):
  t,log=self.fake(0xFFFFFFFF)
  with patch('ctypes.get_last_error',return_value=997),self.assertRaises(OSError):t.read(time.monotonic()+.1)
  self.assertEqual(log[-3:],['cancel','drain','close'])

if __name__=='__main__':unittest.main(verbosity=2)
