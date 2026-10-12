"""No hardware access; tests focus on read-only adaptation and application isolation."""
import unittest
from app_compat import ApplicationReads, ReadMappingError, parse_command
from serial_reader import SerialCard, Profile
from check_apps import inspect

ATRDATA=bytes.fromhex('0048880494968E24CA7B18903920137877710280318066B0840C016E0183009000')
PGP=bytes.fromhex('00A4040006D2760001240100')
PIV=bytes.fromhex('00A4040009A0000003080000100000')

class Link:
 def __init__(self,replies):self.replies=list(replies);self.calls=[]
 def exchange(self,nad,c,timeout=None):
  self.calls.append(bytes(c));result=self.replies.pop(0)
  if isinstance(result,Exception):raise result
  return result

class MappingTests(unittest.TestCase):
 def card(self,select,replies):
  link=Link([ATRDATA+b'\x90\0',b'\x90\0']+replies)
  c=SerialCard(link,Profile('WATCH crw-x 1.8605 05003',0x12),cold_grace=0);c.activate();c.transmit(select);return c,link
 def test_parse_short_and_extended_case2(self):
  for raw,le,ext in [('00CA004F00',256,False),('00CA004F000400',1024,True),('00CA004F000000',65536,True)]:
   c=parse_command(bytes.fromhex(raw));self.assertEqual((c.le,c.extended),(le,ext));self.assertEqual(c.data,b'')
 def test_parse_case4_extended(self):
  c=parse_command(bytes.fromhex('00CB3FFF0000055C035FC1070400'));self.assertEqual(c.data,bytes.fromhex('5C035FC107'));self.assertEqual(c.le,1024)
 def test_bad_extended_length(self):
  for raw in ['00CA000000FF','00DA000000000001','00DA0000000002AA']:
   self.assertIsNone(parse_command(bytes.fromhex(raw)))
 def test_pgp_extended_get_data_uses_short_wire(self):
  c,l=self.card(PGP,[b'abc\x90\0']);self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'abc\x90\0');self.assertEqual(l.calls[-1],bytes.fromhex('00CA004F00'))
 def test_piv_extended_get_data_exact_input(self):
  result=bytes.fromhex('5303AABBCC9000');c,l=self.card(PIV,[result]);self.assertEqual(c.transmit(bytes.fromhex('00CB3FFF0000055C035FC1070400')),result)
  self.assertEqual(l.calls[-1],bytes.fromhex('00CB3FFF055C035FC10700'))
 def test_extended_read_61_response_reassembled(self):
  obj=bytes.fromhex('6E82012C')+b'A'*300
  c,l=self.card(PGP,[obj[:256]+b'\x61\x30',obj[256:]+b'\x90\0'])
  self.assertEqual(c.transmit(bytes.fromhex('00CA006E000400')),obj+b'\x90\0');self.assertEqual(l.calls[-1],bytes.fromhex('00C0000030'))
 def test_61_zero_requests_256_not_zero_bytes(self):
  c,l=self.card(PGP,[b'\x61\0',b'A'*256+b'\x61\x01',b'B\x90\0'])
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'A'*256+b'B\x90\0');self.assertEqual(l.calls[-2],bytes.fromhex('00C0000000'))
 def test_original_le_caps_mapping_and_retains_61(self):
  c,l=self.card(PGP,[b'AA\x61\x10',b'BB\x61\x0e']);self.assertEqual(c.transmit(bytes.fromhex('00CA004F000004')),b'AABB\x61\x0e');self.assertEqual(l.calls[-1],bytes.fromhex('00C0000002'))
 def test_6c_correction_only_for_explicit_read_le(self):
  c,l=self.card(PGP,[b'\x6c\x03',b'ABC\x90\0']);self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'ABC\x90\0');self.assertEqual(l.calls[-1],bytes.fromhex('00CA004F03'))
 def test_no_expansion_after_6c_beyond_original_le(self):
  c,l=self.card(PGP,[b'\x6c\x20']);self.assertEqual(c.transmit(bytes.fromhex('00CA004F000004')),b'\x6c\x20');self.assertEqual(len(l.calls),3)
 def test_unknown_selected_applet_not_adapted(self):
  c,l=self.card(bytes.fromhex('00A4040005F000000001'),[]);self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'\x67\0');self.assertEqual(len(l.calls),2)
 def test_before_select_not_adapted(self):
  l=Link([ATRDATA+b'\x90\0']);c=SerialCard(l,Profile('WATCH crw-x 1.8605',0x12),cold_grace=0);c.activate()
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'\x67\0');self.assertEqual(len(l.calls),1)
 def test_failed_select_clears_previous_assumption(self):
  c,l=self.card(PGP,[b'\x6a\x82']);self.assertEqual(c.transmit(bytes.fromhex('00A4040008A0000006472F000100')),b'\x6a\x82')
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'\x67\0');self.assertEqual(len(l.calls),3)
 def test_off_and_reset_clear_selection(self):
  c,l=self.card(PGP,[ATRDATA+b'\x90\0']);c.power_off();c.reset();self.assertIsNone(c.application_reads.selected)
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'\x67\0')
 def test_successful_extended_pgp_select_tracks_app(self):
  l=Link([ATRDATA+b'\x90\0',b'\x90\0',b'abc\x90\0']);c=SerialCard(l,Profile('WATCH crw-x 1.8605',0x12),cold_grace=0);c.activate()
  self.assertEqual(c.transmit(bytes.fromhex('00A40400000006D276000124010400')),b'\x90\0');self.assertEqual(l.calls[-1],PGP)
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'abc\x90\0')
 def test_partial_fci_61_means_successful_selection(self):
  c,l=self.card(PGP,[b'\x61\x01',b'abc\x90\0']);self.assertEqual(c.transmit(PGP),b'\x61\x01');self.assertEqual(c.application_reads.selected,'openpgp')
  self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'abc\x90\0')
 def test_piv_to_pgp_has_separate_policies(self):
  c,l=self.card(PIV,[b'\x90\0']);self.assertEqual(c.transmit(bytes.fromhex('00CA004F000400')),b'\x67\0');c.transmit(PGP)
  self.assertEqual(c.transmit(bytes.fromhex('00CB3FFF0000055C035FC1070400')),b'\x67\0')
 def test_long_write_not_automatically_split(self):
  c,l=self.card(PGP,[]);cmd=bytes.fromhex('00DB3FFF00012C')+b'A'*300
  self.assertEqual(c.transmit(cmd),b'\x67\0');self.assertEqual(len(l.calls),2)
 def test_key_generation_not_mapped(self):
  c,l=self.card(PGP,[]);self.assertEqual(c.transmit(bytes.fromhex('00478000000002B6000400')),b'\x67\0');self.assertEqual(len(l.calls),2)
 def test_public_key_read_can_be_mapped(self):
  result=bytes.fromhex('7F4904810201029000');c,l=self.card(PGP,[result,result]);self.assertEqual(c.transmit(bytes.fromhex('00478100000002B6000400')),result)
  self.assertEqual(l.calls[-1],bytes.fromhex('0047810002B60000'))
  self.assertEqual(c.transmit(bytes.fromhex('00478100000001B60400')),result)
  self.assertEqual(l.calls[-1],bytes.fromhex('0047810001B600'))
 def test_pin_and_secure_messages_not_rewritten(self):
  c,l=self.card(PGP,[])
  for cmd in ['00200081000004313233340010','04CA004F000400','84CA004F000400','01CA004F000400','10CA004F000400']:
   self.assertEqual(c.transmit(bytes.fromhex(cmd)),b'\x67\0')
  self.assertEqual(len(l.calls),2)
 def test_short_chained_and_signed_commands_still_exact(self):
  c,l=self.card(PGP,[b'\x90\0',b'\x90\0'])
  for command in ['10DB3FFF03010203','84DA000003AABBCC']:
   cmd=bytes.fromhex(command);c.transmit(cmd);self.assertEqual(l.calls[-1],cmd)
 def test_short_61_remains_transparent(self):
  c,l=self.card(PGP,[b'A\x61\x02']);self.assertEqual(c.transmit(bytes.fromhex('00CA006E00')),b'A\x61\x02');self.assertEqual(len(l.calls),3)
 def test_fido_empty_success_is_not_invented(self):
  c,l=self.card(bytes.fromhex('00A4040008A0000006472F000100'),[]);self.assertEqual(c.transmit(bytes.fromhex('80100000010400')),b'\x6d\0');self.assertEqual(len(l.calls),2)
 def test_unknown_piv_getdata_template_rejected(self):
  c,l=self.card(PIV,[]);self.assertEqual(c.transmit(bytes.fromhex('00CB3FFF0000057C035FC1070400')),b'\x67\0');self.assertEqual(len(l.calls),2)
 def test_mid_response_loss_not_replayed(self):
  c,l=self.card(PGP,[b'AA\x61\x01',TimeoutError('injected loss')])
  with self.assertRaises(TimeoutError):c.transmit(bytes.fromhex('00CA004F000400'))
  self.assertEqual(len(l.calls),4);self.assertIsNone(c.application_reads.selected)
 def test_wrong_object_length_cannot_be_success(self):
  c,l=self.card(PIV,[bytes.fromhex('53820100AABB9000')])
  with self.assertRaises(ReadMappingError):c.transmit(bytes.fromhex('00CB3FFF0000055C035FC1050400'))
  self.assertIsNone(c.application_reads.selected)
 def test_cardholder_value_may_contain_inner_tlvs_without_outer_65(self):
  r=bytes.fromhex('5B034142435F2D02656E9000');c,l=self.card(PGP,[r])
  self.assertEqual(c.transmit(bytes.fromhex('00CA0065000400')),r)
 def test_piv_empty_success_is_not_a_certificate(self):
  c,l=self.card(PIV,[b'\x90\0'])
  with self.assertRaises(ReadMappingError):c.transmit(bytes.fromhex('00CB3FFF0000055C035FC1050400'))
 def test_empty_openpgp_certificate_remains_legitimate(self):
  c,l=self.card(PGP,[b'\x90\0']);self.assertEqual(c.transmit(bytes.fromhex('00CA7F21000400')),b'\x90\0')
 def test_invalid_ber_length_rejected(self):
  for response in ['538000009000','5384FFFFFFFF9000','5302AA9000']:
   c,l=self.card(PIV,[bytes.fromhex(response)])
   with self.assertRaises(ReadMappingError):c.transmit(bytes.fromhex('00CB3FFF0000055C035FC1050400'))
 def test_response_exceeding_le_rejected(self):
  c,l=self.card(PGP,[b'ABC\x90\0'])
  with self.assertRaises(ReadMappingError):c.transmit(bytes.fromhex('00CA004F000002'))
 def test_zero_progress_bounded(self):
  c,l=self.card(PGP,[b'\x61\x01',b'\x61\x01'])
  with self.assertRaises(ReadMappingError):c.transmit(bytes.fromhex('00CA004F000400'))
  self.assertEqual(len(l.calls),4)
 def test_same_card_status_errors_pass_through(self):
  c,l=self.card(PIV,[b'\x6a\x82']);self.assertEqual(c.transmit(bytes.fromhex('00CB3FFF0000055C035FC1050400')),b'\x6a\x82')

