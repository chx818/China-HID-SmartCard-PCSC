# China-HID-SmartCard-PCSC (中国免驱 HID 智能卡读卡器 PC/SC 桥接驱动套件)

> 支持**华大集成 (Huada HD-100 带屏与密码键盘)**、**德卡 (DeCard T6 / T10)**、**飞天诚信 (Feitian SCR501 / ROCKEY 531)**、**北京握奇 (Watchdata W2160 四合一版 W8298 / W5181 Plus / 串口纯非接版 CRW-Xs)** 等设备，将私有协议秒变 Windows 标准系统智能卡读卡器！


> **2026-10-27 华大集成 (Huada) HD-100 密码键盘液晶屏双界面读卡器深度适配与涅槃支持**：
> - **全新实机逆向与安全加固**：彻底告别早期盲扫误触发 Bootloader 擦除的教训，采用基于官方安全协议栈（`SSSE32.dll`）的无损直驱，零风险、零破坏。
> - **NXP 与复旦微 (FM175xx) 双硬件方案全通配**：针对市场上流通的早期 NXP 方案与新批次复旦微 FM175xx 方案两种硬件版本，实现了全自动自适应通配。早期 NXP 方案实机完整验证；复旦微方案经逆向定位官方动态库 `SSSE32.dll` 递归多帧接收漏洞（RVA `0xEA6B` 条件跳转 Bug），通过精准的单字节补丁（`0xEA6B`: `0x7C` $\to$ `0x75` / `JL` $\to$ `JNE`）彻底解决底层长响应截断崩溃，双版本均实现 100% 稳定运行！
> - **接触与非接双界面完整支持**：接触式插槽（ISO 7816）与非接触射频区（ISO 14443 Type A）自适应接入；接触卡槽支持物理微动开关自动检测插拔，深度优化 T=0 / T=1 协议适配与断电/复位状态机。
> - **FIDO2 / WebAuthn 会话上下文保持**：移除非必要的侵入式空闲轮询 APDU，避免在 JavaCard 上意外卸载已选中的 FIDO2 Applet（防止 Windows Hello 降级跳过 PIN 输入），实测完整支持长 APDU 交互、CTAP2 CBOR 编解码与硬件安全密钥认证。
> - **三启动入口**：`start_huada_unified.bat`（二合一自适应，默认接触优先，支持 `-Priority RfFirst`）、`start_huada_contact.bat`（接触式独立位）、`start_huada_rf.bat`（非接触式独立位）。


> **2026-10-13 握奇数据 (Watchdata) USB 读卡器原生支持更新**：
> - **四合一版 W2160（代号 W8298，`VID_163C&PID_0A1F`）** 与 **W5181 Plus（`VID_163C&PID_0A28`）** 深度适配。
> - **纯 Python 异步重叠 I/O 直驱**：基于原生 65 字节 HID 报文封装与动态分包重组，无需第三方闭源 DLL，跨平台低耦合。
> - **卡槽精细化隔离与安全保护**：原生中继用户接触卡槽 (`NAD=0x12`) 与非接触射频区 (`NAD=0x15`)，主动过滤内部 SAM (`NAD=0x13/0x14/0x16/0x17`)、磁条卡槽 (`NAD=0x1A`) 与扫码枪键盘接口 (`MI_00`)。
> - **三大应用场景实测通过**：通过 FIDO2 / WebAuthn (CTAP2 CBOR 长响应分片接收与探测)、PIV（公钥、CHUID、CCC 读取）、OpenPGP（卡片数据、扩展能力识别）及 PBOC 银行卡完整交互。
> - **三启动入口**：`start_watchdata_unified.bat`（二合一单卡位，默认接触优先，支持 `-Priority RfFirst`）、`start_watchdata_contact.bat`（接触式独立位）、`start_watchdata_rf.bat`（非接触独立位）。
>
> ⚠️ **关于串口版纯非接 W2160 (CRW-Xs) 的特别说明**：
> - 早期退役的**纯非接版 W2160（CRW-Xs，单片机 uPSD3422E + MFRC531）**是一个**特殊的物理存在**：它不是 USB HID 设备，而是标准的 **RS-232 串口设备 (9600 8E1, NAD=12)**！
> - 它的硬件架构、通信分帧与 USB 版完全不同，**不能运行 USB 脚本**。为此我们为其单独打造了串口中继驱动：运行根目录下的 **`start_w2160_serial.bat`** 即可自动枚举并选择 COM 口接入系统。
> - 完整硬件拆解分析、协议细节、指令限制详见独立文档：[W2160 串口版操作说明](W2160（CRW-Xs）/SERIAL_README.md)。

