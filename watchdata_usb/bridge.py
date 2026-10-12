"""Watchdata USB -> one Windows VPCD slot, with explicit contact/RF priority."""
import argparse
import ipaddress
import select
import socket
import struct
import time
from .transport import enumerate_devices,HidTransport
from .protocol import Link,ProtocolError,MAX_COMMAND
from .reader import Reader,CardLost


def choose(devices,selector=None,input_fn=input,output=print):
    if selector:
        matches=[d for d in devices if selector.lower() in (d.token.lower(),d.path.lower())]
        if selector.isdecimal() and 1<=int(selector)<=len(devices):matches=[devices[int(selector)-1]]
        if len(matches)!=1:raise ValueError('Device selection must match exactly one listed index or device ID')
        return matches[0]
    if not devices:return None
    if len(devices)==1:return devices[0]
    for i,d in enumerate(devices,1):output(f'{i}. {d.product} PID={d.pid:04X} device={d.token}')
    while True:
        try:value=input_fn('Select reader number (Q cancels): ').strip()
        except EOFError as ex:raise ValueError('Multiple readers: use -Device ID/index in noninteractive mode') from ex
        if value.lower()=='q':return None
        if value.isdecimal() and 1<=int(value)<=len(devices):return devices[int(value)-1]
        output('Invalid selection.')


def receive(sock,timeout=3):
    deadline=time.monotonic()+timeout
    def exact(n):
        data=bytearray()
        while len(data)<n:
            left=deadline-time.monotonic()
            if left<=0:raise TimeoutError('VPCD partial-frame deadline')
            sock.settimeout(left);p=sock.recv(n-len(data))
            if not p:raise EOFError('VPCD closed by peer')
            data.extend(p)
        return bytes(data)
    try:
        size=int.from_bytes(exact(2),'big')
        if not size:raise ProtocolError('Empty VPCD frame')
        return exact(size)
    finally:sock.settimeout(None)


def send(sock,data):
    if not 1<=len(data)<=65535:raise ProtocolError('VPCD output length')
    sock.settimeout(3)
    try:sock.sendall(struct.pack('!H',len(data))+data)
    finally:sock.settimeout(None)


class Session:
    def __init__(self,reader):self.reader=reader;self.frames=0;self.last='none'
    def handle(self,p):
        self.frames+=1;self.last=f'CTRL({p[0]})' if len(p)==1 else f'APDU(len={len(p)})'
        if len(p)==1:
            if p[0]==0:self.reader.power_off();return None
            if p[0] in (1,2):self.reader.reset();return None
            if p[0]==4:
                if not self.reader.powered:self.reader.reset()
                return self.reader.atr
            raise ProtocolError('Unknown VPCD control')
        return self.reader.transmit(p)
    def run(self,sock,stop):
        last_business=time.monotonic();last_health=last_business
        while not stop():
            readable,_,_=select.select([sock],[],[],.02)
            if readable:
                p=receive(sock);r=self.handle(p)
                if r is not None:send(sock,r)
                if p!=b'\4':last_business=time.monotonic()
            elif time.monotonic()-max(last_business,last_health)>=5:
                self.reader.health();last_health=time.monotonic()


def loopback(s):
    if s.lower()=='localhost':return '127.0.0.1'
    try:a=ipaddress.ip_address(s)
    except ValueError as ex:raise argparse.ArgumentTypeError('Invalid loopback address') from ex
    if not a.is_loopback:raise argparse.ArgumentTypeError('VPCD must be local')
    return str(a)


def run(args):
    devices=enumerate_devices()
    if args.list_devices:
        for i,d in enumerate(devices,1):print(f'{i}. {d.product} VID=163C PID={d.pid:04X} device={d.token}')
        if not devices:print('No supported Watchdata smart-card HID interface found.')
        return 0
    selected=choose(devices,args.device)
    if selected is None:
        if devices:print('Cancelled.');return 0
        raise OSError('No supported Watchdata reader found (W8298 0A1F / W5181 Plus 0A28)')
    started=time.monotonic();stop=lambda:args.run_seconds>0 and time.monotonic()-started>=args.run_seconds
    print(f'Watchdata USB: {selected.product}; device={selected.token}; mode={args.mode}; priority={args.priority}',flush=True)
    print('Single virtual slot. USB/native FIDO APDUs; RF 400ms startup grace. No APDU payload logging.',flush=True)
    print('Reader health is monitored; safe idle card-presence query is not qualified. Card loss is reported on APDU/reset.',flush=True)
    connected_before=False;last_error=None
    while not stop():
        transport=HidTransport(selected);reader=None;sock=None
        try:
            transport.open();reader=Reader(Link(transport,args.apdu_timeout),selected)
            firmware=reader.identify();print('Reader connected: '+firmware,flush=True)
            if not connected_before:
                if reader.beep(): print('Reader buzzer: reader connected.',flush=True)
                else: print('Reader buzzer command rejected at reader connection.',flush=True)
                connected_before=True
            while not stop() and not reader.activate(args.mode,args.priority):time.sleep(.4)
            if stop():break
            if reader.beep(): print('Reader buzzer: card detected.',flush=True)
            else: print('Reader buzzer command rejected for card detection.',flush=True)
            print(f'Card detected: {reader.medium}; ATR={reader.atr.hex().upper()}',flush=True)
            warned=False
            while not stop():
                try:sock=socket.create_connection((args.host,args.vpcd_port),timeout=2);break
                except OSError as ex:
                    if not warned:print(f'Waiting for VPCD: {ex}',flush=True);warned=True
                    time.sleep(.5)
            if stop():break
            sock.settimeout(None);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            print('Connected to VPCD.',flush=True)
            session=Session(reader)
            try:session.run(sock,stop)
            except (OSError,EOFError,ValueError) as ex:
                print(f'Session ended: {ex}; medium={reader.medium}; last={session.last}; frames={session.frames}',flush=True)
                raise
        except (OSError,EOFError,ValueError) as ex:
            if not connected_before:raise
            message=f'{type(ex).__name__}: {ex}'
            if message!=last_error:print('Reconnecting selected reader: '+message,flush=True);last_error=message
            if not stop():time.sleep(.5)
        finally:
            if sock is not None:sock.close()
            # Do not send any further request into a broken HID message stream.
            if reader is not None and not reader.link.poisoned:
                try:reader.power_off()
                except OSError:pass
            transport.close()
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['auto','contact','rf'],default='auto')
    p.add_argument('--priority',choices=['ContactFirst','RfFirst'],default='ContactFirst')
    p.add_argument('--device',help='Listed index or stable device ID; multiple devices require selection')
    p.add_argument('--list-devices',action='store_true')
    p.add_argument('--host',type=loopback,default='127.0.0.1')
    p.add_argument('--vpcd-port',type=int,default=35963)
    p.add_argument('--run-seconds',type=float,default=0)
    p.add_argument('--apdu-timeout',type=float,default=30)
    a=p.parse_args(argv)
    if not 1<=a.vpcd_port<=65535 or not 0<a.apdu_timeout<=300 or a.run_seconds<0:p.error('Invalid port/time limit')
    try:return run(a)
    except KeyboardInterrupt:print('\nStopped; device released.');return 0
    except (OSError,ValueError) as ex:print(str(ex));return 1

if __name__=='__main__':raise SystemExit(main())
