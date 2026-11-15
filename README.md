# RC Plus 无线模拟器手柄 🎮

把 **DJI RC Plus** 遥控器变成 Windows 上的**无线 Xbox 360 手柄**，专供穿越机模拟器
（Uncrashed / Liftoff / Velocidrone…）。不插线、走 WiFi adb，遥控器屏幕上还有一块
实时 FPV 风格仪表，点桌面图标就能拉起模拟器。

> 实测：无线打杆链路 RTT **2ms**，连续飞行数小时零掉线。本文末尾有延迟攻坚的完整数据。

## 为什么又一个（Why another）

GitHub 上已经有几个 RC Plus 接 PC 的项目
（[leo02002/DJI-RC-Plus-RM700-PC-Controller](https://github.com/leo02002/DJI-RC-Plus-RM700-PC-Controller)、
[Liancycling/DJIRCPlus-Bridge](https://github.com/Liancycling/DJIRCPlus-Bridge_RCPlus-)、
RC Plus 2 侧还有 [IamEmery 的协议逆向](https://github.com/IamEmery/DJI-RC-Plus-2-TKPL2-Native-Gamepad-Bridge-for-Gaming)），
思路都是 USB 有线。本项目不是重复造轮子，差异化在四点：

1. **无线，不插线** —— 全网唯一的 WiFi adb 方案，插线优先但拔线照飞。
2. **WiFi 省电休眠的发现与压制** —— 无线上最大的坑是 Android 省电（PS-Poll）让射频
   只在 beacon 窗口醒来：实测 ping 平均 75ms、事件流断档最长 **1.52 秒**（手感就是
   "打杆不及时、摇杆老是卡一下"）。没有 root 关不掉省电，但**每秒 30 个空 UDP 包**
   就能把链路压到 **2ms**（0.7KB/s 代价）。这组实测数据全网独一份，
   方法见 [references/latency-wifi.md](references/latency-wifi.md)。
3. **遥控器屏幕实时仪表** —— 双杆圆点、四通道条、拨轮、C1~C6、五向键、LB/Back/RB
   键灯，全部实时显示；点遥控器桌面上的 Uncrashed 图标 = 打开仪表 + 自动拉起模拟器。
   没有第二家做了这个。
4. **按"天天在用"做的工程化** —— 常驻自愈（掉线自动重连、事件流"半死"心跳看门狗）、
   R3 关游戏的退出码协议（关了不再自动弹出）、息屏自动唤醒、防安卓模拟器抢占
   adb 端口、电池保护。不是"能跑的脚本"，是陪伴每次飞行的系统。

```
RC Plus (Android evdev) ──adb(WiFi/USB)──> rcplus_sim.py ──ViGEm──> 虚拟 X360 手柄 ──> 模拟器
                                               │
                                               └─ dashboard.py :8123 ──> 遥控器屏幕仪表页
                                                                          (点图标启动游戏)
```

## 特性

- **无线 2ms 链路**：自动压制 Android WiFi 省电休眠（这是无线上最大的坑，详见下文）
- **常驻模式**：`launcher.py --auto` 开机自启，遥控器随时上线随时接上；
  点遥控器上的 Uncrashed 图标 → 仪表打开 + 模拟器自动启动
- **遥控器屏幕仪表**：双杆圆点、油门/偏航/横滚/俯仰通道条、双拨轮、C1~C6、
  五向键十字、LB/Back/RB 键灯，全部实时
- **第三个拨轮 + 飞行模式拨杆**（彩蛋）：右拨轮下方那个不回中的轮子、
  左肩下方 F/S/N 三档拨杆，**都不在 evdev 里**，只在 DUML 私有协议里，
  本项目把它们读出来了 —— 详见下文
- **全输入映射**：双摇杆、双拨轮（右拨轮=游戏音量）、C1~C6、五向键（菜单模式可当
  鼠标选地图）、肩键、Back、R3 长按关游戏
- **油门两种手感**：绝对值（杆在哪油门在哪，适合不回中改装杆）/ 锁存（穿越机手感），Back 一键切换
- **电池保护**：遥控器 <25% 警告、<10% 自动断开
- **断线自愈**：掉线自动重连、事件流"半死"自动检测重连、屏幕休眠自动唤醒

## 硬件支持

| 设备 | 状态 |
|---|---|
| DJI RC Plus | ✅ 完整支持（作者在用） |
| DJI RC / RC Pro / RC 2 | ⚠️ 未验证，evdev 映射大概率不同，欢迎反馈 |

## 安装

### 1. 依赖

- Windows 10/11 + Python 3.10+
- [ViGEmBus 驱动](https://vigem.org)（虚拟手柄内核驱动，必装）
- `pip install vgamepad`
- [adb platform-tools](https://developer.android.com/tools/releases/platform-tools)，
  默认路径 `C:\tools\platform-tools\adb.exe`（可配置）

### 2. 开启遥控器无线调试

插 USB 数据线，执行一次（IP 换成遥控器连 WiFi 后的地址，可在遥控器设置里看）：

```sh
adb tcpip 5555
```

之后拔线，走 WiFi。遥控器息屏会停止上报，脚本会自动处理。

### 3. 配置

在 `scripts/` 下建 `rcplus_config.json`（可选，但强烈推荐，不用改代码）：

```json
{
  "adb": "C:\\tools\\platform-tools\\adb.exe",
  "input_dev": "/dev/input/event6",
  "game": "D:\\Games\\Uncrashed\\Uncrashed.exe",
  "game_proc": "Uncrashed-Win64-Shipping.exe"
}
```

### 4. 启动

```sh
cd scripts
python launcher.py --auto        # 有线优先，没线自动转无线
```

游戏内绑定（Uncrashed 为例）：

1. Controls → 设备选 `XInput Controller #1`
2. Stick Calibration：两杆推满四角再回中
3. Throttle=左摇杆Y · Yaw=左摇杆X · Roll=右摇杆X · Pitch=右摇杆Y
4. Deadzone 设 0；Gamepad Throttle 关；**SDL 轴 2/4 是扳机（恒 -1），别绑**

### 5. 开机自启（可选）

把 [`assets/RCPlus_Auto.bat`](assets/RCPlus_Auto.bat) 改好路径，放进
`Win+R` → `shell:startup` 打开的文件夹。

### 6. 遥控器屏幕仪表（可选）

遥控器 Firefox 打开 `http://<电脑IP>:8123` → 菜单 → **添加到主屏幕**。
以后点这个图标 = 打开仪表 + 自动启动模拟器。
想要真 APP（Uncrashed 图标）：见 [`references/apk-build.md`](references/apk-build.md)。

## 操作速查

| 操作 | 功能 |
|---|---|
| R3（按住 0.5s） | 关游戏，手柄转待命（点图标随时再开） |
| Back | 切换 绝对值/锁存 油门 |
| 右拨轮 | 调游戏音量（自动记住） |
| 左拨轮左拨一下 | 重置（拉满 RT） |
| 五向键直接推 | 移动系统鼠标（选地图不用进任何模式） |
| 五向键中间长按 0.8s | 轮换模式：关→鼠标→摇杆→方向键 |

## 延迟攻坚：WiFi 省电休眠（本项目最大的坑）

无线上手最大的问题不是 adb，而是 **Android 的 WiFi 省电（PS-Poll）**：
射频只在 beacon 窗口醒来收包，实测 ping 平均 53~75ms、事件流断档最长 **1.52 秒**——
手感就是"打杆不及时、摇杆老是卡一下"。

没有 root 关不掉省电（`iw set power_save off` 报 `Operation not permitted`），
但**持续的小流量能让驱动保持唤醒**：

| 注入流量 | ping 平均 | ping 最长 | 事件流最长断档 |
|---|---|---|---|
| 无 | 75ms | 195ms | 1524ms |
| 30 包/秒 (24B UDP) | **2ms** | 5ms | — |
| 50 包/秒 | 2ms | 5ms | — |
| 100 包/秒 | 3ms | 7ms | — |

`rcplus_sim.py` 内置 `RadioKeepAlive`（无线模式自动开，50 包/秒，0.7KB/s）。
代价忽略不计，效果立竿见影——作者实测"打杆都很及时，破了之前一直没做到的记录"。

完整测量方法与踩坑记录：[`references/latency-wifi.md`](references/latency-wifi.md)

## 彩蛋：evdev 看不到的两个输入

遥控器上有两个输入**在 `getevent` 里完全找不到**，但一直在 DUML 私有协议里正常上报。
它们和摇杆、拨轮**在同一个状态包**（`0x06/0xAE`，17 字节，约 10Hz）里。

### 1) 右拨轮下面那个「不回中的轮子」— byte 4

遥控器其实有三个轮子。前两个在 evdev 里（`ABS_Z` / `ABS_RZ`，自回中）；
第三个在右拨轮正下方，**不回中**，内核根本没给它注册轴（event6 连 `EV_REL` 都没声明）。

```
0x00        静止
0x82 / 0xC2 一档（方向由 bit6 决定）
0x84 / 0xC4 二档
0x86 / 0xC6 三档 …最多五档
```

### 2) F/S/N 三档飞行模式拨杆 — byte 2

左肩下方那个三档拨杆。**位置型**，拨到哪停在哪，静止 25 秒零跳变：

| byte 2 | 档位 |
|---|---|
| `0x02` | **F** |
| `0x00` | **S** |
| `0x01` | **N** |

（映射经实机确认。拨动时会**路过 S**，看到 `F→S→N` 中间态是正常的。）

### 怎么读

**不需要接线、不需要拆机，也不需要飞机在线。**
`adb forward tcp:40007 tcp:40007` 打通隧道就能读，静止 9.7 包/秒、
拨动时设备会立刻补发（最短 20ms）。

仪表页上的位置与实机一一对应：
右拨轮下方显示 `滚轮 ◀ ▶`（拨动时箭头亮 + 档位），
左拨轮下方显示 `模式 F S N`（当前档位常亮）。

> 两者目前**只显示、不参与手柄输出**。完整协议解析、踩坑记录、
> 以及真要接的话几种映射方案：[`references/duml-wheel.md`](references/duml-wheel.md)

## 故障排查

见 [`references/troubleshooting.md`](references/troubleshooting.md)。速查：

```sh
ping -n 20 <遥控器IP>     # 平均 2ms=链路好；50ms+=省电没压住，重启 launcher.py --auto
```

## 目录结构

```
rcplus-wireless-sim/
├── SKILL.md                 # AI agent 操作手册（WorkBuddy Skill 格式）
├── scripts/                 # 运行代码
│   ├── launcher.py          # 常驻入口 / 菜单
│   ├── rcplus_sim.py        # 桥接主体（读事件→虚拟手柄→仪表数据）
│   ├── rcplus_bridge.py     # 事件解析 / 标定 CONFIG
│   ├── dashboard.py         # 遥控器屏幕仪表 (HTTP :8123)
│   ├── win_key.py           # SendInput 鼠标/键盘
│   ├── probe_radio.py       # WiFi 省电对照实验
│   ├── probe_latency.py     # 延迟/事件流测量
│   └── duml/                # evdev 看不到的输入（DUML 私有协议）
│       ├── duml_wheel.py    #   读取模块：滚轮 + 档位，自动重连 + 心跳
│       ├── wheel_live.py    #   实时监听滚轮（取证）
│       ├── capture_wheel.py #   录一段再统计字节变化（排查）
│       ├── duml_dump.py     #   逐列找"会停住"的字段 ← 找位置型输入用它
│       ├── duml_frames.py   #   录全部报文类型逐字节分析
│       ├── duml_inventory.py#   清点协议上有哪些报文
│       └── duml_probe.py    #   协议探针 / 轴解码
├── references/              # 硬件映射 / DUML 隐藏输入 / 延迟攻坚 / 排障 / APK 构建
└── assets/
    ├── RCPlus_Auto.bat      # 开机自启模板
    └── apk_build/           # 遥控器桌面图标 APK 源码
```

## 致谢与依赖

- [ViGEm](https://vigem.org)（虚拟手柄内核驱动）与 [vgamepad](https://github.com/felsokva/vgamepad)
- Android platform-tools (adb)

## License

MIT — 随便用，商用自担风险。

## 免责声明

本项目与 DJI 无关。改遥控器输入映射、关闭省电相关操作均通过 adb 调试通道完成，
不修改固件；但请自行评估风险。别在真机飞行时玩模拟器。