> **德卡 T6 / T10 全系双后端自适应驱动更新**：
> - **双后端自适应引擎（Dual-Backend Engine）**：
>   - **经典款 T6 / T6-URM (`VID_0471&PID_A112`)**：原生优先调用 `dcic32.dll` 驱动接触式卡座与非接区，保持老款经典硬件的原生高可靠性；
>   - **新版 T10 (`VID_0471&PID_A133` 标准版 / `PID_A135` 磁条复合版)**：自动识别并平滑降级调用 `dcrf32.dll` 后端（Slot `0x0C` 接触位 + ISO 14443-A 非接射频位），彻底解决新机型在旧驱动返回 `-32` 枚举失败的问题；
>   - **一套脚本全系通配**：统一脚本内部自动完成硬件探针与 DLL 握手匹配，无论插入哪代硬件均“即插即用”，无需人工区分机型。
> - **YubiKey NFC 慢启动保护与响应提速**：针对 YubiKey 等慢启动非接安全元件，保留 **400ms 启动及业务后安静保护期**，防止高频探测导致卡片反复断联死循环；进入稳定空闲后采用 **200ms 轮询 + 40ms 移卡复查**，兼顾低延迟响应与链路稳定。
> - **即时感应蜂鸣提示**：读卡器成功感应并激活卡片瞬间**立即蜂鸣一声**，提供直观物理反馈，无需等待上层软件连接；原脚本连接读卡器就绪蜂鸣完整保留。
> - **接触与非接完整原生支持**：`start_decard_contact.bat` 和 `start_decard_unified.bat` 均原生支持 T6（`A112`）与 T10（`A133`/`A135`）的接触槽与非接射频区。新增主动接触失联检查与插卡即时蜂鸣反馈，修复厂商 DLL 的大包崩溃边界。
> - **独占诊断通道**：默认专供 Windows VPCD 虚拟读卡器；需要独立 APDU 调试时可显式传入 `-DirectPort <端口>` 开启独占诊断模式。
>
> 统一入口是**单虚拟卡位**，默认接触优先；两张卡同时放置时，使用 `start_decard_rf.bat` 或 `start_decard_unified.bat -Priority RfFirst` 读取非接卡。多个入口共享硬件互斥锁，防止多进程冲突。默认不记录敏感 APDU 载荷。

---

## ⚠️【重中之重 · 运行必读前置条件】必须先安装 VPCD (BixVReader)

> [!CAUTION]
> **绝大多数用户“无法读卡”、“设备管理器看不到读卡器”的原因都是因为跳过了这一步！**  
> 本工具工作在用户态，**必须依赖虚拟读卡器驱动**才能将数据送入 Windows 智能卡子系统。

### 为什么必须安装 VPCD？
Windows 原生的智能卡基础设施（`WinSCard.dll` / `SCardSvr` 服务）**只与注册在系统级的 PC/SC 驱动通信**。国产“免驱 HID”读卡器本身走的是厂商私有 USB HID 报文，Windows 默认只把它当作普通的鼠标键盘类 HID 设备，**智能卡服务完全感知不到它的存在**！

本项目通过用户态脚本与读卡器进行底层通信，再通过标准 TCP 套接字把卡片状态与 APDU 实时送入本地的 **VPCD 虚拟读卡器驱动**，从而向整个 Windows 系统暴露一个标准合规的系统级读卡器（系统内显示为 `Virtual PCD 0`）。

