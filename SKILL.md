---
name: rcplus-wireless-sim
description: Turn a DJI RC Plus remote controller into a wireless Xbox 360 gamepad for FPV simulators (Uncrashed, Liftoff, Velocidrone) on Windows, over adb-over-WiFi. Use when the user mentions DJI RC Plus / RC 遥控器接电脑, 穿越机模拟器, FPV sim, Uncrashed, 无线手柄, 摇杆延迟/掉杆/卡顿 diagnosis, or wants to run, install, fix, or extend this bridge (launcher.py / rcplus_sim.py / dashboard.py / apk_build).
---

# RC Plus 无线模拟器手柄

把 DJI RC Plus 遥控器变成 Windows 上的无线 Xbox 360 手柄：

```
RC Plus (Android evdev) --adb(WiFi/USB)--> rcplus_sim.py --ViGEm--> 虚拟 X360 手柄 --> 模拟器
                                                    └--> dashboard.py :8123 --> 遥控器屏幕仪表页
```

核心脚本在 `scripts/`：`launcher.py`（常驻入口/菜单）、`rcplus_sim.py`（桥接主体）、
`rcplus_bridge.py`（解析与标定）、`dashboard.py`（遥控器屏幕实时仪表 + 点图标启动游戏）、
`win_key.py`（SendInput 鼠标）、`probe_latency.py` / `probe_radio.py`（诊断工具）。

## 环境要求

- Windows 10/11，Python 3.10+
- `pip install vgamepad` + **ViGEmBus 驱动**（https://vigem.org 下载安装，没它创建不了虚拟手柄）
- adb platform-tools（默认找 `C:\tools\platform-tools\adb.exe`）
- FPV 模拟器（如 Uncrashed）

## 安装与配置

1. 遥控器开启无线调试：插 USB 数据线跑一次 `adb tcpip 5555`，之后拔线走 WiFi。
2. 建配置文件 `scripts/rcplus_config.json`（可选但推荐，免改代码）：

```json
{
  "adb": "C:\\tools\\platform-tools\\adb.exe",
  "input_dev": "/dev/input/event6",
  "game": "D:\\Games\\Uncrashed\\Uncrashed.exe",
  "game_proc": "Uncrashed-Win64-Shipping.exe"
}
```

   `rcplus_bridge.py` 读 `adb`/`input_dev`，`rcplus_sim.py` 读 `game`/`game_proc`。
3. 首跑：`python launcher.py --auto`（自动选择 USB 或 WiFi；插线优先走线）。
   已记住的 WiFi IP 存在脚本同目录 `wifi_ip.txt`，开机后自动重连。
4. 开机自启：把 `assets/RCPlus_Auto.bat` 改好路径放进 shell 启动文件夹
   （`Win+R` → `shell:startup`）。
5. 遥控器屏幕仪表：遥控器 Firefox 打开 `http://<电脑IP>:8123` → 菜单"添加到主屏幕"。
   点该图标即打开仪表并自动拉起模拟器（POST /launch）。
6. 游戏内绑定：Controls 里选 `XInput Controller #1`，Throttle=左摇杆Y / Yaw=左摇杆X /
   Roll=右摇杆X / Pitch=右摇杆Y；Deadzone 设 0；SDL 轴 2/4 是扳机别绑。

## 必须知道的运行事实

- **退出码协议**：`rcplus_sim` 返回 10 = 用户按 R3 主动关游戏 → launcher 转
  `no_launch` 待命（手柄+仪表保持在线，游戏不再自动弹出）；返回 6 = 已有实例。
  这两个码别改，改了会变成"关游戏→又弹出"死循环。
- **getevent 只在状态变化时输出**：摇杆静止时一条事件都没有是正常的。
  判活必须靠设备侧心跳（流里每 2 秒一条 `__HB__`），别用"有没有数据"判断断线。
- **无线延迟的根因是 WiFi 省电休眠（PS-Poll）**，不是 adb：不发包时 ping 平均 75ms、
  事件流断档最长 1.5 秒；`RadioKeepAlive` 以 50 包/秒向遥控器发空 UDP 后 ping 降到 2ms。
  该线程仅无线模式启动。详见 [references/latency-wifi.md](references/latency-wifi.md)。
- **adb server 端口用 5038**（环境变量 `ANDROID_ADB_SERVER_PORT`）：5037 会被
  MuMu/雷电等模拟器的 adb 抢占重启，一重启事件流就断。
- 遥控器屏幕一休眠，DJI 驱动就停止上报 → KeepAwake 线程每 60s 补 WAKEUP，
  并把 `screen_off_timeout` 设为最大值。

## 诊断

先跑 `ping -n 20 <遥控器IP>`：
- 平均 1~5ms → 链路正常，问题在游戏/电脑侧
- 平均 50ms+ → 保活没生效（脚本没跑、或遥控器换网重连过）；重启 `launcher.py --auto`

更细的测量用 `scripts/probe_radio.py`（省电休眠对照实验）和
`scripts/probe_latency.py`（adb 往返 + 事件流间隔分布）。
常见故障的完整清单在 [references/troubleshooting.md](references/troubleshooting.md)。

## 硬件映射与扩展

改按键绑定、加新遥控器、查轴位 → [references/hardware-mapping.md](references/hardware-mapping.md)。
给遥控器做"Uncrashed"桌面图标 APK → [references/apk-build.md](references/apk-build.md)
（源码在 `assets/apk_build/`，r8/d8 对匿名类的 NPE 坑和 PE 图标提取的 RVA 坑都在里面）。

**evdev 看不到的输入**：右拨轮下方那个「不回中」的滚轮、左肩 F/S/N 三档拨杆，
都只走 DUML 私有协议。`getevent` 找不到它们**不代表没有** —— 读法、协议解析、
"怎么判断某字段是位置型还是计数器"的排查方法
→ [references/duml-wheel.md](references/duml-wheel.md)（代码在 `scripts/duml/`）。
