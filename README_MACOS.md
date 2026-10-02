# China-HID-SmartCard-PCSC (macOS 原生驱动与 PC/SC 桥接套件)

> **Universal macOS PC/SC Bridges for Chinese Driverless USB-HID Smart Card Readers**  
> 专为 macOS（Apple Silicon M系列 M1~M4 / Intel x86_64）打造的国产“免驱 HID”智能卡读卡器原生驱动与桥接工具箱。  
> 彻底摆脱 Windows 32 位 DLL 依赖，采用跨平台原生 USB-HID 协议栈与系统级 PC/SC 桥接架构。

---

## 🌟 核心特性与架构升级

在 Windows 版本中，中继依赖厂商官方提供的 32 位专有动态库（`dcic32.dll` / `RK501API.dll`）。  
在 macOS 上，本项目通过**静态逆向与汇编反编译**，直接提取出底层的 **USB-HID 链路层多报文传输协议（Multi-report Feature Reports）与 ISO 14443-4 T=CL 射频状态机**，实现了：

1. **纯原生 Python + `libhidapi` 驱动**：
   - 零 Windows DLL 依赖，零 Wine/虚拟机依赖。
   - 原生支持 **Apple Silicon (M1/M2/M3/M4, ARM64)** 与 **Intel (x86_64)**。
2. **多报文重组与 ISO 14443-4 T=CL 完整实现**：
   - 完整支持等待时间扩展 `S(WTX)`（处理大算力加密操作）。
   - 完整支持报文分片与重组 `R(ACK)` 链路层级联（处理 PIV/OpenPGP 长证书与长 FCI 回复）。
   - 自动处理多 Feature Report 汇编流（突破单报告 31 字节硬件限制）。
3. **免驱直连 GlobalPlatformPro (`./gp_mac.sh`)**：
   - **直连 JavaCard / 跑 APDU，跳过 VPCD 和系统驱动**！
   - 内置纯 Java Direct BIBO 桥接器（`tools/GPDirect.java`），直接对接官方 `gp.jar`。
   - 完整支持 SCP02 / SCP03 双向加密认证，秒级列出、安装、卸载 Applet！
4. **离线仿真模式 (`--mock`)**：
   - 内置 **Virtual JavaCard 仿真卡**，即使**没有插入拓展坞或读卡器**，也能进行全流程 APDU、ATR 探测与软件调试！
5. **系统级全兼容模式 (`ifd-vpcd.bundle`)**：
   - 接入 macOS `SmartCardServices`，让 **Chrome/Safari (WebAuthn/Passkey)**、**GnuPG (`gpg --card-status`)** 和 **OpenSC** 将其识别为标准合规读卡器。

---

## 🚀 快速上手指南

### 1. 安装基础依赖
macOS 仅需通过 Homebrew 安装一个轻量库 `hidapi`（如果未安装）：
```bash
brew install hidapi
```

---

### 2. 方式 A：免驱动玩转 GlobalPlatform（首选推荐！跳过系统驱动）

如果你当前的核心需求是**管理 JavaCard / 跑 `gp` / 查看已安装 Applet / 装卡**，你可以**完全跳过 PC/SC 驱动与 VPCD**！

#### 一键运行 GlobalPlatformPro
项目已预编译 `gp.jar` 与直连驱动封装，只需一条命令：

```bash
# 查看卡片 CPLC 与芯片信息
./gp_mac.sh -info

# 列出卡片内安装的所有 Applet / Package（自动完成 SCP02 认证）
./gp_mac.sh -l

# 详细调试日志（查看每个 APDU 与会话密钥）
./gp_mac.sh -l -v

# 安装 Applet (.cap 包)
./gp_mac.sh --install myapplet.cap

# 卸载 Applet / Package
./gp_mac.sh --delete <AID>
```

> **实机验证**：已在 **DeCard T6 双界面读卡器 (`0471:a112`) + NXP JCOP J3R200 非接卡** 上实测验证，瞬间识别出卡内安装的 **PIV (`A000000308000010000100`)**、**OpenPGP (`D27600012401`)**、**FIDO2 (`A0000005272101014546513101`)** 等全部 Applet！

