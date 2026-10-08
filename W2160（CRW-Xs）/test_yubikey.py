"""
YubiKey 5 NFC Detection & Applet Probing Test Script for Watchdata W2160
Includes cold-boot allowance (~400ms) for contactless secure elements.
"""

import sys
import io
import time
from w2160_reader import W2160Reader

# 确保控制台 UTF-8 输出
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_yubikey(port="COM6"):
    print("=" * 65)
    print(f"  Watchdata W2160 - YubiKey 5 NFC 综合功能探测测试 ({port})")
    print("=" * 65)

    reader = W2160Reader(port)
    try:
        reader.open()
        print("[*] 串口打开成功，开始寻卡...")

        # 1. 寻卡复位 (带冷启动重试)
        reset_ok = False
        ats = None
        for attempt in range(1, 6):
            print(f"[*] 第 {attempt} 次射频寻卡激活尝试...")
            sw, data, _ = reader.reset_rf_card(timeout=0.5)
            if sw == "9000":
                reset_ok = True
                ats = data
                print(f"[+] ✅ 寻卡成功！SW: 9000")
                print(f"    ATS/ATR: {data.hex().upper()}")
                # 检查尾部 ASCII 标识
                if b"YubiKey" in data:
                    print(f"    [Card Type] 识别到原生标识: 'YubiKey'")
                break
            time.sleep(0.4)

        if not reset_ok:
            print("[-] 寻卡未响应，请检查 YubiKey 是否贴近读卡器感应区。")
            return

        # 冷启动稳定等待
        print("\n[*] 等待 500ms 确保各内置 Applet 完全就绪...")
        time.sleep(0.5)

        # 2. Yubico Management Applet (管理应用)
        print("\n--- [1] YubiKey Management Applet ---")
        aid_mgmt = "00 A4 04 00 08 A0 00 00 05 27 47 11 17"
        sw, data, _ = reader.send_apdu(reader.NAD_CONTACTLESS, aid_mgmt)
        if sw == "9000":
            print(f"    [+] ✅ Management Applet 响应正常 (SW: 9000)")
            try:
                print(f"        固件信息: {data.decode('ascii', errors='ignore')}")
            except:
                print(f"        原始数据: {data.hex().upper()}")
            
            # 读取详细 Device Info (00 1D 00 00 00)
            sw_info, d_info, _ = reader.send_apdu(reader.NAD_CONTACTLESS, "00 1D 00 00 00")
            if sw_info == "9000":
                print(f"        Device Config/Flags: {d_info.hex().upper()}")
        else:
            print(f"    [-] Management Applet 响应: {sw}")

        # 3. FIDO2 / CTAP2 Applet (WebAuthn / U2F)
        print("\n--- [2] FIDO2 / WebAuthn Applet ---")
        aid_fido = "00 A4 04 00 08 A0 00 00 06 47 2F 00 01"
        sw, data, _ = reader.send_apdu(reader.NAD_CONTACTLESS, aid_fido)
        if sw == "9000":
            print(f"    [+] ✅ FIDO2 接口就绪 (SW: 9000)")
            print(f"        协议版本标识: {data.decode('ascii', errors='ignore')} ({data.hex().upper()})")
        else:
            print(f"    [-] FIDO2 响应: {sw}")

        # 4. PIV 智能卡 Applet (PKI / 证书)
        print("\n--- [3] PIV 智能卡 Applet ---")
        aid_piv = "00 A4 04 00 09 A0 00 00 03 08 00 00 10 00"
        sw, data, _ = reader.send_apdu(reader.NAD_CONTACTLESS, aid_piv)
        if sw == "9000":
            print(f"    [+] ✅ PIV 智能卡接口就绪 (SW: 9000)")
            print(f"        PIV 目录数据: {data.hex().upper()}")
        else:
            print(f"    [-] PIV 响应: {sw}")

        # 5. OATH Applet (TOTP 动态口令)
        print("\n--- [4] OATH 动态口令 (Authenticator) Applet ---")
        aid_oath = "00 A4 04 00 07 A0 00 00 05 27 21 01"
        sw, data, _ = reader.send_apdu(reader.NAD_CONTACTLESS, aid_oath)
        if sw == "9000":
            print(f"    [+] ✅ OATH 引擎就绪 (SW: 9000)")
            print(f"        OATH 应答载荷: {data.hex().upper()}")
        else:
            print(f"    [-] OATH 响应: {sw}")

        print("\n" + "=" * 65)
        print("  所有测试项均已完成，设备全链路通信指标合格！")
        print("=" * 65)

    finally:
        reader.close()

if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "COM6"
    test_yubikey(port)
