"""Application-neutral APDU parsing and ATR handling. No serial-only workarounds."""
from dataclasses import dataclass
from .protocol import ProtocolError,MAX_COMMAND

@dataclass(frozen=True)
class Command:
    raw: bytes
    data: bytes
    le: int|None
    extended: bool


def parse_apdu(c):
    c=bytes(c)
    if not 4<=len(c)<=65535:return None
    if len(c)==4:return Command(c,b'',None,False)
    if len(c)==5:return Command(c,b'',c[4] or 256,False)
    if c[4]:
        n=c[4]
        if len(c) not in (5+n,6+n):return None
        return Command(c,c[5:5+n],(c[-1] or 256) if len(c)==6+n else None,False)
    if len(c)<7:return None
    n=int.from_bytes(c[5:7],'big')
    if len(c)==7:return Command(c,b'',n or 65536,True)
    if not n or len(c) not in (7+n,9+n):return None
    return Command(c,c[7:7+n],(int.from_bytes(c[-2:],'big') or 65536) if len(c)==9+n else None,True)


def xor(data):
    value=0
    for x in data:value^=x
    return value


def contact_atr(raw):
    if not 2<=len(raw)<=33 or raw[0] not in (0x3B,0x3F):raise ProtocolError('Invalid contact ATR')
    offset=2;mask=raw[1]>>4;protocols=[];group=1;specific=None
    while mask:
        for bit in (1,2,4):
            if mask&bit:
                if offset>=len(raw):raise ProtocolError('Truncated contact interface bytes')
                if group==2 and bit==1:specific=raw[offset]&15
                offset+=1
        if not mask&8:break
        if offset>=len(raw):raise ProtocolError('Missing contact TD')
        td=raw[offset];offset+=1;protocols.append(td&15);mask=td>>4;group+=1
    tck=any(t!=0 for t in protocols)
    if len(raw)!=offset+(raw[1]&15)+int(tck) or (tck and xor(raw[1:])):raise ProtocolError('Contact ATR length/checksum mismatch')
    chosen=specific if specific is not None else next((t for t in protocols if t!=15),0)
    if chosen not in (0,1):raise ProtocolError('Unsupported contact protocol')
    return bytes(raw),chosen


def ats_atr(ats):
    if not ats or ats[0]!=len(ats) or len(ats)>20:raise ProtocolError('Invalid ATS length')
    offset=1
    if len(ats)>1:
        t0=ats[1];offset=2
        if t0&0x80 or t0&15>8:raise ProtocolError('Invalid ATS FSCI')
        for bit in (0x10,0x20,0x40):
            if t0&bit:
                if offset>=len(ats):raise ProtocolError('Truncated ATS')
                offset+=1
    history=ats[offset:]
    if len(history)>15:raise ProtocolError('Too many historical bytes')
    atr=bytes([0x3B,0x80|len(history),0x80,1])+history
    return atr+bytes([xor(atr[1:])])


def rf_atr(raw):
    candidates=[]
    for i in range(3,len(raw)):
        if not raw[i-1]&0x20 or raw[i]!=len(raw)-i:continue
        try:candidates.append(ats_atr(raw[i:]))
        except ProtocolError:continue
    if len(candidates)!=1:raise ProtocolError('RF reset does not contain one valid Type A ISO-DEP ATS')
    return candidates[0]


def protected(cla):
    if cla&0x80:return bool(cla&0x0C)
    return bool(cla & (0x20 if cla&0x40 else 0x0C))


def t0_transmit(command,exchange):
    parsed=parse_apdu(command)
    if parsed is None or len(command)>MAX_COMMAND:return b'\x67\0'
    # Extended T=0 mapping is not provided by this bridge. Let the reader/card
    # receive the valid form unchanged, instead of truncating or inventing chaining.
    if parsed.extended:return exchange(command)
    c=command
    if len(c)==4:c+=b'\0'
    elif parsed.data and parsed.le is not None:c=c[:-1]
    r=exchange(c)
    automatic=not protected(command[0])
    if automatic and len(command)==5 and len(r)==2 and r[0]==0x6C:
        r=exchange(c[:-1]+r[-1:])
    # Retain the existing reader bridge's T=0 continuation convention. Never issue
    # GET RESPONSE with a different channel or outside the current serialized command.
    if not automatic:return r
    result=bytearray()
    for n in range(65):
        if len(r)<2:raise ProtocolError('Short T=0 response')
        result.extend(r[:-2]);sw=r[-2:]
        if len(result)>65533:raise ProtocolError('T=0 response too long')
        if sw[0]!=0x61 or n==64:return bytes(result)+sw
        if n and len(r)==2:raise ProtocolError('GET RESPONSE made no progress')
        cla=(command[0]&3) if command[0]&0x80 else command[0]&0xEF
        r=exchange(bytes([cla,0xC0,0,0,sw[1]]))
    raise AssertionError('unreachable')
