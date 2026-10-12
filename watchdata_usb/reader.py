"""Watchdata USB contact/RF backend. SAM endpoints are never selected."""
import time
from .protocol import ProtocolError,MAX_COMMAND
from .card import contact_atr,rf_atr,parse_apdu,t0_transmit
from .app_compat import ApplicationReads, parse_command as compat_parse

RESET=bytes.fromhex('0012000000')
RF_TYPE_A=bytes.fromhex('B01200000101')
RF_OFF=bytes.fromhex('B0150E000100')
VERSION=bytes.fromhex('0019000000')
BEEP=bytes.fromhex('B0F20A0100')
ABSENT={b'\x62\0',b'\x62\1'}
RF_NOT_READY=ABSENT|{bytes.fromhex(x) for x in ['7013','7000','7500','6FF0']}

class CardLost(OSError):pass

class Reader:
    def __init__(self,link,device):
        self.link=link;self.device=device;self.medium=None;self.atr=b'';self.powered=False
        self.protocol=None;self.ready_at=0.;self.rf_on=False;self.firmware='';self.application_reads=ApplicationReads()

    def identify(self):
        r=self.link.exchange(0,VERSION,timeout=2)
        if r[-2:]!=b'\x90\0' or not r[:-2].startswith(b'WATCH '):raise ProtocolError('Selected HID is not a supported Watchdata reader')
        text=r[:-2].decode('ascii',errors='strict').strip('\0 ')
        expected='W8298' if self.device.pid==0x0A1F else 'W5181'
        if expected not in text:raise ProtocolError('Firmware identity does not match selected hardware profile')
        self.firmware=text;return text

    @property
    def nad(self):
        if self.medium=='contact':return 0x12
        if self.medium=='rf':return 0x15
        raise CardLost('No active card')

    def beep(self):
        # Try the physical buzzer every time. A transient failure at reader startup
        # must not suppress the detection beep later.
        r=self.link.exchange(0,BEEP,timeout=2)
        return r[-2:]==b'\x90\0' 

    def _activate(self,medium):
        nad=0x12 if medium=='contact' else 0x15
        # The local README defines a Type-A-only activation. On W8298 it recovers
        # detection when the combined 0012 search returns 7013 with a card present.
        cmd=RESET if medium=='contact' else RF_TYPE_A
        r=self.link.exchange(nad,cmd,timeout=3)
        if medium=='rf':self.rf_on=True
        sw=r[-2:]
        if sw in (ABSENT if medium=='contact' else RF_NOT_READY):return False
        if sw!=b'\x90\0':raise ProtocolError(f'{medium} activation failed: SW={sw.hex().upper()}')
        if medium=='contact':atr,protocol=contact_atr(r[:-2])
        else:atr,protocol=rf_atr(r[:-2]),1
        self.atr,self.medium,self.protocol,self.powered=atr,medium,protocol,True
        self.application_reads.reset()
        self.ready_at=time.monotonic()+(.4 if medium=='rf' else 0)
        return True

    def activate(self,mode,priority):
        self.atr=b'';self.medium=None;self.powered=False
        modes=('contact','rf') if priority=='ContactFirst' else ('rf','contact')
        if mode!='auto':modes=(mode,)
        for medium in modes:
            if self._activate(medium):return True
        return False

    def reset(self):
        medium=self.medium;self.atr=b'';self.powered=False;self.application_reads.reset()
        if medium is None or not self._activate(medium):raise CardLost('Card absent during reset')

    def power_off(self):
        self.atr=b'';self.powered=False;self.application_reads.reset()
        # The local docs specify RF power down only. Do not invent a contact OFF
        # command or reset an active card from an idle presence loop.
        if self.medium=='rf' or self.rf_on:
            r=self.link.exchange(0x15,RF_OFF,timeout=2)
            self.rf_on=False
            if r[-2:]!=b'\x90\0':raise ProtocolError('RF power-off rejected: '+r[-2:].hex())

    def _raw(self,command):
        r=self.link.exchange(self.nad,command)
        if r[-2:] in ABSENT|{b'\x6f\xf0'}:
            self.atr=b'';self.powered=False;raise CardLost('Card communication lost; command not replayed')
        return r

    def transmit(self,command):
        if not self.powered:raise CardLost('APDU while powered off')
        parsed=compat_parse(command)
        if parsed is None or len(command)>MAX_COMMAND:return b'\x67\0'
        delay=self.ready_at-time.monotonic()
        if delay>0:time.sleep(delay)
        if self.medium=='contact' and parsed.extended:
            try:response=self.application_reads.extended_read(parsed,self._raw)
            except OSError:self.application_reads.reset();raise
            self.application_reads.observe(parsed,response);return response
        if self.medium=='contact' and self.protocol==0:response=t0_transmit(command,self._raw)
        else:response=self._raw(command)
        self.application_reads.observe(parsed,response);return response

    def health(self):
        r=self.link.exchange(0,VERSION,timeout=2)
        if r[-2:]!=b'\x90\0' or r[:-2].decode('ascii',errors='replace').strip('\0 ')!=self.firmware:raise ProtocolError('Reader disconnected or identity changed')
