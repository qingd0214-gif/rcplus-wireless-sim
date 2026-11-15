# RC Plus 硬件输入映射（evdev 实测）

DJI RC Plus 是一台 Android 设备。`adb shell ls /dev/input/` 有 7 个节点，
全系统只有 event6 有摇杆轴，**evdev 里没有第三个拨轮轴**（实测两次录制 + 三次静止读数确认）。

> ⚠️ 但**别据此认为没有第三个拨轮**。遥控器右拨轮下方那个「不回中」的滚轮
> 确实存在、确实能用，只是**只走 DUML 私有协议，不进 evdev**。
> 详见 [`duml-wheel.md`](duml-wheel.md)。

| 节点 | 名称 | 内容 |
|---|---|---|
| event0 | qpnp_pon | 电源键 |
| event1/2 | dummy_key | 无实键 |
| event3 | qti-haptics | 只有 FF（振动）事件 |
| event4 | gpio-keys | KEY_F1~F6（003b~0040）+ KEY_VOLUMEUP（0073） |
| event5 | fts_ts | 触摸屏 |
| event6 | DJI embedded joystick | 摇杆/拨轮/五向键/手柄键，详见下表 |

## event6 轴（`getevent -p` 实测）

| 代码 | 轴 | 范围 | 用途 | 松手行为 |
|---|---|---|---|---|
| 0000 | ABS_X | -32768..32767 | 左摇杆横向（偏航） | 回中（fuzz 16 / flat 128） |
| 0001 | ABS_Y | -32768..32767 | 左摇杆纵向（油门） | 回中（静止值 ≈ -1） |
| 0002 | ABS_Z | 0..255，中位 127 | 左拨轮 | **回 127（自回中）** |
| 0003 | ABS_RX | -32768..32767 | 右摇杆横向（横滚） | 回中 |
| 0004 | ABS_RY | -32768..32767 | 右摇杆纵向（俯仰） | 回中 |
| 0005 | ABS_RZ | 0..255，中位 127 | 右拨轮 | 回 127（自回中） |
| 0010 | ABS_HAT0X | -1..1 | 五向键左右 | **脉冲**（推一下 ±1 立刻回 0） |
| 0011 | ABS_HAT0Y | -1..1 | 五向键上下 | 脉冲 |

## event6 键

- `BTN_TL` / `BTN_TR`：左右肩键（LB/RB）
- `BTN_THUMBL`：五向键中键（按下）
- `BTN_SOUTH/EAST/NORTH/WEST`、`BTN_SELECT/START`、`BTN_THUMBL/THUMBR`：手柄标准键
- `BTN_TRIGGER_HAPPY1~4`（0x220~0x223）：备用
- `KEY_BACK`（0xac）、`KEY_ENTER`（0x1c）、`KEY_UP/RIGHT/LEFT/DOWN`（0x63/0x67/0x69/0x6a）：五向键方向在部分固件也走 KEY
- 其余 0xe0/0xe1/0xf4/0x130~0x13e 见 `getevent -p /dev/input/event6`

## event4 键（外壳按键）

`KEY_F1~F6` = 遥控器 C1~C6 物理按键（F1/F2/F3 左侧竖排，F4/F5/F6 右侧竖排），
`KEY_VOLUMEUP(0073)` = 未知键（可能是拍照/录像）。

## 仪表页显示的补偿逻辑

- 拨轮自回中 → 直接显示只闪一帧。`rcplus_sim._dash_snapshot()` 里做 **1.5 秒峰值保持**（`_hold`）。
- 五向键脉冲 → `dashboard.py` 页面端做 **450ms 余亮**（`pkT` + `lit()`）。
- 油门/俯仰显示取反（用户实拍校准：屏幕显示方向与物理摇杆方向相反才直观）。

## 加新遥控器/改绑定

1. `adb shell getevent -lt /dev/input/eventN` 边按边看（注意多会话会互相饿死，见 troubleshooting）。
2. 键码 → 手柄键的映射表在 `rcplus_sim.py` 的 `KEY_TO_BTN` 和 `on_key()`；
   轴 → XInput 轴在主循环的 `pad.left_joystick_float` 等调用处。
3. C 键在 event4，摇杆在 event6，`RcReader` 会各起一个读线程（`BUTTON_DEV` 常量）。