class DiagnosticTests(unittest.TestCase):
 def test_tool_never_issues_pin_auth_keygen_or_private_operations(self):
  class Card:
   profile=Profile('WATCH crw-x 1.8605 05003',0x12)
   def __init__(self):self.sent=[]
   def transmit(self,c):
    self.sent.append(c)
    if c[1]==0xA4 and bytes.fromhex('A0000006472F0001') in c:return b'\x6a\x82'
    if c[1] in (0xCB,0x47):return b'\x6a\x88'
    return b'\x90\0'
  card=Card();r=inspect(card)
  self.assertEqual(r['applications']['fido']['state'],'not_selectable')
  for c in card.sent:
   self.assertIn(c[1],(0xA4,0xCA,0xCB,0x47))
   if c[1]==0x47:self.assertEqual(c[2],0x81)
   self.assertNotEqual(c[:2],b'\x80\x10')
  self.assertFalse(r['crypto_operations_tested'])
 def test_absent_certificate_distinct_from_transport_failure(self):
  class Card:
   profile=Profile('WATCH crw-x 1.8605 05003',0x12)
   def transmit(self,c):return b'\x90\0' if c[1]==0xA4 else b'\x6a\x82'
  r=inspect(Card());self.assertEqual(r['applications']['piv']['read_objects']['authentication_certificate']['state'],'not_present')

if __name__=='__main__':unittest.main(verbosity=2)
