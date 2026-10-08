"""
Watchdata W2160 / CRW-X Smart Card Reader Pure Python Driver
Author: chx818 & Antigravity
License: Apache-2.0 / MIT

Direct Win32 Serial implementation without legacy 32-bit wdcrwx.dll.
Supports:
  - Contactless cards (NFC, ISO 14443 Type A/B, Mifare, YubiKey)
  - Contact smart cards (ISO 7816, CPU cards, SLE4442, SLE4428)
  - SAM slots (SAM1 ~ SAM4)
  - APDU transmission, ATR reading, BCC frame encapsulation
"""

import ctypes
from ctypes import wintypes
import time

kernel32 = ctypes.windll.kernel32

class W2160Reader:
    # NAD 卡槽定义
    NAD_READER = 0x00       # 读卡器自身系统指令
    NAD_CONTACT = 0x12      # 用户接触式大卡
    NAD_SAM1 = 0x13         # SAM1 卡槽 (或 0x16，依固件版本)
    NAD_ESAM = 0x14         # ESAM 安全芯片 (或 0x17)
    NAD_CONTACTLESS = 0x15  # 非接触射频卡 (NFC / Mifare / CPU / YubiKey)
    NAD_MAGSTRIPE = 0x1A    # 磁条卡

    def __init__(self, port="COM6", baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.handle = None

    def open(self):
        """打开串口设备并配置超时"""
        self.handle = kernel32.CreateFileW(
            rf"\\.\{self.port}", 0xC0000000, 0, None, 3, 0x80, None
        )
        if self.handle == -1:
            err = kernel32.GetLastError()
            raise IOError(f"无法打开端口 {self.port}，Win32 错误码: {err}")

        # 配置读写超时 (ms)
        class COMMTIMEOUTS(ctypes.Structure):
            _fields_ = [
                ("ReadIntervalTimeout", wintypes.DWORD),
                ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
                ("ReadTotalTimeoutConstant", wintypes.DWORD),
                ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
                ("WriteTotalTimeoutConstant", wintypes.DWORD),
            ]
        t = COMMTIMEOUTS(50, 0, 1000, 0, 1000)
        kernel32.SetCommTimeouts(self.handle, ctypes.byref(t))

    def _bcc(self, data):
        """计算纵向冗余校验 (BCC, 全字节异或)"""
        b = 0
        for x in data:
            b ^= x
        return b

    def send_apdu(self, nad, apdu_bytes, timeout=0.15):
        """
        向指定卡槽发送 APDU 指令并接收响应
        :param nad: 目标卡槽 (如 0x15 非接触卡, 0x12 接触卡)
        :param apdu_bytes: APDU 指令字节序列
        :return: (sw: str, data: bytes, raw: bytes)
        """
        if not self.handle or self.handle == -1:
            raise IOError("读卡器未连接，请先调用 open()")

        if isinstance(apdu_bytes, (list, tuple)):
            apdu_bytes = bytes(apdu_bytes)
        elif isinstance(apdu_bytes, str):
            apdu_bytes = bytes.fromhex("".join(apdu_bytes.split()))

        # 封装协议帧: [NAD] [LEN_H] [LEN_L] [APDU...] [BCC]
        hdr = bytes([nad, (len(apdu_bytes) >> 8) & 0xFF, len(apdu_bytes) & 0xFF])
        payload = hdr + apdu_bytes
        pkt = payload + bytes([self._bcc(payload)])

        # 清空缓冲区后下发
        kernel32.PurgeComm(self.handle, 0x000F)
        bw = wintypes.DWORD(0)
        kernel32.WriteFile(self.handle, pkt, len(pkt), ctypes.byref(bw), None)

        time.sleep(timeout)
        rbuf = ctypes.create_string_buffer(512)
        br = wintypes.DWORD(0)
        kernel32.ReadFile(self.handle, rbuf, 512, ctypes.byref(br), None)
        resp = rbuf.raw[:br.value]

        if len(resp) < 4:
            return None, b"", resp

        # 校验 BCC
        if self._bcc(resp[:-1]) != resp[-1]:
            raise ValueError(f"响应数据校验失败: 计算 BCC={self._bcc(resp[:-1]):02X}, 接收 BCC={resp[-1]:02X}")

        body = resp[3:-1]
        sw = body[-2:].hex().upper() if len(body) >= 2 else ""
        data = body[:-2] if len(body) > 2 else b""
        return sw, data, resp

    def reset_rf_card(self, timeout=0.5):
        """非接触 NFC / CPU 卡寻卡复位 (NAD=0x15, 00 12 00 00 00)"""
        return self.send_apdu(self.NAD_CONTACTLESS, [0x00, 0x12, 0x00, 0x00, 0x00], timeout=timeout)

    def reset_contact_card(self, timeout=0.5):
        """接触式大卡槽寻卡复位 (NAD=0x12, 00 12 00 00 00)"""
        return self.send_apdu(self.NAD_CONTACT, [0x00, 0x12, 0x00, 0x00, 0x00], timeout=timeout)

    def close(self):
        """关闭串口句柄"""
        if self.handle and self.handle != -1:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
