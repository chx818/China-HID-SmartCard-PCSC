# China-HID-SmartCard-PCSC (中国免驱 HID 智能卡读卡器 PC/SC 桥接驱动套件)

> **Universal Windows PC/SC Bridges for Chinese Proprietary "Driverless" USB-HID Smart Card Readers**  
> 专为国产“免驱 HID”智能卡读卡器打造的系统级 PC/SC 虚拟驱动映射工具箱。  
> 支持**德卡 (DeCard T6 / T10)**、**飞天诚信 (Feitian SCR501 / ROCKEY 531)** 等设备，将私有 HID 协议秒变 Windows 标准系统智能卡读卡器！


> **2026-10-04 德卡重构更新**：三个德卡入口已统一收敛至高性能底层引擎 `scripts/DecardBridge.cs`，彻底修复重复发送 APDU、T=0 数据改写、RF 帧误解析和 TCP 半包阻塞等问题；同时完整保留接触式与非接触式的主动即时移卡与重新插卡感知。
>
> 统一入口是**单虚拟卡位**，默认接触优先；两张卡同时放置时，使用 `start_decard_rf.bat` 或 `start_decard_unified.bat -Priority RfFirst` 读取非接卡。三个入口共享一台设备的互斥锁，不能同时运行。RF 保留原来的约 400ms 空闲 I-block 探测和 40ms 失败复查；确认失联后主动通知 Windows。探针与完整业务交换串行，不在 APDU/WTX/分块过程中插入。默认不记录 APDU 载荷。

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
  - **德卡 T6 单界面（纯接触式）**：低至 **~20 元**（比一杯奶茶还便宜）！
  - **德卡 T10 / 德卡 T6 双界面**：只要 **~50 元**！接触插槽 + 13.56MHz 非接射频一应俱全。

### 2. 为什么这些国产“免驱 HID”读卡器是宝藏？
这些二手退役读卡器原本是面向金融、政务领域招标生产的工业级产品：
- 出厂均通过了国家银行卡检测中心（PBOC）或 EMVCo 认证，内部射频滤波、天线抗干扰和 ESD 防护设计扎实。
- 触点采用高厚度镀金物理弹片，寿命达十万次以上；单界面接触版 T6 还自带物理微动开关侦测插拔。
- **只要没买到硬件坏件，且没买到被某些加密专网锁死的深度定制版，它们的用料和硬件稳定性可以全方位吊打华强北山寨货！**

**它们唯一的缺陷就是“免驱”**：厂商为了让政务内网终端免装驱动，设计了一套走 USB HID 的私有报文格式，直接剥夺了标准的 WinSCard / PC/SC 接口，导致 GPG、OpenSC、Passkey、浏览器和 GlobalPlatformPro 根本认不出它们。

**本项目就是为了打破这层私有协议壁垒，让这批白菜价的工业级良心硬件在标准开源生态中彻底复活！**

---

## 💥 翻车事故实录：为什么华大 HD100 搞坏了？

在本项目逆向研发过程中，曾经有一台小巧漂亮的 **华大 HD-100** 双界面读卡器英勇“牺牲”：
- **事故原因**：华大 HD100 在公开渠道没有任何 SDK 与开发头文件。在逆向摸索其私有 HID 协议时，作者对其通信控制字节进行了全空间盲扫（Fuzzing / Sweep）。
- **悲剧发生**：不幸的是，该读卡器固件没有对底层特权指令做身份校验，盲扫指令直接触发了单片机内部的 Bootloader / ISP 固件擦除固化逻辑，导致读卡器内部固件损坏直接变砖，插入 USB 不再枚举识别。
- **最新进展**：**大家不要慌，作者已经重新自费下单了新的华大 HD100，目前已经在快递路上！** 等新机器到货后，将使用更安全精细的静态反编译手段继续逆向，届时也会将 HD100 加入支持阵营！

---

## 🔮 下一步路线图 (Roadmap)

1. **握奇数据 (Watchdata) W2160 单界面（纯非接触挥卡）版适配**：
   - 握奇 W2160 在二手市场货源极其庞大且价格更低（白菜价），外观小巧轻薄。
   - 作者下一步将重点攻克 W2160 的私有 HID 通信协议，给卡友们提供多一个超低成本挥卡选择！
2. **华大 HD100 双界面安全驱动**：待新机抵达后重新验证并入库。

---

## 📋 硬件支持与启动入口指南

项目根目录下提供了针对不同场景的批处理脚本，各自特点与用途如下：

