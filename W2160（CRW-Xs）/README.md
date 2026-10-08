# 北京握奇 (Watchdata) W2160 / CRW-X 多功能智能卡读写器操作实录与开发套件

本目录完整收录针对 **北京握奇 (Watchdata) W2160 多功能扫码读写器 (CRW-X 协议)** 的逆向分析、串口协议规范、纯 Python 直驱驱动、自动化测试脚本、硬件故障排查报告以及原厂资料。

---

## 目录结构

```text
W2160（CRW-Xs）/
├── README.md                  # 本文档：完整的技术报告、协议规范与使用指南
├── driver_issue_evidence.md   # CH340 / HL-340 山寨芯片驱动与硬件缺陷维权报告
├── w2160_reader.py            # 纯 Python 核心驱动库 (无 32 位 DLL 依赖，跨架构直接调用)
├── crwx_cli.py                # 交互式控制台工具 (支持手动发 APDU、切卡槽、跑 .prg 脚本)
├── test_yubikey.py            # YubiKey 5 NFC 综合探测与 Applet 握手测试脚本
├── docs/
│   └── W2160_User_Datasheet.pdf  # 握奇官方英文技术手册 (V1.0)
└── references/
    ├── CRWXDemo.frm           # 官方 VB6 演示上位机界面源码
    ├── CRWXAPI.bas            # 官方 VB6 API 声明及常量定义
    └── sample_test.prg        # 原厂 .prg 自动化测试脚本示例
```

---

## 1. 硬件与驱动踩坑排查实录

在初期测试过程中，读卡器接在 USB-to-RS232 线连接电脑时，任何软件打开对应端口（`COM6`）均报错：
> `A device attached to the system is not functioning (错误代码 31: 连到系统上的设备没有发挥作用)`

通过严格的底层 Win32 API 追踪与单步隔离测试，查明了技术根因：
1. **山寨 HL-340 芯片与新版驱动冲突**：商家售卖的线材使用了假冒/克隆的 HL-340 黑胶芯片，Windows 11 自动更新的最新官方驱动（`CH341S64.SYS` 2024/2026 版）下发波特率配置指令（`SetCommState` / `IOCTL_SERIAL_SET_BAUD_RATE`）时，克隆芯片无法响应，导致堆栈报错 31。
2. **严密的对照实验**：
   * 拔掉读卡器单插新线依然报错，排除读卡器干扰。
   * 插同一台电脑另一根旧的路由器配置线，所有波特率全部秒通，排除电脑与 USB 接口问题。
   * 将驱动降级至 2011 年宽松版本（`3.3.2011.11`）后，`COM6` 恢复正常打开与收发数据。
3. **详细报告参见**：[driver_issue_evidence.md](driver_issue_evidence.md)。

---

## 2. 握奇 W2160 底层通信协议规范

W2160 采用标准串口通信（默认 **9600, 8, N, 1**，支持偶校验 **E**），底层采用 **T=1 帧封装 + BCC 校验**：

### 2.1 发送帧结构 (PC -> Reader)

| 字节偏移 | 字段名称 | 长度 | 描述与取值 |
| :--- | :--- | :--- | :--- |
| `0` | **NAD** | 1 Byte | 卡槽标识：<br>• `0x15`：非接触卡 (NFC / Mifare / CPU卡 / YubiKey)<br>• `0x12`：接触式用户卡槽<br>• `0x16 ~ 0x19`：SAM1 ~ SAM4 卡槽<br>• `0x00`：读卡器系统内置指令 |
| `1` | **LEN_H** | 1 Byte | APDU 长度高字节 |
| `2` | **LEN_L** | 1 Byte | APDU 长度低字节 |
| `3 ~ N` | **APDU** | N Bytes | 标准 ISO 7816-4 APDU 指令 (`CLA INS P1 P2 Lc Data...`) |
| `N+1` | **BCC** | 1 Byte | 纵向冗余校验码：从 `NAD` 到 `APDU` 最后一个字节的所有数据做 `XOR`（异或） |

### 2.2 接收帧结构 (Reader -> PC)

| 字节偏移 | 字段名称 | 长度 | 描述与取值 |
| :--- | :--- | :--- | :--- |
| `0` | **NAD** | 1 Byte | 卡槽标识半字节翻转（如发送 `0x15`，接收返回 `0x51`；发送 `0x12`，返回 `0x21`） |
| `1` | **LEN_H** | 1 Byte | 响应数据长度高字节 |
| `2` | **LEN_L** | 1 Byte | 响应数据长度低字节（包含数据及末尾 2 字节 SW） |
| `3 ~ M-1` | **DATA** | 可选 | 卡片返回数据或 ATR 响应串 |
| `M, M+1` | **SW1 SW2** | 2 Bytes | 卡片/读卡器状态码（如 `9000` 表示成功，`6FF0` 表示超时未寻到卡） |
| `M+2` | **BCC** | 1 Byte | 全帧异或校验码 |

---

## 3. 实测案例记录

### 3.1 废旧交通银行银联信用卡 (PBOC / EMV 接触式/非接触式卡)
* **寻卡复位指令 (NAD=0x15)**：`15 00 05 00 12 00 00 00 02`
* **读卡器响应**：`51 00 19 00 04 6c 78 e0 ab 5f 28 0f 78 80 75 02 86 65 00 a7 08 c0 46 00 90 00 90 00 2e`
* **状态码**：`9000` 成功，成功获取该银联卡的完整 ATS 数据。

### 3.2 YubiKey 5 NFC (高安全硬件密钥)
> **注意**：YubiKey 5 NFC 在进入射频场后需要大约 **400ms 的冷启动供电与固件自检时间**，发送寻卡复位时需配置充足的重试与超时保护。

实测四大核心 Applet 均完美握手：
1. **ATS / ATR 读取**：
   * 报文末尾解码出原生 ASCII 字符串标识：`"YubiKey"`
2. **YubiKey Management Applet** (`A000000527471117`)：
   * 成功读取设备固件版本：`"Virtual mgr - FW version 5.4.3"`
3. **FIDO2 / WebAuthn Applet** (`A0000006472F0001`)：
   * 成功响应 `9000`，接口版本：`"U2F_V2"`
4. **PIV 智能卡 Applet** (`A00000030800001000`)：
   * 成功响应 `9000`，返回完整的 PIV 证书目录。
5. **OATH 动态口令 Applet** (`A0000005272101`)：
   * 成功响应 `9000`，Authenticator 引擎就绪。

---

## 4. 快速上手

### 4.1 环境准备
无需安装任何老旧 32 位驱动或 DLL，支持 Windows 10 / 11 上的任意 64 位 Python 3：
```bash
# 不需要额外的 pip 第三方包，基于原生 Win32 API
python --version
```

### 4.2 运行交互式控制台
```powershell
python crwx_cli.py
```
* 直接输入十六进制 APDU（如 `0012000000` 复位卡片）
* 输入 `nad 15` 或 `nad 12` 切换非接触 / 接触大卡
* 输入 `prg references/sample_test.prg` 执行自动化测试脚本

### 4.3 运行 YubiKey 自动化测试
```powershell
python test_yubikey.py COM6
```

### 4.4 在自己的代码中集成
```python
from w2160_reader import W2160Reader

with W2160Reader("COM6") as reader:
    sw, data, _ = reader.reset_rf_card()
    if sw == "9000":
        print("读到卡片 ATR:", data.hex())
```