#### 纯 Python 零依赖轻量工具 (`gp_lite.py`)
```bash
# 查看卡片 CPLC 与安全域信息
python3 tools/gp_lite.py -i

# 发送任意自定义 APDU（例如选择主应用）
python3 tools/gp_lite.py -a "00A4040000"

# 【无硬件离线测试】如果你此时没带拓展坞，加 --mock 即可直接跑通！
python3 tools/gp_lite.py --mock -i -l
```

---

### 3. 方式 B：系统级全场景 PC/SC 兼容（Chrome Passkey / GPG / OpenSC）

如果你需要让整个 macOS 系统（如 Safari、Chrome 网页安全密钥、GnuPG）都识别出物理读卡器：

#### 第一步：启动 Mac 桥接中继
```bash
# 德卡 T6 / T10（二合一智能感知：接触插槽 + 非接触挥卡）
./start_decard_mac.sh

# 飞天诚信 SCR501 (ROCKEY 531)
./start_feitian_mac.sh
```

#### 第二步：编译并安装 macOS 虚拟驱动 `ifd-vpcd`
本项目已内置一键编译脚本（自动使用 `clang` 编译出适合 macOS `SmartCardServices` 的驱动 Bundle）：
```bash
# 1. 一键编译
./tools/build_macos_vpcd.sh

# 2. 安装至系统标准驱动目录（需 sudo 权限，但无需关闭 SIP！）
sudo mkdir -p /usr/local/libexec/SmartCardServices/drivers
sudo cp -r build_vpcd/ifd-vpcd.bundle /usr/local/libexec/SmartCardServices/drivers/

# 3. 刷新 macOS 智能卡子系统
sudo killall -SIGKILL -m .com.apple.ifdreader 2>/dev/null || true
```

验证系统级识别状态：
```bash
pcsctest
# 或
security list-smartcards
```

---

## 🧪 自动化测试套件

你可以在任何时候运行我们的自动化测试套件（硬件已连接时测真机，无硬件时自动测试仿真）：
```bash
./test_gp_mac.sh
```
该测试会全自动验证：
1. `libhidapi` 动态库加载与设备枚举；
2. 德卡帧打包（STX/ETX）、XOR BCC 校验与多报告分片重组；
3. 非接 ATS 到 PC/SC ATR 实时转译；
4. 仿真卡 ISO-7816 与 GlobalPlatform APDU 状态机；
5. TCP 35963 本地套接字双工会话；
6. 物理卡片 GlobalPlatformPro Mutual SCP02 握手与 Applet 清单获取。

---

## 📁 目录文件清单

```text
├── gp_mac.sh                       # GlobalPlatformPro macOS 直连启动器（免系统驱动）
├── start_decard_mac.sh             # 德卡 T6/T10 macOS 桥接后台服务
├── start_feitian_mac.sh            # 飞天 SCR501 macOS 桥接后台服务
├── test_gp_mac.sh                  # 一键端到端全链路诊断测试
│
├── mac_drivers/                    # 纯原生 macOS 驱动模块
│   ├── hid_transport.py            # libhidapi ctypes 跨架构封装
│   ├── decard_hid.py               # 德卡协议解析、多报文分片重组与 T=CL 引擎
│   ├── feitian_hid.py              # 飞天协议解析与打包收发引擎
│   └── mock_card.py                # JavaCard / GlobalPlatform 离线仿真卡
│
├── scripts/
│   ├── decard_mac_bridge.py        # 德卡 macOS 统一 TCP 桥接服务
│   └── feitian_mac_bridge.py       # 飞天 macOS 统一 TCP 桥接服务
│
└── tools/
    ├── gp.jar                      # GlobalPlatformPro 官方工具包 (v25.10.20)
    ├── GPDirect.java               # apdu4j 直连套接字驱动封装（Bypass PC/SC）
    ├── gp_lite.py                  # 纯 Python 版轻量 GP 客户端
    ├── build_macos_vpcd.sh         # macOS ifd-vpcd.bundle 一键编译工具
    └── test_mac_pipeline.py        # 单元与集成自动化测试套件
```