### 安装指引
1. **下载并安装 BixVReader / VPCD**：
   - 推荐使用成熟的开源项目 [vsmartcard - Virtual Smart Card Architecture (BixVReader)](https://github.com/frankmorgner/vsmartcard/releases)。
   - 安装其提供的虚拟智能卡读卡器驱动（Windows 驱动安装包）。
2. **确认驱动已正常就绪**：
   - 打开 Windows **【设备管理器】** $\to$ 展开 **【智能卡读卡器】**，应能看到类似 `Bix Virtual Smart Card Reader` 或 `Virtual PCD` 设备，且状态正常无感叹号。
   - 此时该驱动会在本地后台侦听 `127.0.0.1:35963` 端口，等待我们的 Bridge 脚本连接注入。

---

## 💡 为什么要做这个项目？（捡垃圾者的救赎与华强北避坑指南）

### 1. 核心动力：极致的性价比与大厂工业级做工
智能卡（JavaCard、OpenPGP Card、FIDO2/WebAuthn 硬件安全密钥）在海外通常配合 ACS ACR122U、ACR1252U 等标准 CCID 读卡器使用。但放眼国内市场，现状却非常魔幻：
- **正版原装 CCID 读卡器高昂**：正品 ACS 或飞天 CCID 双界面读卡器价格普遍在 **150 ～ 300+ 元**，对于普通开发者或卡友来说门槛不低。
- **华强北山寨 ACR122U 极其劣质**：电商平台上山寨最多的就是所谓的 ACR122U。内部采用劣质国产单片机软模拟协议，甚至飞线粗制滥造；**射频天线根本没有经过阻抗匹配调谐**，发热惊人、频繁死机。一旦发送稍微长一点的 APDU（如读取 X.509 证书、做 RSA 签名、或者写入大体积 Applet），**必定疯狂掉帧、超时、假死**！
- **海鲜市场（闲鱼/二手）国产“免驱”读卡器白菜价泛滥**：
  国内各地的银行柜台、社保窗口、税务政务大厅等，退役了海量的正规国产读卡器：
  - **飞天诚信 ROCKEY 531 (SCR501)**：二手只要 **~50 元**！
  - **德卡 T6 单界面（纯接触式，PID_A112）**：低至 **~20 元**（比一杯奶茶还便宜）！
  - **德卡 T10 / 德卡 T6 双界面（A112 / A133 / A135）**：只要 **~50 元**！接触插槽 + 13.56MHz 非接射频一应俱全。

### 2. 为什么这些国产“免驱 HID”读卡器是宝藏？
这些二手退役读卡器原本是面向金融、政务领域招标生产的工业级产品：
- 出厂均通过了国家银行卡检测中心（PBOC）或 EMVCo 认证，内部射频滤波、天线抗干扰和 ESD 防护设计扎实。
- 触点采用高厚度镀金物理弹片，寿命达十万次以上；单界面接触版 T6 还自带物理微动开关侦测插拔。
- **只要没买到硬件坏件，且没买到被某些加密专网锁死的深度定制版，它们的用料和硬件稳定性可以全方位吊打华强北山寨货！**

**它们唯一的缺陷就是“免驱”**：厂商为了让政务内网终端免装驱动，设计了一套走 USB HID 的私有报文格式，直接剥夺了标准的 WinSCard / PC/SC 接口，导致 GPG、OpenSC、Passkey、浏览器和 GlobalPlatformPro 根本认不出它们。

**本项目就是为了打破这层私有协议壁垒，让这批白菜价的工业级良心硬件在标准开源生态中彻底复活！**

---

## 💥 翻车事故与完美逆袭：华大 HD-100 的“变砖”与“重生”

在本项目逆向研发早期，曾经有一台小巧漂亮的 **华大 HD-100** 双界面读卡器英勇“牺牲”：
- **翻车教训**：早期华大 HD100 缺乏开发头文件。在摸索私有 HID 协议时对其通信字节进行了全空间盲扫（Fuzzing），直接触发了读卡器内部固件未做鉴权的 Bootloader 擦除逻辑，导致机器变砖无法枚举。
- **绝地重生**：新购华大 HD-100（复合型带密码键盘与液晶屏，`VID_072F&PID_90D5`）到货后，我们改变策略：采用静态反编译结合官方安全协议栈（`SSSE32.dll`），彻底杜绝裸扫。
- **核心难点攻克**：
  1. **密码键盘安全设计解密**：该设备的数字键盘属于金融级 PIN Pad，日常闲置时硬件 MCU 完全锁定并禁止上报按键（杜绝系统木马盗取按键）；只有上位机下发 PIN 输入会话指令（`ICC_GetInputPass`）时才会开启安全键盘采样。
  2. **NXP 与复旦微双版本全兼容 & 驱动单字节补丁突破**：市面上流通的华大 HD-100 存在早期 NXP 方案与新版复旦微 (FM175xx) 方案两代硬件。原厂动态库 `SSSE32.dll` 在处理复旦微硬件的非接多帧长响应时，因内部递归接收函数（RVA `0x1000AFF0`）在 `0xEA6B` 处的条件跳转判断缺陷（`JL` 误判导致未填入实际接收字节数并返回错误码 `-2`），会导致读卡器无限断联重试。我们通过逆向精确定位该缺陷，采用单字节二进制补丁（`0xEA6B`: `0x7C` $\to$ `0x75` / `JL` $\to$ `JNE`），彻底根治了多帧长响应拼包缺陷。目前无论较早的 NXP 方案还是新的复旦微方案，均能稳定接收数百字节的多帧长响应！
  3. **FIDO2 / WebAuthn 会话上下文保持**：彻底移除了空闲探卡时发送非必要 APDU（如 `00 A4 04 00 00`）的逻辑，避免在 JavaCard 上重置选中的 FIDO2 Applet（防止 Windows Hello 降级跳过 PIN 输入），保证 FIDO2、PIV、OpenPGP 的多步骤认证流程完好顺畅。

---

## 🔮 下一步路线图 (Roadmap)

1. **更多国产“免驱”型号适配**：欢迎卡友提 Issue 或寄送退役样机共同折腾！
2. **PIN Pad 硬件直输入模式扩展**：继续探索 PC/SC Part 10 原生 `FEATURE_VERIFY_PIN_DIRECT` 控制码与华大 PIN Pad 的无缝打通。

---

## 📋 硬件支持与启动入口指南

项目根目录下提供了针对不同场景的批处理脚本，各自特点与用途如下：

| 启动脚本 (BAT) | 适用硬件型号 | 工作模式 | 核心特点与使用场景 |
| :--- | :--- | :--- | :--- |
| **`start_huada_unified.bat`** | 华大 HD-100 (`VID_072F&PID_90D5`) | 双界面自适应选择 | 默认接触优先，`-Priority RfFirst` 非接优先；通配 NXP 与复旦微 FM175xx 方案，内置长数据多帧拼包与非侵入式会话保持。 |
| **`start_huada_rf.bat`** | 华大 HD-100 非接触射频区 | 固定非接触射频位 | 专用于挥非接卡/安全密钥，自动 ATS 转系统标准 ATR，完美兼容 FIDO2、PIV 与 WebAuthn。 |
| **`start_huada_contact.bat`** | 华大 HD-100 接触式卡槽 | 固定接触 CPU 卡槽 | 专用于插卡，物理微动开关自动检测插拔状态，支持 T=0/T=1 CPU 卡与社保/银行芯片卡。 |
| **`start_watchdata_unified.bat`** | 握奇 W2160 (W8298) / W5181 Plus | USB 接触+非接 自动选择 | 默认接触优先，`-Priority RfFirst` 非接优先；纯 Python 65 字节 HID 驱动，无需外部 DLL。已通过 FIDO2、PIV、OpenPGP、PBOC 验证。 |
| **`start_watchdata_rf.bat`** | 握奇 W2160 (W8298) / W5181 Plus 非接区 | USB 固定非接触位 (`NAD=0x15`) | 独立非接触射频区，支持长响应自动多包拼接与 FIDO2 CTAP2 认证。 |
| **`start_watchdata_contact.bat`** | 握奇 W2160 (W8298) / W5181 Plus 接触槽 | USB 固定接触位 (`NAD=0x12`) | 独立用户接触式卡槽，安全过滤内部 SAM。 |
| **`start_w2160_serial.bat`** | 握奇 W2160 串口版 (CRW-Xs) | 串口纯非接中继 (`9600 8E1`) | **⚠️ 特殊设备**：老款纯非接 RS-232 串口读卡器，自动列出 COM 口供选择；详见 [串口版说明](W2160（CRW-Xs）/SERIAL_README.md)。 |
| **`start_decard_unified.bat`** | 德卡 T6 (`PID_A112`) / T10 (`PID_A133`/`A135`) | 单卡位自动选择 | 自动识别机型并自适应切换 `dcic32.dll` (T6 A112 原生引擎) 与 `dcrf32.dll` (T10 A133/A135 降级引擎)；默认接触优先，`-Priority RfFirst` 非接优先。实测 A112/A133/A135 全系列双卡在位与独立入口。 |
| **`start_decard_rf.bat`** | 德卡 T6 / T10 (A112/A133/A135) 非接区 | 固定非接触 RF | ISO 14443-A/ISO-DEP。保留 400ms 慢启动保护，稳定后约 200ms 轮询并主动通知 Windows；已实测标准 CPU 卡及 YubiKey 5 NFC。独占整台设备的 SDK 访问。 |
| **`start_decard_contact.bat`** | 德卡 T6 (A112) / T10 (A133/A135) 接触槽 | 固定接触位 | T6 原生 `dcic32.dll` 接触座与 T10 `0x0C` 接触槽通用；A112/A133/A135 T=0 实卡读取、复位和失联通知通过；T=1 仅离线验证。T10 单次 T=0 TPDU 上限 250 字节，超限返回 `6700`。 |
| **`start_feitian_scr501.bat`** | 飞天 SCR501<br>(ROCKEY 531) | 专用非接触中继<br>(`RK501API.dll`) | **⚠️ 明确说明：目前仅实现非接触（挥卡）界面可用！**<br>基于飞天诚信官方动态库，内置防掉卡去抖看门狗，稳定读取各类非接 CPU 卡、JavaCard 与 FIDO Key。 |
| **`test_gp.bat`** | 通用诊断 | GlobalPlatformPro | 自动探测并调用 `gp.exe` 连通 `Virtual PCD`，打印卡片内的安全域、AID 与 Applet 列表，一键测试链路是否畅通。 |


---

## 🚀 极速上手三步法

### 第一步：启动虚拟读卡器
确保已安装并配置好 **BixVReader / VPCD**，设备管理器中已出现虚拟智能卡读卡器。

### 第二步：运行对应读卡器脚本
- 如果你使用的是**华大 HD-100（带屏带密码键盘）**：
  双击 **`start_huada_unified.bat`** 自动选择卡位；固定插卡使用 **`start_huada_contact.bat`**，固定挥卡使用 **`start_huada_rf.bat`**。
- 如果你使用的是**握奇 USB 读卡器（四合一版 W2160 代号 W8298 / W5181 Plus）**：
  双击 **`start_watchdata_unified.bat`** 自动选择卡位；固定插卡使用 **`start_watchdata_contact.bat`**，固定挥卡使用 **`start_watchdata_rf.bat`**。
- 如果你使用的是**握奇 W2160 串口版（老款纯非接 CRW-Xs）**：
  双击 **`start_w2160_serial.bat`**，根据提示选择对应的 COM 端口即可。
- 如果你使用的是**德卡 T6（`PID_A112`，原生 `dcic32.dll`）或 T10（`PID_A133` 标准版 / `PID_A135` 磁条版，基于 `dcrf32.dll`）**：
  双击 **`start_decard_unified.bat`** 自动选择卡位并自适应后端驱动；固定插卡使用 **`start_decard_contact.bat`**，固定非接使用 **`start_decard_rf.bat`**。
- 如果你使用的是**飞天 SCR501（挥非接卡）**：
  直接双击 **`start_feitian_scr501.bat`**。

德卡入口打印 `Connected medium=...` 后，表示物理卡已激活并连接到 VPCD；再用上层软件验证 APDU：
```text
DeCard mode=Auto, priority=Contact, VPCD=127.0.0.1:35963
Connected medium=Contact ATR=...
```

### 第三步：开始使用！
应用能否使用还取决于卡内 Applet、APDU 长度和上层中间件。以下是用途示例；本轮验收只覆盖报告列出的只读交互：
- **OpenPGP 状态查看**：
  ```cmd
  gpg --card-status
  ```
- **FIDO2 / Passkey 测试**：
  是否可用取决于系统、浏览器、卡内应用及 CTAP/NFC 接入支持；不能仅凭 PC/SC 桥接成功推断 WebAuthn 可用。本轮未验证该功能。
- **GlobalPlatformPro 卡片管理**：
  直接双击根目录下的 `test_gp.bat`，或在命令行中运行：
  ```cmd
  gp.exe -r "Virtual PCD" -l -v
  ```

---

## 🛒 二手海鲜市场捡垃圾避坑指南

为了防止大家白花冤枉钱，在闲鱼等二手平台上购买时，请特别注意以下几点：

1. **绝对不要买“深度定制版 / 专网加密锁死版”**：
   - 某些标有“XX省公安专网”、“XX税控专用终端”、“XX银行特种机”且卖家声明“需要插加密狗或专网认证”的机器不要买！这些设备可能在单片机固件层面锁死了非公开通信密钥，甚至修改了 USB VID/PID。
2. **认准通用的公版型号**：
   - **北京握奇 (Watchdata)**：
     - 四合一 USB 版认准 **`W2160`**（内部固件代号 **`W8298`**，`VID_163C&PID_0A1F`，带接触插槽与条码扫码窗）或 **`W5181 Plus`**（`VID_163C&PID_0A28`）。
     - 纯非接串口版认准 **`W2160 / CRW-Xs`**（带 DB9 串口线与 DC 9V 供电插头，纯非接触）。
   - **德卡 (DeCard)**：认准 `T6`、`T6-URM`（USB 免驱版，`PID_A112`，原生使用 `dcic32.dll`）、`T10`（USB 双界面标准版 `PID_A133` / 磁条复合版 `PID_A135`，使用 `dcrf32.dll`）。
   - **飞天诚信 (Feitian)**：认准 `SCR501`、`ROCKEY 531`（PID 通常为 `0603`，HID 免驱版）。
3. **留意硬件成色与配件**：
   - 德卡 T6 纯接触版的卡座如果弹片被异物捅变形会导致接触不良；
   - 双界面版请确认非接射频天线板未被外力折损；
   - 尽量选择带原装 USB 屏蔽磁环数据线的成色。

---

## 🛠️ 常见问题 (FAQ)

### Q1: 运行脚本时提示 `dcic32.dll` 或 `RK501API.dll` 无法加载（BadImageFormatException）？
**A**: 国产硬件厂商的历史 SDK 动态库均为 **32 位 (x86)** 架构。本项目的 BAT 脚本与 PowerShell 脚本均内置了检测与自适应机制，若当前位于 64 位环境，会自动调用 `SysWOW64\WindowsPowerShell` 重新以 32 位宿主启动，无需手动修改系统环境。（注：握奇 USB 系列驱动为纯 Python 原生直驱，无此依赖限制）。

### Q2: 运行 `gpg --card-status` 报错 `scdaemon: card is already checked out / No such device`？
**A**: Windows 下由于 `CertPropSvc`（证书传播服务）或浏览器可能同时访问智能卡，而 GnuPG 默认以独占（Exclusive）方式打开 PC/SC。
**解决方法**：在 `%APPDATA%\gnupg\scdaemon.conf` 中追加一行配置：
```text
pcsc-shared
```
保存后执行 `gpgconf --kill scdaemon` 重启守护进程即可。

### Q3: 为什么 Windows Passkey 认证时弹窗提示 `未知的设备状态(代码: 2、 9、 0x80100022)`？
**A**: 这是由于早期脚本在响应系统的 Warm Reset 时向 TCP 流塞入了多余的字节导致数据脱节。请确保拉取本项目最新版本的 `start_decard_unified.bat`，目前已彻底修复该问题。

---

## 📁 仓库文件结构

```
SmartCard-Bridges/
│
├── README.md                      # 项目说明文档
├── LICENSE                        # MIT 开源许可证
│
├── start_huada_unified.bat        # 🔥 华大 HD-100 接触+非接 二合一智能桥接
├── start_huada_rf.bat             # 华大 HD-100 非接触 (RF) 独立桥接
├── start_huada_contact.bat        # 华大 HD-100 接触式卡槽独立桥接
│
├── start_watchdata_unified.bat    # 🔥 握奇 W2160(W8298)/W5181 Plus 接触+非接 自动桥接
├── start_watchdata_rf.bat         # 握奇 USB 系列非接触 (RF) 独立桥接
├── start_watchdata_contact.bat    # 握奇 USB 系列接触式卡槽独立桥接
├── start_w2160_serial.bat         # 握奇 W2160 老款串口纯非接专用桥接 (CRW-Xs)
│
├── start_decard_unified.bat       # 🔥 德卡 T6/T10 接触+非接 二合一智能桥接
├── start_decard_rf.bat            # 德卡双界面 / T10 非接触 (RF) 独立桥接
├── start_decard_contact.bat       # 德卡 T6 / T10 接触式卡座独立桥接
├── start_feitian_scr501.bat       # 飞天诚信 SCR501 (ROCKEY 531) 专用桥接
├── test_gp.bat                    # GlobalPlatformPro 连通性快速验证
│
├── watchdata_usb/                 # 握奇 USB 系列纯 Python 直驱驱动模块
│   ├── bridge.py                  # VPCD 虚拟读卡器协议中继器
│   ├── card.py                    # 接触与非接触智能卡抽象
│   ├── protocol.py                # CRW-X 协议帧封装与解包 (65 字节 HID)
│   ├── reader.py                  # 异步 Overlapped I/O 设备读写器
│   └── transport.py               # HID 传输层与重叠 I/O 封装
│
├── W2160（CRW-Xs）/               # 握奇 W2160 串口纯非接专区
│   ├── SERIAL_README.md           # 串口版专属使用说明与避坑指引
│   ├── serial_bridge.py           # 串口 VPCD 桥接中继实现
│   ├── serial_reader.py           # 串口 CRW-X 读卡器状态机
│   └── serial_transport.py        # Windows RS-232 串口驱动
│
├── for MAC/                       # macOS 跨平台驱动与测试套件
│   ├── README.md                  # macOS 安装与使用指南
│   ├── start_decard_mac.sh        # macOS 德卡双界面桥接
│   ├── start_decard_contact_mac.sh # macOS 德卡接触槽桥接
│   ├── start_feitian_mac.sh       # macOS 飞天 SCR501 桥接
│   └── scripts/                   # macOS Python 驱动与中继脚本
│
├── drivers/                       # 提取的官方驱动原生 DLL 与 C 语言头文件
│   ├── SSSE32.dll                 # 华大 HD-100 原生动态库 (已打入 0xEA6B 多帧接收补丁, x86)
│   ├── dcic32.dll                 # 德卡接触式 IC 动态库 (x86)
│   ├── dcic32.h
│   ├── dcic32.lib
│   ├── dcrf32.dll                 # 德卡非接触 RF 动态库 (x86)
│   ├── dcrf32.h
│   ├── dcrfrd.dll                 # 德卡非接触 RF 动态库 (x64)
│   └── RK501API.dll               # 飞天诚信 SCR501 动态库 (x86)
│
├── scripts/                       # 核心业务逻辑脚本 (PowerShell / C# / Python)
│   ├── HuadaBridge.cs             # 华大 HD-100 C# 核心桥接与协议中继器
│   ├── huada_unified_bridge.ps1   # 华大 HD-100 二合一中继入口
│   ├── huada_rf_bridge.ps1        # 华大 HD-100 非接独立中继
│   ├── huada_contact_bridge.ps1   # 华大 HD-100 接触独立中继
│   ├── DecardBridge.cs            # 德卡 T6/T10 C# 核心桥接与协议中继器
│   ├── decard_unified_bridge.ps1  # 德卡接触/非接 二合一中继逻辑
│   ├── decard_rf_bridge.ps1       # 德卡非接独立中继逻辑
│   ├── decard_contact_bridge.ps1  # 德卡接触式独立中继逻辑 (T6 / T10 通用)
│   ├── watchdata_unified_bridge.ps1 # 握奇 USB 二合一中继入口
│   ├── watchdata_rf_bridge.ps1    # 握奇 USB 非接独立中继
│   ├── watchdata_contact_bridge.ps1 # 握奇 USB 接触独立中继
│   ├── watchdata_usb_bridge.py    # 握奇 USB Python 核心中继
│   ├── w2160_serial_bridge.ps1    # 握奇 W2160 串口版中继入口
│   └── feitian_scr501_bridge.ps1  # 飞天 SCR501 独立中继逻辑
│
└── tools/                         # 协议分析逆向与辅助工具
    ├── DeCardReader.cs            # 德卡 C# 完整 P/Invoke 接口封装参考
    ├── dump_cmd_table.py          # PE 导出函数与指令分发器反编译工具
    └── gp.exe                     # GlobalPlatformPro 预编译工具
```

---

## 📄 开源许可证

本项目核心源码以 [MIT 许可证](LICENSE) 开源，欢迎社区卡友共同完善与提交 PR！  
所包含的官方驱动动态库（`SSSE32.dll`、`dcic32.dll`、`RK501API.dll` 等）版权归各自原厂商所有。本项目仅做技术研究与协议中继桥接之用。
