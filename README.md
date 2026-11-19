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
  鼠标选地图）、肩键、Back、R3 长按关游戏 —— 每一项见下文[按键映射完整表](#按键映射完整表)
- **真后台运行**：`pythonw` 无窗口常驻，日志落盘；飞行时自动断开 DUML、跳过电量查询
- **油门两种手感**：绝对值（杆在哪油门在哪，适合不回中改装杆）/ 锁存（穿越机手感），Back 一键切换
- **电池保护**：遥控器 <25% 警告、<10% 自动断开
- **断线自愈**：掉线自动重连、事件流"半死"自动检测重连、屏幕休眠自动唤醒

## 硬件支持

| 设备 | 状态 |
|---|---|
| DJI RC Plus | ✅ 完整支持（作者在用） |
| DJI RC / RC Pro / RC 2 | ⚠️ 未验证，evdev 映射大概率不同，欢迎反馈 |

## ⚠️ 硬件改装：左摇杆（油门）的回中弹簧必须拆掉

**这一步不是可选项。** 本项目按"油门杆不回中"设计，左摇杆纵向的回中弹簧必须拆掉，
拆完油门杆会**停在任意位置**（杆位 = 油门值）。

为什么必须拆：

- 穿越机（含真机）的油门天然不回中，松手就悬停 50% 的杆子在模拟器里完全没法飞；
- 本项目的**绝对值油门模式**（默认）就是读取杆的绝对位置当油门 —— 弹簧还在的话，
  一松手油门自动弹回 50%，压杆/爬升都做不到；
- 校准游戏端点时也按"不回中杆"的行程来推，弹簧在会一直跟你抢。

拆掉之后三个副作用，全部有解：

| 副作用 | 处理 |
|---|---|
| 开机自检报"摇杆未回中"，警报滴滴响不停 | 遥控器快捷面板开**勿扰**；本项目每次连上/重连会**自动写回** `zen_mode=1`，不用手动 |
| 油门杆停机时会停在任意位置 | 起飞/开飞前先把油门放到最低（或你要的位置），养成习惯 |
| 想要"松手保持"的穿越机手感 | 按 **Back** 切换 锁存模式（推加 / 拉减 / 松手保持），随时切回绝对值 |

> 没拆弹簧也不是完全不能用：把 `--throttle latch` 打开用锁存模式，但手感会很别扭，
> 推一下加一点、杆子被弹簧拽回来，不推荐。

## 安装

### 1. 依赖

- Windows 10/11 + Python 3.10+
- [ViGEmBus 驱动](https://vigem.org)（虚拟手柄内核驱动，必装）
- `pip install vgamepad`
- [adb platform-tools](https://developer.android.com/tools/releases/platform-tools)，
  默认路径 `C:\tools\platform-tools\adb.exe`（可配置）

> ⚠️ **给 `vgamepad` 用一个独立 venv，别装进受管运行时。**
> 有些环境（比如 IDE/助手自带的嵌入式 python）会在重启时把 `site-packages`
> 重置成只剩 `pip`，`vgamepad` 跟着消失 —— 症状是"重启后游戏里突然没手柄"，
> 而 `rcplus_sim.py` 只打一行 `缺 vgamepad` 就退出，很难联想过去。
>
> ```sh
> py -3.14 -m venv C:\rcplus-env
> C:\rcplus-env\Scripts\python.exe -m pip install vgamepad
> ```
>
> 或者直接双击 `assets/setup_env.bat`（一键建环境 + 装包）。启动 bat 会先探测，
> 缺了自动重建；`launcher.py` 也会自动挑一个**能 import vgamepad** 的解释器。
> 细节见 [`references/troubleshooting.md`](references/troubleshooting.md) 第 4 条。

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

**后台运行（推荐日常用）**：用 `pythonw.exe` 启动 launcher，桌面不会有任何黑框，
输出写进 `scripts/launcher_bg.log`：

```bat
start "" "C:\rcplus-env\Scripts\pythonw.exe" -u "...\scripts\launcher.py" --auto
```

停后台：

```sh
powershell -Command "Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'launcher.py|rcplus_sim.py' } | % { Stop-Process -Id $_.ProcessId -Force }"
```

> 后台模式下所有子进程（adb、tasklist…）都会带 `CREATE_NO_WINDOW`，
> 不会闪黑框；控制台模式（`python launcher.py --auto`）仍保留，便于看实时状态。

游戏内绑定（Uncrashed 为例）：

1. Controls → 设备选 `XInput Controller #1`
2. Stick Calibration：两杆推满四角再回中
3. Throttle=左摇杆Y · Yaw=左摇杆X · Roll=右摇杆X · Pitch=右摇杆Y
4. Deadzone 设 0；Gamepad Throttle 关；**SDL 轴 2/4 是扳机（恒 -1），别绑**

### 5. 开机自启（可选，推荐）

把 [`assets/RCPlus_Auto.bat`](assets/RCPlus_Auto.bat) 改好路径，放进
`Win+R` → `shell:startup` 打开的文件夹。想无窗口启动就把 bat 里的 `python.exe`
换成 `pythonw.exe`（见上一步）。

常驻进程活着 = 遥控器点仪表图标随时能拉起模拟器；**待命时它不占遥控器的 DUML**
（见下文的"飞行时零负担"）。

### 6. 遥控器屏幕仪表（可选）

遥控器 Firefox 打开 `http://<电脑IP>:8123` → 菜单 → **添加到主屏幕**。
以后点这个图标 = 打开仪表 + 自动启动模拟器。
想要真 APP（Uncrashed 图标）：见 [`references/apk-build.md`](references/apk-build.md)。

## 按键映射（完整表）

遥控器上的每个输入映射到哪、干什么用，逐项列清。
`evdev 名` 是 `getevent` 里看到的名字，方便自己改映射时对照。

### 摇杆与拨轮

| 物理位置 | evdev | 虚拟手柄输出 | 功能 |
|---|---|---|---|
| 左摇杆 横向 | `ABS_X` | 左摇杆 X | **偏航**（yaw） |
| 左摇杆 纵向 | `ABS_Y` | 左摇杆 Y | **油门** · 默认绝对值（杆位=油门）；Back 切锁存 |
| 右摇杆 横向 | `ABS_RX` | 右摇杆 X | **横滚**（roll） |
| 右摇杆 纵向 | `ABS_RY` | 右摇杆 Y | **俯仰**（pitch，默认取反） |
| 左拨轮 | `ABS_Z` | **RT 轴脉冲** | **重置**：往左拨到底（raw ≤ 85）→ RT 拉满 ≥0.25s，保证游戏抓到按沿 |
| 右拨轮 | `ABS_RZ` | — | **调游戏音量**（增量式，松手即停，自动记住；只改游戏进程音量） |
| 右拨轮下方「不回中滚轮」 | 无（DUML byte4） | — | **仅仪表显示**：转的时候箭头亮 + 速度档 1~5 |
| 左肩下 F/S/N 三档拨杆 | 无（DUML byte2） | — | **仅仪表显示**：当前档位常亮 |

> 重置有两个触发源，互为备份：**左拨轮左拨** 或 **C1（L1）**，效果完全等价（都是拉满 RT）。
> 用 `--vol-axis ABS_Z` 把左拨轮改成音量后，左拨轮的重置会自动关闭（避免一拨两件事）。

### 五向键

| 操作 | evdev | 输出 | 功能 |
|---|---|---|---|
| 直接推 ↑↓←→ | `ABS_HAT0X/Y` | ① 系统光标② 手柄十字键 | **选图/菜单导航**：光标 900 px/s（斜推自动限速），同时发十字键给游戏 |
| 短按中键 | `BTN_THUMBL` / `KEY_ENTER` | 不输出（脚本自用） | **鼠标左键**（平时）；**菜单模式里 = 确认**（按通道发 左键 / A / Enter） |
| 长按中键 0.8s | 同上 | — | **轮换菜单通道**：关 → 鼠标 → 摇杆 → 方向键 → 关 |

**为什么中键不透传给游戏**：它同时是"按左摇杆"的键名（`BTN_THUMBL`），透传会让游戏
以为你一直按着 LS，误触发绑定。

菜单模式的三条通道（鼠标 / 摇杆 / 方向键）**都只在菜单模式里生效**：进模式时飞行输出
（摇杆、扳机）全部清零，所以油门杆停在哪都不会影响导航；**安全网**——进模式后任一杆
推动超过 60% 视为"想飞"，自动退出菜单模式恢复飞行。

### 外圈按键

| 物理键 | evdev | 虚拟手柄输出 | 功能 |
|---|---|---|---|
| A / B / X / Y | `BTN_SOUTH/EAST/NORTH/WEST` | A / B / X / Y | 透传 |
| LB / RB | `BTN_TL` / `BTN_TR` | LB / RB | 透传 |
| Back | `BTN_SELECT`（部分固件也报 `KEY_BACK`） | 不透传¹ | **切换 油门绝对值 / 锁存**；菜单模式下 = **Esc** |
| START | `BTN_START` / `KEY_HOMEPAGE` | START | 透传 |
| RS（按右摇杆） | `BTN_THUMBR` | RS | 透传 |
| **C1**（左侧第 1 个，仪表标 `L1`） | `KEY_F1` | RT 拉满 | **重置**（同左拨轮） |
| **C2**（左侧第 2 个，标 `L2`） | `KEY_F2` | RB | 透传 |
| **C3**（左侧第 3 个，标 `L3`） | `KEY_F3` | 不透传 | **菜单通道轮换**（短按，等价长按中键） |
| **C4**（右侧第 1 个，标 `R1`） | `KEY_F4` | **更改地图宏** | 自动：Esc 开暂停菜单 → 鼠标精确点击「更改地图」→ 弹出地图选择面板（选图用五向键鼠标）。坐标按 3440x1440 实测，其它分辨率在 `rcplus_config.json` 改 `changemap_x/y` |
| **C5**（右侧第 2 个，标 `R2`） | `KEY_F5` | 键盘 **R**（SendInput） | 备用通道：游戏不认手柄时用键盘绑定重置 |
| **C6**（右侧第 3 个，标 `R3`） | `KEY_F6` | 不透传 | **按住 0.5s 关游戏** → 关仪表页 → 手柄转待命（点图标随时再开）；按不到 0.5s 不动作，防误碰 |

¹ 部分固件会把 Back 同时报成手柄 BACK 键，此时游戏里也会看到 BACK 被按下，不影响使用。

### 仪表页每个元素

遥控器 Firefox 打开 `http://<电脑IP>:8123`，页面上每块都是实的：

| 元素 | 含义 |
|---|---|
| 左杆圆点 | 左摇杆实时位置（横向偏航 / 纵向油门） |
| 右杆圆点 | 右摇杆实时位置（横滚 / 俯仰） |
| 4 条通道条 | 油门 / 偏航 / 横滚 / 俯仰的实时数值 |
| 双拨轮条 | 左、右拨轮（自回中，做 **1.5s 峰值保持**，不然只闪一帧） |
| `滚轮 ◀ ▶` + 档位数字 | 第三个不回中滚轮：转动时对应箭头亮，数字 = 速度档 1~5 |
| `模式 F S N` | 飞行模式拨杆当前档位，常亮 |
| `L1 L2 L3` / `R1 R2 R3` 键灯 | 外壳 C1~C6，按下即亮 |
| `LB` `Back` `RB` 键灯 | 肩键 / Back |
| `摇杆延迟 X ms · N 条/s` | **实时链路延迟**：`getevent` 内核时间戳 vs PC 到达时刻的漂移（相对滑动窗口最优路径）。绿 <30ms / 黄 <100ms / 红 ≥100ms。只在推杆时更新，静止时显示最后一次的值 |
| 五向键十字 + 中心点 | 五向键方向与中键（脉冲上报，做 **450ms 余亮**） |
| `▶ 启动模拟器` 按钮 | 一键拉起 Uncrashed；页面连上时若游戏没跑，也会自动发一次启动 |

### 可调参数（不想改代码就用这些）

| 参数 | 默认 | 作用 |
|---|---|---|
| `--throttle latch` | 绝对值 | 启动即用锁存油门 |
| `--menu 1/2/3` | 关 | 启动即进菜单通道（1 鼠标 / 2 摇杆 / 3 方向键） |
| `--mouse-speed` | 900 | 五向键推光标的速度（像素/秒） |
| `--r3-hold` | 0.5 | R3 关游戏需要按住多久（0 = 一碰就关） |
| `--reset-dial-lo` | 85 | 左拨轮触发重置的阈值（raw ≤ 此值） |
| `--no-reset-dial` | 关 | 禁用左拨轮重置 |
| `--vol-axis ABS_Z` | `ABS_RZ` | 把音量换到左拨轮 |
| `--no-wheel` | 关 | 不读第三拨轮 / FSN（不连 DUML） |
| `--invert-pitch` | 关 | 翻转俯仰方向 |

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

### 飞行时零负担（重要）

读 DUML 需要一直挂一个客户端在上面。而**真机飞行时，飞行链路自己也走 DUML**——
常驻客户端会和它抢遥控器的处理能力（实测：飞行打杆变肉、极限转角不及时）。

所以本项目的 DUML 客户端**跟随游戏生命周期**：

- 游戏在跑 → 连上（仪表上的滚轮 / F/S/N 是亮的）
- 游戏退出 / 待命 / 飞行 → **自动断开**（仪表上那两个区域是灭的，正常现象）

同理，待命和飞行时也会跳过电量查询（`dumpsys` 会短暂挤停数据通道）。
原则一句话：**飞行时遥控器独占 DUML，PC 侧不留任何客户端。**

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
│   ├── launcher.py          # 常驻入口 / 菜单（支持 pythonw 后台模式）
│   ├── rcplus_sim.py        # 桥接主体（读事件→虚拟手柄→仪表数据）
│   ├── rcplus_bridge.py     # 事件解析 / 标定 CONFIG
│   ├── dashboard.py         # 遥控器屏幕仪表 (HTTP :8123)
│   ├── stick_screen.py      # 只开仪表屏的独立入口
│   ├── win_key.py           # SendInput 鼠标/键盘
│   ├── probe_radio.py       # WiFi 省电对照实验
│   ├── probe_latency.py     # 延迟/事件流测量
│   ├── probe_latency2~5.py  # 内核时间戳攒包检测 / 仪表线程 A/B 对决
│   ├── test_wheel_gate.py   # 仪表 DUML 连接 start/stop 往返验证
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
