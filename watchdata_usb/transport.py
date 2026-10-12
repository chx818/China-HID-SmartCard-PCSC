"""Native Windows HID transport. Metadata filtering precedes any smart-card command."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import hashlib
import math
import os
import time

SUPPORTED_PIDS = {0x0A1F: 'W8298 / W2160 USB', 0x0A28: 'W5181 Plus'}
INVALID_HANDLE = C.c_void_p(-1).value

class HidError(OSError):
    pass

class GUID(C.Structure):
    _fields_ = [('Data1', W.DWORD), ('Data2', W.WORD), ('Data3', W.WORD), ('Data4', W.BYTE * 8)]

class InterfaceData(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('guid', GUID), ('flags', W.DWORD), ('reserved', C.c_size_t)]

class Attributes(C.Structure):
    _fields_ = [('Size', W.DWORD), ('VendorID', W.WORD), ('ProductID', W.WORD), ('VersionNumber', W.WORD)]

class Caps(C.Structure):
    _fields_ = [('Usage', W.WORD), ('UsagePage', W.WORD), ('InputReportByteLength', W.WORD),
                ('OutputReportByteLength', W.WORD), ('FeatureReportByteLength', W.WORD),
                ('Reserved', W.WORD * 17)] + [(n,W.WORD) for n in (
                    'NumberLinkCollectionNodes','NumberInputButtonCaps','NumberInputValueCaps','NumberInputDataIndices',
                    'NumberOutputButtonCaps','NumberOutputValueCaps','NumberOutputDataIndices',
                    'NumberFeatureButtonCaps','NumberFeatureValueCaps','NumberFeatureDataIndices')]

class Overlapped(C.Structure):
    _fields_ = [('Internal', C.c_size_t), ('InternalHigh', C.c_size_t), ('Offset', W.DWORD),
                ('OffsetHigh', W.DWORD), ('hEvent', W.HANDLE)]

@dataclass(frozen=True)
class Device:
    path: str
    pid: int
    product: str
    usage_page: int = 0xFFA0
    usage: int = 1
    input_size: int = 65
    output_size: int = 65

    @property
    def token(self):
        return hashlib.sha256(self.path.lower().encode('utf-8')).hexdigest()[:16]


def _bind(dll,name,args,result):
    f=getattr(dll,name);f.argtypes=args;f.restype=result;return f

class Api:
    def __init__(self):
        if os.name != 'nt':
            raise HidError('Watchdata USB bridge requires Windows')
        self.k=C.WinDLL('kernel32',use_last_error=True)
        self.h=C.WinDLL('hid',use_last_error=True)
        self.s=C.WinDLL('setupapi',use_last_error=True)
        P=C.POINTER
        for name,args,res in [
            ('CreateFileW',[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE],W.HANDLE),
            ('CloseHandle',[W.HANDLE],W.BOOL),('CreateEventW',[C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR],W.HANDLE),
            ('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD),
            ('CancelIoEx',[W.HANDLE,P(Overlapped)],W.BOOL),
            ('GetOverlappedResult',[W.HANDLE,P(Overlapped),P(W.DWORD),W.BOOL],W.BOOL),
            ('ReadFile',[W.HANDLE,C.c_void_p,W.DWORD,P(W.DWORD),P(Overlapped)],W.BOOL),
            ('WriteFile',[W.HANDLE,C.c_void_p,W.DWORD,P(W.DWORD),P(Overlapped)],W.BOOL),
            ('CreateMutexW',[C.c_void_p,W.BOOL,W.LPCWSTR],W.HANDLE),('ReleaseMutex',[W.HANDLE],W.BOOL)]:
            _bind(self.k,name,args,res)
        for name,args,res in [
            ('HidD_GetHidGuid',[P(GUID)],None),('HidD_GetAttributes',[W.HANDLE,P(Attributes)],W.BOOLEAN),
            ('HidD_GetPreparsedData',[W.HANDLE,P(C.c_void_p)],W.BOOLEAN),('HidD_FreePreparsedData',[C.c_void_p],W.BOOLEAN),
            ('HidP_GetCaps',[C.c_void_p,P(Caps)],W.LONG),
            ('HidD_GetProductString',[W.HANDLE,C.c_void_p,W.ULONG],W.BOOLEAN)]:
            _bind(self.h,name,args,res)
        for name,args,res in [
            ('SetupDiGetClassDevsW',[P(GUID),W.LPCWSTR,W.HWND,W.DWORD],W.HANDLE),
            ('SetupDiEnumDeviceInterfaces',[W.HANDLE,C.c_void_p,P(GUID),W.DWORD,P(InterfaceData)],W.BOOL),
            ('SetupDiGetDeviceInterfaceDetailW',[W.HANDLE,P(InterfaceData),C.c_void_p,W.DWORD,P(W.DWORD),C.c_void_p],W.BOOL),
            ('SetupDiDestroyDeviceInfoList',[W.HANDLE],W.BOOL)]:
            _bind(self.s,name,args,res)

    @staticmethod
    def check(result, operation):
        if not result:
            n=C.get_last_error();raise HidError(n,f'{operation}: Win32 {n}')


def enumerate_devices(api=None):
    api=api or Api();guid=GUID();api.h.HidD_GetHidGuid(C.byref(guid))
    devs=api.s.SetupDiGetClassDevsW(C.byref(guid),None,None,0x12)
    if devs == INVALID_HANDLE:api.check(False,'HID enumeration')
    found=[]
    try:
        index=0
        while True:
            item=InterfaceData();item.cbSize=C.sizeof(item)
            if not api.s.SetupDiEnumDeviceInterfaces(devs,None,C.byref(guid),index,C.byref(item)):
                if C.get_last_error()==259:break
                api.check(False,'HID interface enumeration')
            index+=1;size=W.DWORD()
            api.s.SetupDiGetDeviceInterfaceDetailW(devs,C.byref(item),None,0,C.byref(size),None)
            if size.value<6 or size.value>65536:raise HidError('Invalid HID interface path size')
            detail=C.create_string_buffer(size.value)
            C.cast(detail,C.POINTER(W.DWORD))[0]=8 if C.sizeof(C.c_void_p)==8 else 6
            api.check(api.s.SetupDiGetDeviceInterfaceDetailW(devs,C.byref(item),detail,size.value,C.byref(size),None),'HID interface path')
            path=C.wstring_at(C.addressof(detail)+4)
            # Cheap path prefilter, then authoritative attributes/caps. Never open a keyboard for I/O.
            if 'vid_163c' not in path.lower():continue
            handle=api.k.CreateFileW(path,0,3,None,3,0,None)
            if handle==INVALID_HANDLE:continue
            try:
                a=Attributes();a.Size=C.sizeof(a)
                if not api.h.HidD_GetAttributes(handle,C.byref(a)) or a.VendorID!=0x163C or a.ProductID not in SUPPORTED_PIDS:continue
                pp=C.c_void_p()
                if not api.h.HidD_GetPreparsedData(handle,C.byref(pp)):continue
                try:
                    caps=Caps();status=api.h.HidP_GetCaps(pp,C.byref(caps))
                finally:api.h.HidD_FreePreparsedData(pp)
                if status!=0x00110000:continue
                if (caps.UsagePage,caps.Usage,caps.InputReportByteLength,caps.OutputReportByteLength)!=(0xFFA0,1,65,65):continue
                product=C.create_unicode_buffer(256)
                api.h.HidD_GetProductString(handle,product,C.sizeof(product))
                found.append(Device(path,a.ProductID,product.value or SUPPORTED_PIDS[a.ProductID]))
            finally:api.k.CloseHandle(handle)
    finally:api.s.SetupDiDestroyDeviceInfoList(devs)
    return sorted(found,key=lambda x:(x.pid,x.path.lower()))

class HidTransport:
    def __init__(self,device,api=None):
        self.device=device;self.api=api or Api();self.handle=None;self.mutex=None;self.owned=False

    def open(self):
        if self.handle is not None:raise HidError('HID already open')
        k=self.api.k
        self.mutex=k.CreateMutexW(None,False,'Global\\WatchdataUSB.'+self.device.token)
        if not self.mutex:self.api.check(False,'Create reader mutex')
        state=k.WaitForSingleObject(self.mutex,0)
        if state not in (0,0x80):
            k.CloseHandle(self.mutex);self.mutex=None
            raise HidError('Another Watchdata bridge owns the selected reader')
        self.owned=True
        self.handle=k.CreateFileW(self.device.path,0xC0000000,0,None,3,0x40000000,None)
        if self.handle==INVALID_HANDLE:
            self.handle=None
            try:self.api.check(False,'Open selected HID (may be busy/unplugged)')
            finally:self.close()
        return self

    def _io(self,data,reading,deadline):
        if self.handle is None:raise HidError('HID closed')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('HID exchange deadline')
        k=self.api.k;overlap=Overlapped();overlap.hEvent=k.CreateEventW(None,True,False,None)
        if not overlap.hEvent:self.api.check(False,'Create I/O event')
        buf=C.create_string_buffer(65) if reading else C.create_string_buffer(data,65)
        n=W.DWORD();pending=False
        try:
            ok=(k.ReadFile if reading else k.WriteFile)(self.handle,buf,65,C.byref(n),C.byref(overlap))
            if not ok:
                if C.get_last_error()!=997:self.api.check(False,'HID read' if reading else 'HID write')
                pending=True
                wait=k.WaitForSingleObject(overlap.hEvent,min(0xFFFFFFFE,max(1,math.ceil(remaining*1000))))
                if wait==258:raise TimeoutError('HID response deadline; no automatic command replay')
                if wait!=0:self.api.check(False,'Wait HID I/O')
                # Includes errors on unplug/cancellation, not just event success.
                completed=k.GetOverlappedResult(self.handle,C.byref(overlap),C.byref(n),False)
                # If a driver signalled prematurely (ERROR_IO_INCOMPLETE), still cancel
                # and drain before releasing its buffer. Other errors are terminal completions.
                if completed or C.get_last_error()!=996:pending=False
                self.api.check(completed,'Complete HID I/O')
            if n.value!=65:raise HidError(f'Short HID report: {n.value}/65 bytes')
            return bytes(buf.raw) if reading else n.value
        finally:
            if pending:
                # Cancel is only a request. Keep the buffer/OVERLAPPED/event alive until
                # completion is acknowledged, including drivers that cancel slowly.
                k.CancelIoEx(self.handle,C.byref(overlap))
                k.GetOverlappedResult(self.handle,C.byref(overlap),C.byref(n),True)
            k.CloseHandle(overlap.hEvent)

    def write(self,report,deadline):
        if len(report)!=65:raise ValueError('HID reports must be exactly 65 bytes')
        return self._io(bytes(report),False,deadline)

    def read(self,deadline):return self._io(None,True,deadline)

    def close(self):
        if self.handle is not None:self.api.k.CloseHandle(self.handle);self.handle=None
        if self.mutex:
            if self.owned:self.api.k.ReleaseMutex(self.mutex)
            self.api.k.CloseHandle(self.mutex);self.mutex=None;self.owned=False

    def __enter__(self):return self.open()
    def __exit__(self,*exc):self.close()
