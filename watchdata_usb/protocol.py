"""Validated Watchdata HID reports. No APDU interpretation or serial firmware quirks."""
import threading
import time

class ProtocolError(OSError):pass

# Qualified initially up to 16 reports. Increase only after on-device sequence-wrap testing.
MAX_COMMAND=61*16
MAX_RESPONSE=61*16

def encode(nad,payload):
    if nad not in (0,0x12,0x15):raise ValueError('Only reader/contact/RF endpoints are enabled; SAM excluded')
    if not 1<=len(payload)<=MAX_COMMAND:raise ValueError('Command exceeds qualified HID length')
    reports=[]
    for sequence,start in enumerate(range(0,len(payload),61)):
        part=payload[start:start+61]
        more=start+len(part)<len(payload)
        report=bytes([0,nad,sequence|(0x20 if more else 0),len(part)])+part
        reports.append(report.ljust(65,b'\0'))
    return reports

class Link:
    def __init__(self,transport,timeout=30,observer=None):
        self.transport=transport;self.timeout=timeout;self.poisoned=False;self.lock=threading.Lock();self.observer=observer

    def exchange(self,nad,command,timeout=None):
        reports=encode(nad,bytes(command))
        with self.lock:
            if self.poisoned:raise ProtocolError('HID session untrusted after transport/protocol failure; reopen required')
            deadline=time.monotonic()+(self.timeout if timeout is None else timeout)
            try:
                for r in reports:self.transport.write(r,deadline)
                output=bytearray();sequence=0
                while True:
                    if time.monotonic()>=deadline:raise TimeoutError('HID complete-message deadline')
                    r=self.transport.read(deadline)
                    if len(r)!=65 or r[0]!=0:raise ProtocolError('Invalid HID report size/ID')
                    expected=(nad>>4)|((nad&15)<<4)
                    if r[1]!=expected:raise ProtocolError('Wrong response NAD; refusing cross-slot data')
                    flags,count=r[2],r[3]
                    if flags&0xD0 or flags&0x0F!=sequence:raise ProtocolError('Unexpected HID sequence/flags')
                    if not 1<=count<=61:raise ProtocolError('Invalid HID fragment length')
                    if self.observer:self.observer(nad,flags,count)
                    output.extend(r[4:4+count])
                    if len(output)>MAX_RESPONSE:raise ProtocolError('Response exceeds qualified HID length')
                    if not flags&0x20:break
                    sequence+=1
                    if sequence>=16:raise ProtocolError('HID sequence wrap not qualified')
                if len(output)<2:raise ProtocolError('Response missing status word')
                return bytes(output)
            except (OSError,ValueError):
                self.poisoned=True
                raise