| 启动脚本 (BAT) | 适用硬件型号 | 工作模式 | 核心特点与使用场景 |
| :--- | :--- | :--- | :--- |
| **`start_decard_unified.bat`** | 德卡 T6 双界面（本轮实测）<br>T10/单界面需另行验收 | 单卡位自动选择 | 默认接触优先，`-Priority RfFirst` 非接优先；只在建立新会话时选择卡位。当前验收覆盖只读 APDU、复位、分块及连接恢复。 |
| **`start_decard_rf.bat`** | 德卡 T6 非接区（本轮实测） | 固定非接触 RF | ISO 14443-A/ISO-DEP。空闲约 400ms 检测移卡并主动通知 Windows；不支持 Type B、10 字节 UID 或存储卡伪 APDU。独占整台 T6 的 SDK 访问。 |
| **`start_decard_contact.bat`** | 德卡 T6 接触槽（本轮实测） | 固定接触位 | 接触状态约 250ms 轮询。本轮实测 T=0；T=1 仅离线测试。T=0 保留原有 SDK 命令映射和扩展命令转交行为。密钥生成及长耗时业务未验收。 |
| **`start_feitian_scr501.bat`** | 飞天 SCR501<br>(ROCKEY 531) | 专用非接触中继<br>(`RK501API.dll`) | **⚠️ 明确说明：目前仅实现非接触（挥卡）界面可用！**<br>基于飞天诚信官方动态库，内置防掉卡去抖看门狗，稳定读取各类非接 CPU 卡、JavaCard 与 FIDO Key。 |
| **`test_gp.bat`** | 通用诊断 | GlobalPlatformPro | 自动探测并调用 `gp.exe` 连通 `Virtual PCD`，打印卡片内的安全域、AID 与 Applet 列表，一键测试链路是否畅通。 |

---

## 🚀 极速上手三步法

### 第一步：启动虚拟读卡器
确保已安装并配置好 **BixVReader / VPCD**，设备管理器中已出现虚拟智能卡读卡器。

### 第二步：运行对应读卡器脚本
- 如果你使用的是**德卡 T6 双界面、德卡 T10 或单界面 T6**：
  直接双击 **`start_decard_unified.bat`** 即可。
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
   - **德卡**：认准 `T6`、`T6-URM`（USB 免驱版）、`T10`（USB 双界面）。
   - **飞天诚信**：认准 `SCR501`、`ROCKEY 531`（PID 通常为 `0603`，HID 免驱版）。
3. **留意硬件成色与配件**：
   - 德卡 T6 纯接触版的卡座如果弹片被异物捅变形会导致接触不良；
   - 双界面版请确认非接射频天线板未被外力折损；
   - 尽量选择带原装 USB 屏蔽磁环数据线的成色。

---

## 🛠️ 常见问题 (FAQ)

### Q1: 运行脚本时提示 `dcic32.dll` 或 `RK501API.dll` 无法加载（BadImageFormatException）？
**A**: 国产硬件厂商的历史 SDK 动态库均为 **32 位 (x86)** 架构。本项目的 BAT 脚本与 PowerShell 脚本均内置了检测与自适应机制，若当前位于 64 位环境，会自动调用 `SysWOW64\WindowsPowerShell` 重新以 32 位宿主启动，无需手动修改系统环境。

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
├── start_decard_unified.bat       # 🔥 德卡 T6/T10 接触+非接 二合一智能桥接
├── start_decard_rf.bat            # 德卡双界面 / T10 非接触 (RF) 独立桥接
├── start_decard_contact.bat       # 德卡 T6 / T10 接触式卡座独立桥接
├── start_feitian_scr501.bat       # 飞天诚信 SCR501 (ROCKEY 531) 专用桥接
├── test_gp.bat                    # GlobalPlatformPro 连通性快速验证
│
├── drivers/                       # 提取的官方驱动原生 DLL 与 C 语言头文件
│   ├── dcic32.dll                 # 德卡接触式 IC 动态库 (x86)
│   ├── dcic32.h
│   ├── dcic32.lib
│   ├── dcrf32.dll                 # 德卡非接触 RF 动态库 (x86)
│   ├── dcrf32.h
│   ├── dcrfrd.dll                 # 德卡非接触 RF 动态库 (x64)
│   └── RK501API.dll               # 飞天诚信 SCR501 动态库 (x86)
│
├── scripts/                       # 核心业务逻辑 PowerShell 脚本
│   ├── decard_unified_bridge.ps1  # 德卡接触/非接 二合一中继逻辑
│   ├── decard_rf_bridge.ps1       # 德卡非接独立中继逻辑
│   ├── decard_contact_bridge.ps1  # 德卡接触式独立中继逻辑 (T6 / T10 通用)
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
所包含的官方驱动动态库（`dcic32.dll`、`RK501API.dll` 等）版权归各自原厂商所有。本项目仅做技术研究与协议中继桥接之用。
