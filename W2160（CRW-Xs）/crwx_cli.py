"""
Watchdata W2160 / CRW-X Smart Card Reader Python Tool
Pure Python implementation matching CRWXDemo.frm & CRWXAPI.bas
No 32-bit wdcrwx.dll required!
"""
import ctypes
from ctypes import wintypes
import time
import os
import sys

kernel32 = ctypes.windll.kernel32

class CRWXReader:
    def __init__(self, port="COM6", baudrate=9600, parity='N'):
        self.port = port
        self.baudrate = baudrate
        self.parity = parity.upper()
        self.handle = None
        self.nad = 0x15 # Default: Contactless Card (非接触卡)

    def open(self):
        self.handle = kernel32.CreateFileW(
            rf"\\.\{self.port}", 0xC0000000, 0, None, 3, 0x80, None
        )
        if self.handle == -1:
            err = kernel32.GetLastError()
            raise Exception(f"无法打开串口 {self.port} (Win32 Error: {err})")
        
        # Configure Timeouts
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

    def set_nad(self, nad):
        """设置当前操作卡槽 (00:读卡器, 12:接触卡, 13:SAM1, 14:ESAM, 15:非接触卡)"""
        self.nad = nad

    def _bcc(self, data):
        b = 0
        for x in data:
            b ^= x
        return b

    def transmit(self, apdu_hex_or_bytes, nad=None):
        """发送 APDU 并接收响应，返回 (sw, data_hex, raw_resp)"""
        if nad is None:
            nad = self.nad

        if isinstance(apdu_hex_or_bytes, str):
            clean_hex = "".join(apdu_hex_or_bytes.split())
            apdu = bytes.fromhex(clean_hex)
        else:
            apdu = bytes(apdu_hex_or_bytes)

        # 封装帧: [NAD] [LEN_H] [LEN_L] [APDU...] [BCC]
        hdr = bytes([nad, (len(apdu) >> 8) & 0xFF, len(apdu) & 0xFF])
        payload = hdr + apdu
        pkt = payload + bytes([self._bcc(payload)])

        # 清空缓冲区并发送
        kernel32.PurgeComm(self.handle, 0x000F)
        bw = wintypes.DWORD(0)
        kernel32.WriteFile(self.handle, pkt, len(pkt), ctypes.byref(bw), None)

        time.sleep(0.12)
        rbuf = ctypes.create_string_buffer(512)
        br = wintypes.DWORD(0)
        kernel32.ReadFile(self.handle, rbuf, 512, ctypes.byref(br), None)
        resp = rbuf.raw[:br.value]

        if len(resp) < 4:
            return None, "", b""

        # 校验 BCC
        if self._bcc(resp[:-1]) != resp[-1]:
            print(f"[!] 警告: 接收到响应 BCC 校验失败!")

        body = resp[3:-1]
        sw = body[-2:].hex().upper() if len(body) >= 2 else ""
        data_hex = body[:-2].hex().upper() if len(body) > 2 else ""
        return sw, data_hex, resp

    def run_prg_file(self, prg_path):
        """运行原厂 .prg 自动化测试脚本"""
        print(f"\n[*] 开始执行 PRG 脚本: {prg_path}")
        if not os.path.exists(prg_path):
            print(f"[-] 文件不存在: {prg_path}")
            return

        with open(prg_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        for idx, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("/"):
                continue

            if line.upper().startswith("NAD"):
                parts = line.split("=")
                if len(parts) == 2:
                    self.set_nad(int(parts[1].strip(), 16))
                    print(f"[{idx}] 切换卡槽 NAD = 0x{self.nad:02X}")
                continue

            # 拆分 SW 比对部分
            expected_sw = ""
            expected_data = ""
            if "SW" in line.upper():
                p_sw = line.upper().split("SW")
                cmd_part = p_sw[0]
                expected_sw = p_sw[1].strip()
            else:
                cmd_part = line

            if "R" in cmd_part.upper():
                p_r = cmd_part.upper().split("R")
                apdu_str = p_r[0].strip()
                expected_data = p_r[1].strip()
            else:
                apdu_str = cmd_part.strip()

            sw, data_hex, _ = self.transmit(apdu_str)
            status_ok = True
            if expected_sw and expected_sw != "FFFF" and sw != expected_sw:
                status_ok = False
            if expected_data and data_hex != expected_data:
                status_ok = False

            mark = "✅ PASS" if status_ok else "❌ FAIL"
            print(f"[{idx}] TX: {apdu_str}")
            print(f"    RX Data: {data_hex} | SW: {sw} -> {mark} (Expect SW:{expected_sw})")

    def close(self):
        if self.handle and self.handle != -1:
            kernel32.CloseHandle(self.handle)
            self.handle = None

def interactive_cli():
    reader = CRWXReader("COM6")
    try:
        reader.open()
        print("="*60)
        print("  握奇 W2160 / CRW-X 读卡器控制台 (COM6)")
        print("  命令指南:")
        print("    - 直接输入十六进制 APDU (如 0012000000 复位卡片)")
        print("    - nad 15 / nad 12: 切换卡槽 (15=非接触卡, 12=接触大卡)")
        print("    - prg <文件路径>: 执行 .prg 自动化脚本")
        print("    - q: 退出")
        print("="*60)
        
        while True:
            cmd = input(f"\n[NAD:0x{reader.nad:02X}] > ").strip()
            if not cmd:
                continue
            if cmd.lower() in ['q', 'exit', 'quit']:
                break
            if cmd.lower().startswith("nad "):
                new_nad = int(cmd.split()[1], 16)
                reader.set_nad(new_nad)
                print(f"已切换卡槽为: 0x{reader.nad:02X}")
                continue
            if cmd.lower().startswith("prg "):
                prg_f = cmd[4:].strip()
                reader.run_prg_file(prg_f)
                continue

            try:
                sw, data, _ = reader.transmit(cmd)
                print(f"  --> 返回状态字 (SW): {sw}")
                if data:
                    print(f"  --> 返回卡片数据: {data}")
            except Exception as e:
                print(f"[-] 执行出错: {e}")
    finally:
        reader.close()
        print("\n串口已安全关闭。")

if __name__ == "__main__":
    interactive_cli()
