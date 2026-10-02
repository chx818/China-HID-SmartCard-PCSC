"""
macOS USB-HID Transport Abstraction using libhidapi
Compatible with Apple Silicon (ARM64) and Intel (x86_64) macOS.
"""

import ctypes
import os
import sys
from typing import List, Optional, Tuple

# Search paths for libhidapi on macOS
POSSIBLE_LIB_PATHS = [
    "/opt/homebrew/lib/libhidapi.dylib",
    "/usr/local/lib/libhidapi.dylib",
    "libhidapi.dylib",
]

_hid_lib = None


def get_hid_lib():
    global _hid_lib
    if _hid_lib is not None:
        return _hid_lib

    for p in POSSIBLE_LIB_PATHS:
        try:
            lib = ctypes.CDLL(p)
            _hid_lib = lib
            return _hid_lib
        except OSError:
            continue

    raise RuntimeError(
        "Could not load libhidapi.dylib. Please install it with: brew install hidapi"
    )


class hid_device_info(ctypes.Structure):
    pass


hid_device_info._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(hid_device_info)),
]


class HIDDevice:
    def __init__(self, vid: int, pid: int, path: Optional[bytes] = None):
        self.vid = vid
        self.pid = pid
        self.path = path
        self.handle = None
        self.lib = get_hid_lib()

        # Set up prototypes
        self.lib.hid_init.restype = ctypes.c_int
        self.lib.hid_exit.restype = ctypes.c_int
        self.lib.hid_open.restype = ctypes.c_void_p
        self.lib.hid_open.argtypes = [ctypes.c_ushort, ctypes.c_ushort, ctypes.c_wchar_p]
        self.lib.hid_open_path.restype = ctypes.c_void_p
        self.lib.hid_open_path.argtypes = [ctypes.c_char_p]
        self.lib.hid_write.restype = ctypes.c_int
        self.lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        self.lib.hid_read_timeout.restype = ctypes.c_int
        self.lib.hid_read_timeout.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        self.lib.hid_close.restype = None
        self.lib.hid_close.argtypes = [ctypes.c_void_p]
        self.lib.hid_error.restype = ctypes.c_wchar_p
        self.lib.hid_error.argtypes = [ctypes.c_void_p]

    def open(self) -> bool:
        self.lib.hid_init()
        if self.path:
            self.handle = self.lib.hid_open_path(self.path)
        else:
            self.handle = self.lib.hid_open(self.vid, self.pid, None)

        return self.handle is not None

    def close(self):
        if self.handle:
            self.lib.hid_close(self.handle)
            self.handle = None

    def write(self, data: bytes) -> int:
        if not self.handle:
            raise RuntimeError("Device not open")
        buf = ctypes.create_string_buffer(data, len(data))
        res = self.lib.hid_write(self.handle, buf, len(data))
        if res < 0:
            err = self.lib.hid_error(self.handle)
            raise IOError(f"hid_write failed: {err}")
        return res

    def read(self, length: int, timeout_ms: int = 1000) -> bytes:
        if not self.handle:
            raise RuntimeError("Device not open")
        buf = ctypes.create_string_buffer(length)
        res = self.lib.hid_read_timeout(self.handle, buf, length, timeout_ms)
        if res < 0:
            err = self.lib.hid_error(self.handle)
            raise IOError(f"hid_read failed: {err}")
        return buf.raw[:res]

    @classmethod
    def enumerate_devices(cls, vid: int = 0, pid: int = 0) -> List[Tuple[int, int, str, bytes]]:
        """Returns list of (vid, pid, product_str, path)."""
        lib = get_hid_lib()
        lib.hid_init()
        lib.hid_enumerate.restype = ctypes.POINTER(hid_device_info)
        lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
        lib.hid_free_enumeration.restype = None
        lib.hid_free_enumeration.argtypes = [ctypes.POINTER(hid_device_info)]

        res_list = []
        cur = lib.hid_enumerate(vid, pid)
        head = cur
        while cur:
            dev = cur.contents
            prod = dev.product_string or ""
            path = dev.path or b""
            res_list.append((dev.vendor_id, dev.product_id, prod, path))
            cur = dev.next
        if head:
            lib.hid_free_enumeration(head)
        return res_list
