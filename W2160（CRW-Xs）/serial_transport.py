"""Typed Windows serial I/O for CRW-Xs. No external packages or vendor DLL required."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import os
import re
import time

class SerialError(OSError):
    pass

@dataclass(frozen=True)
class PortInfo:
    name: str
    description: str

def normalize_port(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"COM[1-9][0-9]{0,3}", value):
        raise ValueError("Port must be a Windows serial name such as COM3")
    return value

def available_ports() -> list[PortInfo]:
    if os.name != "nt":
        raise SerialError("This serial bridge currently targets Windows")
    import winreg
    names = set()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            i = 0
            while True:
                try:
                    _, name, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if isinstance(name, str) and re.fullmatch(r"COM[1-9][0-9]*", name.upper()):
                    names.add(name.upper())
    except FileNotFoundError:
        pass
    # Registry enumeration does not open or probe unrelated serial hardware.
    return [PortInfo(n, "Windows serial port") for n in sorted(names, key=lambda n: int(n[3:]))]

class DCB(C.Structure):
    _fields_ = [("DCBlength", W.DWORD), ("BaudRate", W.DWORD), ("flags", W.DWORD),
                ("wReserved", W.WORD), ("XonLim", W.WORD), ("XoffLim", W.WORD),
                ("ByteSize", W.BYTE), ("Parity", W.BYTE), ("StopBits", W.BYTE),
                ("XonChar", C.c_char), ("XoffChar", C.c_char), ("ErrorChar", C.c_char),
                ("EofChar", C.c_char), ("EvtChar", C.c_char), ("wReserved1", W.WORD)]

class Timeouts(C.Structure):
    _fields_ = [(n, W.DWORD) for n in ("interval", "read_multiplier", "read_constant", "write_multiplier", "write_constant")]

class ComStat(C.Structure):
    _fields_ = [("flags", W.DWORD), ("in_queue", W.DWORD), ("out_queue", W.DWORD)]

class WindowsSerial:
    def __init__(self, port: str, baudrate: int = 9600, parity: str = "N"):
        self.port = normalize_port(port)
        if baudrate not in (9600, 19200, 38400, 57600, 115200):
            raise ValueError("Unsupported baud rate")
        if parity not in ("N", "E"):
            raise ValueError("Parity must be N or E")
        self.baudrate, self.parity, self.handle = baudrate, parity, None
        self._api = None

    def _load(self):
        if os.name != "nt":
            raise SerialError("Windows serial I/O required")
        k = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": ([W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
            "CloseHandle": ([W.HANDLE], W.BOOL),
            "GetCommState": ([W.HANDLE, C.POINTER(DCB)], W.BOOL),
            "SetCommState": ([W.HANDLE, C.POINTER(DCB)], W.BOOL),
            "SetCommTimeouts": ([W.HANDLE, C.POINTER(Timeouts)], W.BOOL),
            "SetupComm": ([W.HANDLE, W.DWORD, W.DWORD], W.BOOL),
            "PurgeComm": ([W.HANDLE, W.DWORD], W.BOOL),
            "ReadFile": ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            "WriteFile": ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            "ClearCommError": ([W.HANDLE, C.POINTER(W.DWORD), C.POINTER(ComStat)], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            func = getattr(k, name); func.argtypes = args; func.restype = result
        self._api = k

    def _check(self, result, operation):
        if not result:
            code = C.get_last_error()
            raise SerialError(code, f"{self.port}: {operation} failed (Win32 {code})")

    def open(self):
        if self.handle is not None:
            raise SerialError("Serial port already open")
        self._load()
        k = self._api
        h = k.CreateFileW('\\\\.\\' + self.port, 0xC0000000, 0, None, 3, 0, None)
        if h == W.HANDLE(-1).value:
            self._check(False, "open; port may be absent or in use")
        self.handle = h
        try:
            dcb = DCB(); dcb.DCBlength = C.sizeof(DCB)
            self._check(k.GetCommState(h, C.byref(dcb)), "GetCommState")
            dcb.BaudRate = self.baudrate
            # Binary, explicit parity check, DTR and RTS on; no CTS/DSR/XON flow control.
            dcb.flags = 1 | (2 if self.parity == "E" else 0) | (1 << 4) | (1 << 12)
            dcb.ByteSize = 8; dcb.Parity = 2 if self.parity == "E" else 0; dcb.StopBits = 0
            self._check(k.SetCommState(h, C.byref(dcb)), "SetCommState")
            self._check(k.SetupComm(h, 131072, 131072), "SetupComm")
            # Return partial reads promptly; exact-frame assembly uses one monotonic deadline.
            timeout = Timeouts(20, 0, 50, max(1, (12000 + self.baudrate - 1) // self.baudrate), 1000)
            self._check(k.SetCommTimeouts(h, C.byref(timeout)), "SetCommTimeouts")
            self._check(k.PurgeComm(h, 0x0F), "initial purge")
            return self
        except BaseException:
            self.close(); raise

    def check_errors(self):
        if self.handle is None:
            raise SerialError("Serial port is closed")
        errors, stat = W.DWORD(), ComStat()
        self._check(self._api.ClearCommError(self.handle, C.byref(errors), C.byref(stat)), "ClearCommError")
        if errors.value:
            raise SerialError(f"{self.port}: UART error flags 0x{errors.value:X}; frame discarded")
        return stat.in_queue

    def write_all(self, data: bytes, deadline: float):
        offset = 0
        while offset < len(data):
            if time.monotonic() >= deadline:
                raise TimeoutError("Serial write deadline; command execution may be uncertain")
            self.check_errors()
            chunk = data[offset:offset + 4096]; buf = C.create_string_buffer(chunk)
            written = W.DWORD()
            self._check(self._api.WriteFile(self.handle, buf, len(chunk), C.byref(written), None), "WriteFile")
            if not 0 < written.value <= len(chunk):
                raise SerialError("Serial write made no progress")
            offset += written.value

    def read_exact(self, count: int, deadline: float) -> bytes:
        result = bytearray()
        while len(result) < count:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Serial frame deadline ({len(result)}/{count} bytes); no automatic APDU replay")
            self.check_errors()
            n = min(count - len(result), 4096); buf = C.create_string_buffer(n); received = W.DWORD()
            self._check(self._api.ReadFile(self.handle, buf, n, C.byref(received), None), "ReadFile")
            if received.value > n:
                raise SerialError("Invalid serial receive count")
            result.extend(buf.raw[:received.value])
        self.check_errors()
        return bytes(result)

    def close(self):
        h, self.handle = self.handle, None
        if h is not None:
            self._api.CloseHandle(h)

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
