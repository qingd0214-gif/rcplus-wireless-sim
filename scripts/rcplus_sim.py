#!/usr/bin/env python3
"""
rcplus_sim.py — 把 DJI RC Plus / RC Pro 变成电脑上的 Xbox 360 手柄
                给 Uncrashed、Liftoff、Velocidrone 等 FPV 模拟器用

数据链路:
    RC Plus 摇杆 (Android evdev)  --adb-->  本脚本  --ViGEm-->  虚拟 Xbox360 手柄  -->  模拟器

前置:
    1. ViGEmBus 驱动已装好（本机已验证 OK）
    2. pip install vgamepad
    3. RC Plus 用数据线连电脑，`adb devices` 能看到设备

用法:
    python rcplus_sim.py --demo          ★ 不接遥控器，自动摆杆（验证驱动）
    python rcplus_sim.py                 ★ 默认：油门=左摇杆纵轴（绝对值，回中=中位）
                                          校准/绑轴【必须】用这个，锁存会毁掉校准
    python rcplus_sim.py --throttle latch   脚本内油门锁存（仅当游戏没有
                                            "Gamepad Throttle" 选项时才用）
    python rcplus_sim.py --throttle dial    油门 = 右侧拨轮（可停在任意位置）
    python rcplus_sim.py --launch           启动后自动拉起 Uncrashed

为什么默认不再锁存：
    Uncrashed 里有 "Gamepad Throttle" 开关，开了它游戏会自己处理"摇杆回中=油门"，
    我们只需老实发送绝对值。自己再锁存一层，会导致左 Y 轴一直漂移不回中——
    校准时表现为"有光标来抢设置"、绑不上轴；飞行时表现为飞机乱撞。
    游戏里的 Gamepad Throttle 要【开】。
"""

import argparse
import math
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# 独占一个 adb server 端口（默认 5037）。装了 MuMu/雷电这类模拟器后，它们
# 自带的 adb 会抢 5037、重启系统 adb server —— 一重启，我们的 getevent
# 摇杆数据流就被当场掐断，游戏里表现为"突然延迟/短暂断连"。
# 换到 5038 之后，模拟器的 adb 永远杀不到我们的 server。
# 必须【在第一次调用 adb 之前】设置好。
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")

try:
    import vgamepad as vg
except ImportError:
    sys.exit("缺 vgamepad，先执行:  python -m pip install vgamepad")

# 字符串名 -> Xbox 按键常量
XBTN = {
    "A":  vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B":  vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X":  vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y":  vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "GUIDE": vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
    "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "BACK":  vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "LS": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "RS": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
}

sys.path.insert(0, str(Path(__file__).parent))
from rcplus_bridge import CONFIG, State, parse_line  # noqa: E402

# Windows 默认定时器精度是 15.6ms：主循环 sleep(1/250=4ms) 实际会睡 15ms 左右，
# 等于把 250Hz 降成 ~64Hz，还带 15ms 抖动——这是"手感发黏"的隐形来源之一。
# 向系统申请 1ms 精度（进程级，退出自动失效）。
try:
    import ctypes
    ctypes.WinDLL("winmm").timeBeginPeriod(1)
except Exception:
    pass

# ---------------------------------------------------------------- 可调参数
DEADBAND    = 0.02     # 摇杆中心死区
RATE_HZ     = 250      # 更新虚拟手柄的频率
LATCH_RATE  = 1.6      # 锁存油门灵敏度：满杆每秒改变 1.6 个完整行程
THROTTLE_LO = -32768   # 油门杆最低位的原始值（拆弹簧后若最低位读数不是这个，改这里）
ADB_RESTART_DELAY = 0.2    # 事件流中断后等多久重连（原 1.0s：流一断飞行就冻 1 秒）
STALL_KILL    = 8.0    # 这么久没收到任何事件 → 判定事件流已死，强行重连
                       # （2026-11-14：无线 adb 会"半死"——TCP 还在、getevent 不再吐数据，
                       #   读线程永远阻塞在 readline 上，既不报错也不重连，表现就是
                       #   "摇杆卡住不动、按什么键都没反应"，直到游戏退出。必须靠看门狗。）

GAME_EXE = r"D:\穿越机模拟器\Uncrashed免安装\Uncrashed.FPV\Uncrashed.exe"
GAME_PROC = "Uncrashed-Win64-Shipping.exe"

# 可选：rcplus_config.json 覆盖游戏路径（和 rcplus_bridge 里的 adb/event 节点共用一个文件）
#   { "game": "D:\\Games\\Uncrashed\\Uncrashed.exe",
#     "game_proc": "Uncrashed-Win64-Shipping.exe" }
try:
    import json as _json
    _cfg = _json.loads((Path(__file__).with_name("rcplus_config.json")).read_text(encoding="utf-8"))
    GAME_EXE = _cfg.get("game", GAME_EXE)
    GAME_PROC = _cfg.get("game_proc", GAME_PROC)
except FileNotFoundError:
    pass
except Exception as e:
    print(f"[!] rcplus_config.json 解析失败，忽略：{e}")

# 遥控器的物理按键在两个 evdev 节点上：
#   /dev/input/event6  摇杆 MCU：自带完整手柄按键 (BTN_SOUTH/A、BTN_EAST/B ...)
#   /dev/input/event4  gpio-keys：KEY_F1~F6（C1/C2 等外壳按键）
BUTTON_DEV = "/dev/input/event4"
TOGGLE_KEY = "BTN_SELECT"          # Back 键 = 切换 油门锁存/绝对值
KILL_KEY = "KEY_F6"                # R3 = 关闭游戏
KILL_HOLD = 0.5                    # R3 要按住这么久才算数（防止飞行中误碰一下就把游戏关了）
MOUSE_SPEED = 900.0                # 菜单模式·鼠标通道：光标速度 像素/秒
ENTER_HOLD = 0.8                   # 五向键中间长按多久 = 轮换菜单通道（短按 = 确认）

# ---------------------------------------------------------------- 菜单模式
# 实测结论（2026-11-09 mouse_test.txt，50s 那次）：
#   五向键 ←↑→↓ → ABS_HAT0X / ABS_HAT0Y，取值 -1/0/1（上 = HAT Y:-1，右 = HAT X:+1）
#   五向键中间   → BTN_THUMBL（遥控器把它和"按左摇杆"合成同一个键名）
#   外壳 L3      → KEY_F3（这个键存在的话，短按也能轮换通道，不用长按）
# 所以"五向键读不到"这个前提是错的——它一直好好上报，问题只在游戏那边：
# Uncrashed 的选图界面不认虚拟手柄的十字键（实测 D-Pad 通了但 UI 不动）。
# 到底认什么，不同游戏/窗口模式不一样，猜不如试。于是做成三条通道，
# 长按中间键轮换，哪条让光标动起来就用哪条：
#   1 鼠标   → 注入 Windows 光标（游戏直接读系统鼠标时可用）
#   2 摇杆   → 五向键当虚拟手柄左摇杆推（游戏用自带光标/焦点导航时可用）
#   3 方向键 → 注入键盘 ↑↓←→（游戏只认键盘导航时可用）
# 三种通道都只在"菜单模式"里生效：飞行时左摇杆就是油门，油门杆不回中，
# 直接把五向键叠到左摇杆上会跟油门打架，所以必须先摘掉飞行输出。
MENU_MODES = ("鼠标", "摇杆", "方向键")
MENU_TOGGLE_KEYS = ("KEY_F3",)     # 外壳 L3：短按直接轮换（有就用，没有也不影响）
MENU_KEYS = ("KEY_ENTER", "BTN_THUMBL")   # 五向键中间，两种上报都认
MENU_STICK = 0.8                   # 摇杆通道：五向键按下时左摇杆推多少（0~1）

# 遥控器按键 -> Xbox 手柄按键。None = 不透传给游戏（脚本自用）
BTN_MAP = {
    "BTN_SOUTH":   "A",      # A
    "BTN_EAST":    "B",      # B
    "BTN_NORTH":   "X",      # X
    "BTN_WEST":    "Y",      # Y
    "BTN_TL":      "LB",
    "BTN_TR":      "RB",
    "BTN_START":   "START",
    # 五向键中间 = BTN_THUMBL。脚本要用它当"确认/轮换通道"，而且长按期间
    # 若还透传给游戏，游戏会认为你一直按着 LS，容易误触发绑定。所以扣下不发。
    "BTN_THUMBL":  None,
    "BTN_THUMBR":  "RS",
    "KEY_ENTER":   "A",
    "KEY_BACK":    "BACK",
    "KEY_HOMEPAGE":"START",
    "KEY_F1":      None,     # L1：不走手柄按键，改驱动 RT 轴（游戏的重置是轴输入）
    "KEY_F2":      "RB",
    "KEY_F3":      None,     # L3：菜单模式开关（不透传 GUIDE，否则会被游戏当系统键）
    "KEY_F4":      "START",  # 实测 RC Plus 无实体 START，F4 专用给游戏重置绑定
    "KEY_F5":      None,     # 走键盘注入（见 KEY_TAP），不占手柄按键
    "KEY_F6":      None,     # R3：关闭游戏（脚本自用，不透传给游戏）
    # 五向键若走按键上报，会以这些名字出现：不走 BTN_MAP 透传，
    # 而是在主循环里单独合成十字键（见"五向键 -> 手柄十字键"那段）
    "BTN_DPAD_UP":    None,
    "BTN_DPAD_DOWN":  None,
    "BTN_DPAD_LEFT":  None,
    "BTN_DPAD_RIGHT": None,
    "KEY_UP":      None,     # 五向键的另一路上报（Android 导航键）
    "KEY_DOWN":    None,
    "KEY_LEFT":    None,
    "KEY_RIGHT":   None,
    "BTN_SELECT":  None,     # 油门模式切换键，不透传
}

# 遥控器按键 -> 键盘按键（按下即敲一下）。游戏手柄动作绑定不生效时的备用通道。
KEY_TAP = {
    "KEY_F5": "R",           # F5 = 键盘 R，用来绑定游戏里的重置
    # KEY_F6 (R3) 原来敲键盘 T，属于早期调试残留。改成"关闭游戏"后必须摘掉，
    # 否则按 R3 关游戏的同时还会往游戏里打进一个 T。
}
# 遥控器按键名 -> Xbox 按键常量（值为 None 的不透传）
BTN_X = {k: XBTN[v] for k, v in BTN_MAP.items() if v}

# evdev 轴初始值（没收到事件前的默认状态 = 摇杆回中、油门最低）
# ABS_Y 默认 -32768：硬件油门已不回中，静止位在最低，避免开机时油门悬在 50%
AXIS_DEFAULTS = {
    "ABS_X": 0, "ABS_Y": -32768, "ABS_RX": 0, "ABS_RY": 0,
    "ABS_Z": 127, "ABS_RZ": 127,
    "ABS_HAT0X": 0, "ABS_HAT0Y": 0,
}


def norm(v, lo, ctr, hi):
    """把某个轴的原始值归一化到 -1..1（中心为 0）。"""
    if v >= ctr:
        n = (v - ctr) / max(1, hi - ctr)
    else:
        n = (v - ctr) / max(1, ctr - lo)
    return max(-1.0, min(1.0, n))


def dz(x):
    return 0.0 if abs(x) < DEADBAND else x


# ---------------------------------------------------------------- 游戏进程
def game_pids():
    """返回正在运行的 Uncrashed 进程 PID 列表。"""
    try:
        # 注意：中文 Windows 下 tasklist 输出是 GBK，不能用 text=True
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROC}", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=10,
        )
        raw = r.stdout or b""
    except Exception:
        return []
    for enc in ("gbk", "utf-8", "latin-1"):
        try:
            out = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 2 and GAME_PROC.lower() in parts[0].lower():
            pid = parts[1].strip()
            if pid.isdigit():
                pids.append(pid)
    return pids


def kill_game():
    pids = game_pids()
    for p in pids:
        subprocess.run(["taskkill", "/PID", p, "/F"], capture_output=True)
    print("    已关闭游戏。" if pids else "    游戏本来就没在运行。")
    return len(pids)


# ---------------------------------------------------------------- 电量保护
class BatteryGuard(threading.Thread):
    """每 2 分钟读一次电量。低于 25% 警告，低于 10% 主动断开（保遥控器）。"""

    WARN, STOP = 25, 10

    def __init__(self, adb, serial=None):
        super().__init__(daemon=True)
        self.adb, self.serial = adb, serial
        self.stop = threading.Event()
        self.last_level = None

    def _level(self):
        try:
            cmd = [self.adb] + (["-s", self.serial] if self.serial else []) \
                  + ["shell", "dumpsys battery"]
            out = subprocess.run(cmd, capture_output=True, timeout=15,
                                 encoding="gbk", errors="ignore").stdout or ""
        except Exception:
            return None
        for line in out.splitlines():
            if "level" in line and ":" in line:
                try:
                    return int(line.split(":")[1].strip())
                except ValueError:
                    return None
        return None

    def run(self):
        while not self.stop.wait(120):
            lv = self._level()
            if lv is None:
                continue
            self.last_level = lv
            if lv <= self.STOP:
                print(f"\n\n[!!] 遥控器电量只剩 {lv}%，为保护电池主动断开！")
                print("     请充电。虚拟手柄会随之消失。\n")
                import os
                os._exit(5)
            elif lv <= self.WARN:
                print(f"\n[!] 遥控器电量 {lv}%，建议尽快充电", flush=True)


# ---------------------------------------------------------------- 拨轮控音量
# RC Plus 的左右拨轮都是【弹簧回中】（min 0 / 中位 127 / max 255），
# 所以不能做"绝对位置=音量"（手一松就弹回 50%）。改用增量式：
#   拨轮往一边拨 → 音量按偏离量成比例连续加减；回中 → 立刻停住。
VOL_FILE    = Path(__file__).parent / "volume.txt"
DIAL_C      = 127     # 拨轮中位原始值
DIAL_DB     = 0.09    # 拨轮死区（相对满行程），滤掉回中后的残余抖动
DIAL_SPEED  = 1.0     # 拨到底时的音量变化速度：1.0 = 约 1 秒走完全程

# 左拨轮往左拨 = 重置。中位 127，最左 0。
# 阈值留得偏紧：飞行中误触重置等于主动炸机，宁可多拨一点。
RESET_DIAL_LO  = 85      # raw <= 这个值算"往左拨到位"（127→85 = 往左 33% 行程）
RESET_MIN_HOLD = 0.25    # RT 最短保持秒数，保证游戏抓得到一次完整按下沿


class VolumeCtl(threading.Thread):
    """把拨轮映射成「当前正在跑的游戏进程」的音量滑块。

    只调该进程的 ISimpleAudioVolume，不动系统总音量，所以语音/音乐不受影响。

    为什么是后台线程：实测 AudioUtilities.GetAllSessions() 平均 17ms、峰值 53ms，
    而主循环 250Hz 的单帧预算只有 4ms。放在主循环里会每 1.5 秒卡一下摇杆输出。
    所以主线程只做纯数学（算 vol），COM 探测与写入全丢给本线程。
    """

    TICK = 0.06        # 后台线程刷新周期：写入延迟最多 60ms，人耳无感

    def __init__(self, proc=GAME_PROC, axis="ABS_RZ", persist=True,
                 speed=DIAL_SPEED):
        super().__init__(daemon=True)
        self.proc   = (proc or "").lower()
        self.axis   = axis
        self.persist = persist
        self.speed  = speed
        self.vol    = self._load()     # 目标音量（主线程写，后台线程读）
        self.error  = None
        self.ready  = False            # 后台是否已连上会话
        self._sess = None              # ISimpleAudioVolume 指针
        self._pid  = None
        self._applied = None           # 上次真正写进去的音量
        self._t_probe = 0.0
        self._t_save  = 0.0
        self._stop = threading.Event()

    # ---- 音量记忆（下次启动接着上次的位置）
    def _load(self):
        try:
            return max(0.0, min(1.0, float(VOL_FILE.read_text().strip())))
        except Exception:
            return 1.0

    def _save(self, now):
        if not self.persist or now < self._t_save:
            return
        self._t_save = now + 1.0
        try:
            VOL_FILE.write_text(f"{self.vol:.3f}")
        except Exception:
            pass

    # ---- 音频会话
    def _probe(self, now):
        if now < self._t_probe:
            return self._sess is not None
        self._t_probe = now + 1.5
        try:
            from pycaw.pycaw import AudioUtilities
            for s in AudioUtilities.GetAllSessions():
                p = s.Process
                if p and p.name().lower() == self.proc:
                    if s.ProcessId != self._pid:      # 换了进程 → 强制重写一次
                        self._pid = s.ProcessId
                        self._applied = None
                    self._sess = s.SimpleAudioVolume
                    self.error = None
                    return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        self._sess, self._pid = None, None
        return False

    def _write(self, now, force=False):
        if self._sess is None:
            return
        if not force and self._applied is not None \
                and abs(self._applied - self.vol) < 0.003:
            return
        try:
            self._sess.SetMasterVolume(float(self.vol), None)
            self._applied = self.vol
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self._sess = None

    # ---- 后台线程：只它碰 COM
    def run(self):
        try:
            import comtypes
            comtypes.CoInitialize()        # 线程内独立公寓，必须在本线程调
        except Exception:
            pass
        while not self._stop.wait(self.TICK):
            now = time.time()
            if not self._probe(now):
                self.ready = False
                continue
            self.ready = True
            self._write(now)
            self._save(now)
        self._sess = None

    def stop(self):
        self._stop.set()

    # ---- 主线程每帧调用：纯数学，零阻塞
    def tick(self, raw, dt):
        d = (raw.get(self.axis, DIAL_C) - DIAL_C) / float(DIAL_C)
        if abs(d) <= DIAL_DB:
            return False
        # 扣掉死区后重新归一，避免刚越过死区那一下跳变
        d = math.copysign((abs(d) - DIAL_DB) / (1.0 - DIAL_DB), d)
        new = max(0.0, min(1.0, self.vol + d * self.speed * dt))
        if new == self.vol:          # 只在顶到 0/100 时相等（不能用小阈值，
            return False             # 否则轻拨时每帧增量太小会被吃掉，拨了没反应）
        self.vol = new
        return True


class KeepAwake(threading.Thread):
    """遥控器屏幕一休眠，DJI 的驱动就停止上报摇杆/按键（实测 mWakefulness=Asleep
    时 getevent 零事件）。这里每 20 秒补一次唤醒，从根上避免"摇杆突然全失效"。

    2026-11-09 改：不再轮询 dumpsys power。那个命令输出几百 KB，在 WiFi adb
    上要拖 1~3 秒，会把 getevent 控制流挤停——表现就是飞行中每隔 20 秒左右
    飞机"短暂断连"一次。改成无条件每 20 秒发一个 WAKEUP 键（几个字节），
    屏幕醒着时它是 no-op，代价可以忽略。"""

    def __init__(self, adb, serial=None):
        super().__init__(daemon=True)
        self.adb, self.serial = adb, serial
        self.stop = threading.Event()

    def _sh(self, *args, timeout=10):
        cmd = [self.adb] + (["-s", self.serial] if self.serial else []) + ["shell", *args]
        try:
            return subprocess.run(cmd, capture_output=True, timeout=timeout) \
                .stdout.decode("utf-8", "ignore")
        except Exception:
            return ""

    def prepare(self):
        """启动时：唤醒 + 关掉自动息屏。"""
        self._sh("input", "keyevent", "KEYCODE_WAKEUP")
        self._sh("settings", "put", "system", "screen_off_timeout", "2147483647")

    def run(self):
        # 2026-11-14 改：心跳从 5s 放宽到 15s，而且只有无线才发。
        # 每发一次就要新起一个 adb 客户端进程（实测单次 95ms，走同一个 adb server），
        # 密集发会把 getevent 的流挤出一堆 >100ms 的断档（实测每秒 1 次），
        # 手感就是"卡一下"。有线根本没有省电掐连接的问题，完全不用发。
        n = 0
        wireless = bool(self.serial and ":" in self.serial)
        while not self.stop.wait(15):
            n += 1
            if n % 4 == 0:
                # 每 60 秒补一次唤醒（屏幕醒着时是 no-op）
                self._sh("input", "keyevent", "KEYCODE_WAKEUP", timeout=8)
            elif wireless:
                # 无线专有：轻量心跳，防 WiFi 省电把空闲 TCP 静默掐死
                self._sh("true", timeout=8)


class RadioKeepAlive(threading.Thread):
    """无线专用：把遥控器的射频从 WiFi 省电休眠里踢醒，这是延迟的真正大头。

    2026-11-14 实测（小米 5G / 信道 60 / RSSI -62 / 协商 520Mbps）：
      · 不发包：ping 平均 53~75ms、最长 195ms；getevent 事件流 p99 66ms，
        12 秒内 10 次 >100ms 断档，最长 1.52 秒 —— 手感就是"摇杆卡一下 /
        掉一下 / 有一秒完全没反应"。
      · 每秒 30 个 24 字节 UDP：ping 平均 2ms、最长 5ms。
    原因：Android 的 WiFi 省电（PS-Poll）让射频只在 beacon 窗口醒来，收包要等
    下一个窗口；只要入向流量持续存在，驱动就会保持唤醒。代价 0.7KB/s，忽略不计。
    只对无线连接有意义，插线时完全不启动。
    """

    def __init__(self, ip, rate=50):
        super().__init__(daemon=True)
        self.ip, self.rate = ip, rate
        self.stop = threading.Event()

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setblocking(False)
        payload = b"\x00" * 24          # 空包：只为制造"有流量"的事实，内容无意义
        t0 = time.monotonic()
        n = 0
        while not self.stop.is_set():
            try:
                s.sendto(payload, (self.ip, 9998))   # 无线程监听，ICMP 会被内核限流
            except Exception:
                pass
            n += 1
            delay = t0 + n / self.rate - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -2.0:          # 系统挂起过，重新对表，别追帧
                t0, n = time.monotonic(), 0
        s.close()


# ---------------------------------------------------------------- 可见性自检
SDL_DLL = r"D:\穿越机模拟器\Uncrashed免安装\Uncrashed.FPV\Uncrashed\Binaries\Win64\SDL2.dll"


def sdl_sees_pad(dll=SDL_DLL):
    """借用游戏自己的 SDL2.dll 枚举一次手柄，确认游戏那套输入层能看见我们。
    返回 (数量, 名字) 或 None（用不了 SDL 时）。"""
    if not Path(dll).exists():
        return None
    try:
        import ctypes
        sdl = ctypes.CDLL(dll)
        # 手柄必须先存在，再 SDL_Init —— SDL 2.0.9 不做热插拔检测
        if sdl.SDL_Init(0x200 | 0x2000) != 0:
            return None
        sdl.SDL_NumJoysticks.restype = ctypes.c_int
        sdl.SDL_JoystickNameForIndex.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
        n = sdl.SDL_NumJoysticks()
        name = ""
        if n > 0:
            raw = sdl.SDL_JoystickNameForIndex(0)
            name = raw.decode("utf-8", "ignore") if raw else ""
        sdl.SDL_Quit()
        return (n, name)
    except Exception:
        return None


# ---------------------------------------------------------------- adb 读取
class RcReader(threading.Thread):
    """持续读 RC 的 evdev 事件；adb 掉了会自动重连。"""

    def __init__(self, adb, device, state, on_key=None, serial=None):
        super().__init__(daemon=True)
        self.adb, self.device, self.state = adb, device, state
        self.serial = serial          # 指定 -s 串号，避免 USB+WiFi 双设备冲突
        self.on_key = on_key          # 回调(键名, 是否按下)，用于热切换等
        self.got_data = False
        self.restarts = 0
        self.stop = threading.Event()
        self.last_data = time.time()   # 最近一次收到摇杆/按键数据的时间（停滞诊断用）
        self.last_beat = time.time()   # 最近一次收到设备侧心跳 __HB__ 的时间（判活）

    def kill_proc(self):
        """杀掉 getevent 子进程（连树）。

        为什么必须：python 退出时这个读线程还阻塞在 proc.stdout 上（daemon
        线程不等待），adb.exe 就成了孤儿——它还挂在控制台上，而 Windows
        Terminal 要等控制台上【所有】进程退出才关窗口。不杀它，双击自动
        启动的黑框在脚本退出后永远关不掉（实测确认）。
        """
        p = getattr(self, "proc", None)
        if p is None or p.poll() is not None:
            return
        try:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

    def _try_reconnect(self):
        """WiFi 模式下 adb 连接条目会因电脑睡眠/网络抖动消失 → 主动重连。

        （2026-11-14 事故：电脑睡了一觉后 adb devices 空，getevent 每次都
        瞬时失败，读线程 0.2s 一轮空转 17 万次，遥控器全程没数据。）
        """
        if not self.serial or ":" not in self.serial:
            return
        try:
            subprocess.run([self.adb, "connect", self.serial],
                           capture_output=True, timeout=15)
        except Exception:
            pass

    def run(self):
        fail_streak = 0        # 连续"一条数据都没读到"的次数（= 连接级故障）
        while not self.stop.is_set():
            # 复合命令：getevent 放后台，前台每 2 秒打一条心跳。
            # 为什么需要心跳：getevent 只在状态**变化**时输出，遥控器放着一动不动
            # 就一条事件都没有 —— 光看"有没有数据"根本分不清"静止"和"流已死"，
            # 会误判成掉线反复重连（2026-11-14 踩过）。有心跳就能精确区分：
            # 有心跳没事件 = 设备静止（正常）；连心跳都没有 = 流真的死了。
            cmd = [self.adb] + (["-s", self.serial] if self.serial else []) \
                  + ["shell", f"getevent -lt {self.device} & "
                              f"while true; do echo __HB__; sleep 2; done"]
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,          # 必须：否则 adb shell 会随父进程 stdin 关闭而退出
                    bufsize=1, universal_newlines=True,
                    encoding="utf-8", errors="ignore",
                )
            except FileNotFoundError:
                print(f"\n[错误] 找不到 adb: {self.adb}")
                return
            self.proc = proc               # 记下来，退出时由主线程杀掉（见 kill_proc）
            self.last_beat = time.time()   # 心跳计时归零

            # 看门狗：无线 adb 会"半死"——子进程还在、TCP 还挂着，但数据再也不来，
            # 读线程就永远卡在 readline 上，不抛异常也不重连。表现：摇杆冻住、
            # 按键全失灵，只能关游戏重来。这里盯 __HB__ 心跳（不是数据），
            # 超过 STALL_KILL 秒连心跳都没有就杀掉子进程，让下面的重连逻辑接管。
            wd_stop = threading.Event()

            def _watchdog(p=proc, ev=wd_stop):
                while not ev.wait(1.0):
                    if self.stop.is_set():
                        return
                    if time.time() - self.last_beat > STALL_KILL:
                        print(f"\n[警告] 事件流 {STALL_KILL:.0f}s 连心跳都没了（adb 半死），"
                              f"强制重连…", flush=True)
                        try:
                            p.kill()
                        except Exception:
                            pass
                        return

            threading.Thread(target=_watchdog, daemon=True).start()

            got_any = False
            prev_keys = dict(self.state.keys)
            try:
                for line in proc.stdout:
                    if "__HB__" in line:          # 设备侧心跳：链路还活着
                        self.last_beat = time.time()
                        got_any = True            # 有回音 → 不算连接级故障
                        continue
                    if parse_line(line, self.state):
                        got_any = True
                        self.got_data = True
                        self.last_data = time.time()
                    if self.on_key and self.state.keys != prev_keys:
                        for k, v in self.state.keys.items():
                            if prev_keys.get(k) != v:
                                self.on_key(k, v)
                        prev_keys = dict(self.state.keys)
                    if self.stop.is_set():
                        break
            except Exception:
                pass
            finally:
                wd_stop.set()
                try:
                    proc.terminate()
                except Exception:
                    pass

            if self.stop.is_set():
                return
            self.restarts += 1
            if got_any:
                # 正常断流（游戏切换/设备重枚举）：快速重连即可
                fail_streak = 0
                print(f"\n[警告] adb 事件流中断，{ADB_RESTART_DELAY}s 后重连…")
                time.sleep(ADB_RESTART_DELAY)
            else:
                # 连接级故障：先 adb connect，再退避 1→5 秒，绝不满速空转
                fail_streak += 1
                self._try_reconnect()
                delay = min(1.0 * fail_streak, 5.0)
                if fail_streak in (1, 5, 20) or fail_streak % 120 == 0:
                    print(f"\n[警告] 读不到遥控器数据（连续 {fail_streak} 次），"
                          f"每 {delay:.0f}s 自动重试；无线 adb 断了会自动重连。",
                          flush=True)
                time.sleep(delay)


def adb_preflight(adb, want_device=None, wifi=False):
    """确认 adb 可用且遥控器在线。返回设备序列号或 None。
    wifi=True 时优先选 IP 形式的串号（无线连接）。"""
    try:
        out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=15).stdout
    except FileNotFoundError:
        print(f"[错误] 找不到 adb.exe: {adb}")
        print("       改 CONFIG['adb'] 或 --adb 参数指向正确的 adb")
        return None
    except Exception as e:
        print(f"[错误] 执行 adb 失败: {e}")
        return None

    devs = [l.split("\t")[0].strip() for l in out.splitlines()[1:]
            if "\tdevice" in l]
    if not devs:
        print("[错误] 没有检测到遥控器。检查:")
        print("       1) 换一根【数据线】(不是充电线)")
        print("       2) 遥控器上把 USB 模式选成『文件传输/调试』")
        print("       3) adb 输出原文:")
        for l in out.splitlines():
            print("          " + l)
        return None
    if want_device and want_device in devs:
        return want_device
    if wifi:
        wifi_devs = [d for d in devs if ":" in d]   # IP:port 形式 = 无线
        if wifi_devs:
            return wifi_devs[0]
    return devs[0]


# ---------------------------------------------------------------- 单实例
_MUTEX_HANDLE = None


def single_instance_ok():
    """用 Windows 命名互斥体防止同时跑多份（多份会各自建一个虚拟手柄互相抢，
    两个 getevent 还会互相饿死 —— 五向键那种短脉冲最先丢）。

    2026-11-15 发现这把锁一直是坏的：`ctypes.windll.kernel32.GetLastError()`
    拿到的不是真实的 Win32 错误码（ctypes 只有在 use_last_error=True 时才会
    保存它），检查永远不触发，双开畅通无阻。必须用 WinDLL(use_last_error=True)
    + ctypes.get_last_error()。
    """
    global _MUTEX_HANDLE
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _MUTEX_HANDLE = k32.CreateMutexW(
            None, True, "Global\\RCPlusSimBridgeMutex")
        if not _MUTEX_HANDLE:
            return False
        return ctypes.get_last_error() != 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return True          # 拿不到互斥体就不拦，别因小失大


# ---------------------------------------------------------------- 主逻辑
def main():
    if not single_instance_ok():
        print("[!] 已经有一个手柄脚本在运行了。")
        print("    多开会导致多个虚拟手柄互相抢，摇杆会失效、按键会错乱。")
        print("    先关掉其他启动器窗口，再重新运行。")
        if "--yes" not in sys.argv:      # 双击自动启动时不等回车，直接退出
            try:
                input("\n按回车退出…")
            except Exception:
                pass
        return 6

    ap = argparse.ArgumentParser(description="RC Plus → 虚拟 Xbox360 手柄")
    ap.add_argument("--wifi", help="RC 的 IP，走无线 adb（会先 adb connect）")
    ap.add_argument("--adb", default=CONFIG["adb"], help="adb.exe 路径")
    ap.add_argument("--device", default=CONFIG["input_dev"], help="evdev 节点")
    ap.add_argument("--throttle", choices=["latch", "stick", "dial"], default="stick",
                    help="stick=绝对值(硬件油门已改不回中,默认) latch=锁存(硬件回中时用) "
                         "dial=拨轮; 运行中按 Back 键可随时切换")
    ap.add_argument("--rate", type=float, default=LATCH_RATE, help="锁存油门灵敏度")
    ap.add_argument("--invert-pitch", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="不接遥控器，自动摆杆（验证模拟器能否识别虚拟手柄）")
    ap.add_argument("--launch", action="store_true", help="就绪后自动启动 Uncrashed")
    ap.add_argument("--game", default=GAME_EXE, help="游戏 exe 路径")
    ap.add_argument("--raw", action="store_true", help="额外显示各轴原始值(标定用)")
    ap.add_argument("--no-vol", action="store_true",
                    help="关闭拨轮调音量")
    ap.add_argument("--vol-axis", choices=["ABS_RZ", "ABS_Z"], default="ABS_RZ",
                    help="用哪个拨轮调音量：ABS_RZ=右拨轮(默认) ABS_Z=左拨轮")
    ap.add_argument("--vol-speed", type=float, default=DIAL_SPEED,
                    help=f"拨轮灵敏度，拨到底每秒走完几个行程(默认 {DIAL_SPEED})")
    ap.add_argument("--vol-start", type=float, default=None,
                    help="强制设定初始音量 0~1（不给则沿用上次记住的值）")
    ap.add_argument("--no-reset-dial", action="store_true",
                    help="关闭「左拨轮往左拨=重置」（只留 L1）")
    ap.add_argument("--reset-dial-lo", type=int, default=RESET_DIAL_LO,
                    help=f"左拨轮触发重置的阈值，raw<=(默认 {RESET_DIAL_LO})，"
                         f"越小越难误触")
    ap.add_argument("--yes", action="store_true",
                    help="所有询问自动回答 y（双击自动启动时用，不等回车）")
    ap.add_argument("--no-r3-kill", action="store_true",
                    help="关掉「R3 = 关闭游戏」，只留 L3 菜单模式")
    ap.add_argument("--r3-hold", type=float, default=KILL_HOLD,
                    help=f"R3 要按住多少秒才关游戏(默认 {KILL_HOLD:g}，设 0 = 一碰就关)")
    ap.add_argument("--no-wheel", action="store_true",
                    help="不读第三拨轮（右拨轮下方那个不回中的），只保留摇杆功能")
    ap.add_argument("--mouse-speed", type=float, default=MOUSE_SPEED,
                    help=f"菜单·鼠标通道：五向键推住时光标速度 像素/秒(默认 {MOUSE_SPEED:g})")
    ap.add_argument("--menu", type=int, choices=[0, 1, 2, 3], default=0,
                    help="启动时直接进菜单通道(1鼠标/2摇杆/3方向键)，0=不进")
    a = ap.parse_args()

    # 0) 关键前置检查：游戏已经在跑 = 它启动时看不到手柄，后面怎么点都是空的
    running = game_pids()
    if running:
        print(f"[!] Uncrashed 已经在运行 (PID {', '.join(running)})")
        print("    它在启动时就把输入设备枚举完了，现在即使建好手柄，")
        print("    游戏里的设备下拉也仍然是空的 —— 必须重启游戏。")
        if a.launch:
            if a.yes:
                ans = "y"
                print("    自动确认：关掉它重新启动（--yes）。")
            else:
                try:
                    ans = input("    要我现在关掉它、重新用正确顺序启动吗？[y/N] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans = ""
            if ans == "y":
                kill_game()
                time.sleep(2.0)
            else:
                print("    已取消。请手动关闭游戏后重来。")
                return 3
        else:
            print("    建议先关掉游戏，再重新运行本脚本。\n")

    adb = a.adb
    if a.wifi:
        subprocess.run([adb, "connect", f"{a.wifi}:5555"], check=False)

    serial = None
    if not a.demo:
        serial = adb_preflight(adb, wifi=bool(a.wifi))
        if not serial:
            print("\n提示: 想先验证驱动/模拟器这一端，可加 --demo 参数（不需要遥控器）")
            return 2
        conn = "无线WiFi" if ":" in serial else "USB"
        print(f"遥控器已连接({conn} · {serial}) · 读 {a.device}")

    # 1) 先建手柄，再启动游戏 —— UE 类游戏在启动时才枚举输入设备
    pad = vg.VX360Gamepad()
    print(f"★ 虚拟 Xbox 360 手柄已创建 (VID 045E / PID 028E) · 油门模式={a.throttle}")
    print("  Windows 里可用 Win+R → joy.cpl 看到『XBOX 360 手柄』")

    st = State()
    st.raw.update(AXIS_DEFAULTS)          # 关键：预置中位，未收到事件也能驱动手柄

    # --- 遥控器屏幕"摇杆仪表"网页服务（常开，失败不影响飞行） ---
    # 遥控器自带 Firefox：打开 http://<本机IP>:8123 就是 FPV 遥控器风格的
    # 实时仪表（双杆圆点+通道条+按键灯）；在 Firefox 菜单里"添加到主屏幕"
    # 之后，遥控器桌面就有图标，点开即仪表。数据同源，与飞行互不干扰。
    # 仪表显示符号（用户实拍校准）：油门/俯仰与摇杆物理方向相反，取反显示
    # 拨轮峰值保持：拨轮是自回中的（松手立刻回 127），直接显示的话页面上
    # 只闪一帧根本看不清。这里把"拨到过的最远值"留 1.5 秒，再回落到 0。
    _hold = {"dl": 0.0, "dr": 0.0, "tdl": 0.0, "tdr": 0.0}

    def _dash_snapshot():
        raw = st.raw
        now = time.time()
        dl = norm(raw.get("ABS_Z", 127), 0, 127, 255)
        dr = norm(raw.get("ABS_RZ", 127), 0, 127, 255)
        if abs(dl) > 0.03:
            _hold["dl"], _hold["tdl"] = dl, now
        elif now - _hold["tdl"] > 1.5:
            _hold["dl"] = 0.0
        if abs(dr) > 0.03:
            _hold["dr"], _hold["tdr"] = dr, now
        elif now - _hold["tdr"] > 1.5:
            _hold["dr"] = 0.0
        return {"thr": round(-norm(raw.get("ABS_Y", THROTTLE_LO), THROTTLE_LO, 0, 32767), 3),
                "yaw": round(norm(raw.get("ABS_X", 0), -32768, 0, 32767), 3),
                "roll": round(norm(raw.get("ABS_RX", 0), -32768, 0, 32767), 3),
                "pitch": round(-norm(raw.get("ABS_RY", 0), -32768, 0, 32767), 3),
                "dl": round(_hold["dl"], 3),
                "dr": round(_hold["dr"], 3),
                "hx": raw.get("ABS_HAT0X", 0), "hy": raw.get("ABS_HAT0Y", 0),
                "btns": sorted(k for k, v in st.keys.items() if v),
                # 第三拨轮（只在 DUML 里）：{"wd": 方向, "ws": 速度档}
                **dashboard.wheel_snapshot()}

    # 遥控器点仪表页 → 自动启动模拟器（游戏已在跑就跳过，绝不重复开）
    def _dash_launch():
        if game_pids():
            return True                       # 已在运行
        try:
            subprocess.Popen([a.game], cwd=str(Path(a.game).parent))
            print("\n>>> [遥控器] 已启动模拟器   ", flush=True)
            return False
        except Exception as e:
            print(f"\n[!] 遥控器启动模拟器失败: {e}   ", flush=True)
            return False

    try:
        import dashboard
        if not a.no_wheel:
            # 第三拨轮：只读，只上仪表 —— 不写手柄轴、不写任何键（2026-11-15）
            dashboard.start_wheel(a.adb, serial)
        dashboard.start_server(_dash_snapshot, commands={"launch": _dash_launch})
        print(f"★ 摇杆仪表屏已就绪: http://{dashboard.local_ip()}:8123"
              f"  （遥控器 Firefox 打开；Firefox 菜单→添加到主屏幕 = 桌面图标）")
    except OSError:
        print("[i] 仪表屏端口已被占用（可能手柄脚本已开着），跳过。")
    except Exception as e:
        print(f"[!] 仪表屏服务启动失败（不影响飞行）: {e}")

    # --- 油门手感 ---
    # 硬件油门已改不回中（拆弹簧）→ 默认绝对值：杆在哪，油门就是哪。
    # 锁存模式留给"硬件回中"的场景（按 Back 键随时切换）。
    box = {"latch": (a.throttle == "latch"), "btn": "", "btn_t": 0.0,
           "reset_until": 0.0,
           # R3 关游戏：按下的时刻，松手时才判定按够久没有
           "kill_t": 0.0, "quit": False, "kill_on": not a.no_r3_kill,
           # 十字键当前状态 (上,下,左,右)，只用于状态栏显示
           "dpad": (False, False, False, False),
           # 菜单模式：0=关（正常飞行），1/2/3 = MENU_MODES 的下标+1
           "menu": a.menu,
           # 鼠标通道的位移小数累积（像素），避免每帧取整丢步
           "mouse_acc": [0.0, 0.0],
           # 进入菜单模式时的杆位快照，用来判断"是不是想飞了"
           "menu_entry": {},
           # 一次性"清空手柄状态"请求。不能在 on_key 里直接 pad.reset()：
           # 那个回调跑在 RcReader 线程，和主线程 250Hz 的 pad.update() 撞在一起
           # 偶尔会把 ViGEm 调用搞挂，读线程一死就再也收不到按键了。
           "reset_req": False,
           # 五向键中间按下的时刻（松开时判定：短按=确认 / 长按=轮换通道）
           "enter_t": 0.0,
           # 一次物理按下被两路上报（KEY_ENTER + BTN_THUMBL）时只处理一次
           "enter_done": False,
           # 摇杆通道里"确认"要发一下 A 键：按住到这个时刻为止
           "a_until": 0.0,
           # 左拨轮若已被音量占用，就不能再兼任重置，否则一拨触发两件事
           "dial_reset": (not a.no_reset_dial) and a.vol_axis != "ABS_Z"}

    if box["menu"]:
        # --menu 直接进模式：也得有杆位快照，否则安全网不生效
        box["menu_entry"] = {k: st.raw.get(k, 0) for k in
                             ("ABS_X", "ABS_Y", "ABS_RX", "ABS_RY")}

    def menu_label():
        return MENU_MODES[box["menu"] - 1] if box["menu"] else "关"

    def cycle_menu():
        """轮换菜单通道：关 → 鼠标 → 摇杆 → 方向键 → 关。

        为什么要轮换而不是一步到位：游戏的选图界面认哪种输入，实测没法预判
        （D-Pad 已确认不认）。让用户长按几次就换一条路，比让他改配置、重启
        脚本快得多。
        """
        box["menu"] = (box["menu"] + 1) % (len(MENU_MODES) + 1)
        box["mouse_acc"] = [0.0, 0.0]
        box["a_until"] = 0.0
        if box["menu"]:
            box["reset_req"] = True    # 真正清手柄放在主线程（见 reset_req 注释）
            # 杆位快照：之后杆子动得多 → 主循环自动退出（见安全网）
            box["menu_entry"] = {k: st.raw.get(k, 0) for k in
                                 ("ABS_X", "ABS_Y", "ABS_RX", "ABS_RY")}
            hint = {"鼠标": "五向键推 = 系统光标",
                    "摇杆": "五向键推 = 游戏自带光标",
                    "方向键": "五向键 = 键盘方向键"}[menu_label()]
            print(f"\n>>> [菜单模式 → {menu_label()}] 飞行输出已摘掉 · {hint} · "
                  f"短按中间=确认 · 长按中间=换下一条 · Back=Esc   ", flush=True)
        else:
            print("\n>>> [菜单模式 关] 恢复飞行输出   ", flush=True)

    def menu_confirm():
        """菜单模式里的"点一下"：按通道各自发对应的确认动作。"""
        import win_key
        if box["menu"] == 1:                     # 鼠标通道
            ok = win_key.mouse_click("left")
            print(f"\n>>> [菜单·鼠标] 左键 (SendInput {ok})   ", flush=True)
        elif box["menu"] == 2:                   # 摇杆通道 → 虚拟 A 键
            box["a_until"] = time.time() + 0.12
            print("\n>>> [菜单·摇杆] A 键   ", flush=True)
        elif box["menu"] == 3:                   # 方向键通道 → 键盘 Enter
            ok = win_key.tap("ENTER")
            print(f"\n>>> [菜单·方向键] Enter (SendInput {ok})   ", flush=True)

    def on_key(name, down):
        if down:
            box["btn"], box["btn_t"] = name, time.time()
            print(f"\r[按键] {name}      ", end="", flush=True)   # 实时日志：看清到底收到什么
            # 键盘注入备用通道：游戏手柄动作绑定失效时用这个
            k = KEY_TAP.get(name)
            if k:
                try:
                    import win_key
                    win_key.tap(k)
                    print(f"\n>>> 已发送键盘 {k}   ", flush=True)
                except Exception as e:
                    print(f"\n[!] 键盘注入失败: {e}")
        # 入口一：外壳 L3（KEY_F3）。有就短按直接轮换，省得长按。
        if name in MENU_TOGGLE_KEYS and down:
            cycle_menu()
        # 入口二（主入口）：五向键中间 = KEY_ENTER 或 BTN_THUMBL
        #   短按 = 确认（按通道发 左键/A/Enter）
        #   长按 ≥0.8s = 轮换菜单通道
        # 用长按当开关：中间键是唯一"摸得到、按得准"的确定性按键，
        # 不依赖任何键名假设；短按留给"选中"这种高频动作。
        # 注意同一物理按下可能被两路各上报一次（enter_done 去重），
        # 否则一次按下会既开模式又立刻确认。
        if name in MENU_KEYS:
            if down:
                if not box["enter_t"]:
                    box["enter_t"] = time.time()
                    box["enter_done"] = False
            elif not box["enter_done"]:
                box["enter_done"] = True
                held_s = time.time() - box["enter_t"] if box["enter_t"] else 0.0
                box["enter_t"] = 0.0
                if held_s >= ENTER_HOLD:
                    cycle_menu()
                elif box["menu"]:
                    try:
                        menu_confirm()
                    except Exception as e:
                        print(f"\n[!] 确认注入失败: {e}")
                else:
                    # 鼠标常开后，平时短按中间=左键点选，不用进菜单模式。
                    try:
                        import win_key
                        ok = win_key.mouse_click("left")
                        print(f"\n>>> [五向键] 左键 (SendInput {ok})   ", flush=True)
                    except Exception as e:
                        print(f"\n[!] 左键注入失败: {e}")
        if box["menu"] and down and name == "KEY_BACK":
            try:
                import win_key
                win_key.tap("ESC")
                print("\n>>> [菜单模式] Esc   ", flush=True)
            except Exception as e:
                print(f"\n[!] Esc 注入失败: {e}")
        if name == KILL_KEY and box["kill_on"]:
            if down:
                box["kill_t"] = time.time()
            else:
                held = time.time() - box["kill_t"] if box["kill_t"] else 0.0
                box["kill_t"] = 0.0
                if held >= a.r3_hold:
                    box["quit"] = True        # 真正动手放在主循环里
                else:
                    print(f"\n>>> R3 按太快（{held:.2f}s < {a.r3_hold:g}s），"
                          f"没关游戏   ", flush=True)
        if name == TOGGLE_KEY and down:
            box["latch"] = not box["latch"]
            mode = "锁存(穿越机手感)" if box["latch"] else "绝对值(校准用)"
            print(f"\n>>> 油门模式切换为：{mode}   ", flush=True)

    readers = []
    guard = None
    radio_ka = None
    if not a.demo:
        for dev in sorted({a.device, BUTTON_DEV}):
            r = RcReader(adb, dev, st, on_key, serial)
            r.start()
            readers.append(r)
        guard = BatteryGuard(adb, serial)
        guard.start()
        awaker = KeepAwake(adb, serial)
        awaker.prepare()          # 先唤醒一次并关掉自动息屏
        awaker.start()
        # 无线才需要：持续小流量唤醒射频（详见 RadioKeepAlive 文档字符串）
        if serial and ":" in serial:
            radio_ka = RadioKeepAlive(serial.split(":")[0])
            radio_ka.start()
            print("  [无线] 射频保活已开启（50 包/秒）：实测链路 RTT 75ms → 2ms")
        print("  请把【两个摇杆】各推到四角再回中一次，脚本才读得到全部轴")
        print("  （电量保护已开启：<25% 警告，<10% 自动断开）")
        print(f"  按 遥控器 {TOGGLE_KEY} = 切换 绝对值/锁存（默认绝对值：硬件油门不回中）")
        print("  【五向键】直接推 = 移动系统光标（选地图不用进任何模式）· 中间短按 = 左键点选")
        print("      （实测这游戏不认键盘方向键也不认手柄十字键，认的就是系统鼠标）")
        print("  【菜单模式】备用：长按中间 0.8 秒轮换 关→鼠标→摇杆→方向键→关")
        print("      模式里：五向键推=按通道移动 · 短按中间=确认 · Back=Esc")
        print("  【飞行中】五向键 = 手柄十字键（游戏自己认十字键的界面用）")
        if a.no_r3_kill:
            print("  R3 = 关闭游戏（已用 --no-r3-kill 关掉）")
        else:
            hold = "一碰就关" if a.r3_hold <= 0 else f"按住 {a.r3_hold:g} 秒"
            print(f"  R3 = 关闭游戏（{hold}）· 关完连本脚本一起退出，双击 bat 重新开")
        print("  【左拨轮往左拨一下】= 重置（拉满 RT/Axis6）；L1 也可，留作备份")
        print("  遥控器物理按键已映射成手柄按键，游戏里可直接绑定（见下方按钮表）")

    # --- 拨轮调游戏音量 ---
    vol = None
    if not a.no_vol:
        vol = VolumeCtl(axis=a.vol_axis, speed=a.vol_speed)
        if a.vol_start is not None:
            vol.vol = max(0.0, min(1.0, a.vol_start))
        vol.start()                 # 后台线程管 COM，主循环零阻塞
        name = "右拨轮" if a.vol_axis == "ABS_RZ" else "左拨轮"
        print(f"★ {name} = 游戏音量（当前 {vol.vol*100:.0f}%）"
              f" · 拨一下加减，松手停住 · 音量自动记住")
        print(f"  只调游戏进程自己的音量，不影响系统/语音 · "
              f"灵敏度 {a.vol_speed:g}（--vol-speed 可调）")
        if a.vol_axis == "ABS_Z":
            print("  [!] 左拨轮已被音量占用 → 拨轮重置自动关闭，重置仍可用 L1")

    if a.launch:
        time.sleep(1.5)                   # 等 Windows 把设备节点挂好
        seen = sdl_sees_pad()
        if seen is None:
            print("  （跳过 SDL 自检：没找到游戏自带的 SDL2.dll）")
        elif seen[0] == 0:
            print("[!] 游戏自带的 SDL2 看不到这个手柄，先别启动游戏。")
            print("    试试：换个 USB 口重插、确认 ViGEm 总线设备正常、杀毒软件没拦。")
            return 4
        else:
            print(f"★ 自检通过：游戏自带的 SDL2 已看到 {seen[0]} 个手柄 —— {seen[1]}")
        try:
            subprocess.Popen([a.game], cwd=str(Path(a.game).parent))
            print(f"★ 已启动 {Path(a.game).name}")
            print("\n  下一步（在游戏里）：")
            print("   1) 进 Controls，设备下拉里应出现 XInput Controller #1 —— 选中它")
            print("   2) Stick Calibration，按提示把摇杆推到行程端点、再回中")
            print("   3) 手动分配 Throttle / Roll / Pitch / Yaw")
            print("      Throttle=左摇杆上下  Yaw=左摇杆左右")
            print("      Roll=右摇杆左右      Pitch=右摇杆上下")
            print("      ⚠ SDL 轴 2 和 4 是扳机，永远 -1，千万别选")
            print("   4) Deadzone 设 0；Gamepad Throttle 关（油门直接走摇杆轴，游戏别再做一层）")
            print("   5) 硬件油门已不回中： Stick Calibration 里把油门重新校准一次端点")
            print("   6) 如果之前绑乱了，先用菜单 [8] 重置绑定再重新绑\n")
        except Exception as e:
            print(f"[警告] 启动游戏失败: {e}")

    throttle = 0.0
    t0 = time.time()
    prev_t = t0
    last_print = 0.0
    period = 1.0 / RATE_HZ

    try:
        while True:
            now = time.time()
            dt = min(0.1, now - prev_t)
            prev_t = now
            raw = st.raw

            # 切模式时请求的手柄清零，统一在主线程做（跨线程调 ViGEm 不安全）
            if box["reset_req"]:
                box["reset_req"] = False
                try:
                    pad.reset()
                except Exception:
                    pass

            # R3 关游戏：判定在 on_key 里（松手且按够时长才置 quit），这里执行。
            # 关完游戏连脚本一起退出。退出码 10 = "用户主动关"：
            # launcher 常驻模式看到 10 就不再自动开游戏（否则会变成
            # "关掉→重启→又弹出"死循环），只重开手柄待命，等遥控器点图标。
            if box["quit"]:
                print("\n>>> R3：关闭游戏…")
                kill_game()
                # 遥控器屏幕上的仪表页也一并关掉，屏幕回到遥控器桌面。
                # （之后想再玩：点遥控器图标 → 仪表打开 → 自动拉起模拟器）
                if serial and not a.demo:
                    try:
                        subprocess.run([a.adb, "-s", serial, "shell",
                                        "am force-stop com.rcplus.dashboard"],
                                       capture_output=True, timeout=10)
                        print(">>> 遥控器仪表页已关闭。")
                    except Exception as e:
                        print(f"[!] 关遥控器仪表页失败（不影响其他操作）: {e}")
                print(">>> 手柄脚本一并退出（退出码 10，常驻脚本不会重启游戏）。")
                return 10          # finally 块照常释放手柄/读线程

            # 拨轮调音量：放在最前面，菜单模式里也能调（不加这个提前返回会被跳过）
            if vol is not None:
                vol.tick(raw, dt)

            # 菜单模式（长按五向键中间轮换）：飞行输出全摘掉，五向键专门用来
            # 操作游戏的选图界面。三条通道轮换——不同游戏/窗口模式认的输入
            # 不一样（Uncrashed 确认不认 D-Pad），与其猜，不如让用户长按几次换路。
            if box["menu"]:
                import win_key
                pad.left_joystick_float(0.0, 0.0)
                pad.right_joystick_float(0.0, 0.0)
                pad.left_trigger(0)
                pad.right_trigger(0)
                held_ui = {k for k, v in st.keys.items() if v}
                hx, hy = raw.get("ABS_HAT0X", 0), raw.get("ABS_HAT0Y", 0)
                d_up    = hy < 0 or "BTN_DPAD_UP" in held_ui or "KEY_UP" in held_ui
                d_down  = hy > 0 or "BTN_DPAD_DOWN" in held_ui or "KEY_DOWN" in held_ui
                d_left  = hx < 0 or "BTN_DPAD_LEFT" in held_ui or "KEY_LEFT" in held_ui
                d_right = hx > 0 or "BTN_DPAD_RIGHT" in held_ui or "KEY_RIGHT" in held_ui
                prev = box["dpad"]          # 上一帧的状态，方向键通道要用按下沿
                box["dpad"] = (d_up, d_down, d_left, d_right)

                # 安全网：进模式后把任一杆推动超过 60% = 明显想飞，自动退出。
                # 避免"忘了还在菜单模式 → 摇杆没反应 → 以为遥控器坏了"。
                # 用相对进场快照的变化量，不能用绝对值：油门杆不回中，
                # 看绝对值的话一进模式就会立刻退出。
                e = box["menu_entry"] or {}
                if e:
                    moved = max(abs(st.raw.get(k, 0) - e.get(k, 0))
                                for k in ("ABS_X", "ABS_Y", "ABS_RX", "ABS_RY"))
                    if moved > 0.6 * 32768:
                        box["menu"] = 0
                        print("\n>>> [菜单模式 自动关闭] 检测到摇杆动作，已恢复飞行   ",
                              flush=True)
                        continue

                if box["menu"] == 1:
                    # 通道 1 · 鼠标：期望位移（像素/帧）→ 累积小数 remainder 再取整，
                    # 否则 250Hz 下每帧 3.6px 全被 int() 吃成 3px，速度虚标 17%
                    vx = ((1.0 if d_right else 0.0) - (1.0 if d_left else 0.0))
                    vy = ((1.0 if d_down else 0.0) - (1.0 if d_up else 0.0))
                    if vx and vy:                 # 斜推不超速
                        vx *= 0.7071
                        vy *= 0.7071
                    box["mouse_acc"][0] += vx * a.mouse_speed * dt
                    box["mouse_acc"][1] += vy * a.mouse_speed * dt
                    mx = int(box["mouse_acc"][0])
                    my = int(box["mouse_acc"][1])
                    if mx or my:
                        box["mouse_acc"][0] -= mx
                        box["mouse_acc"][1] -= my
                        try:
                            win_key.mouse_move(mx, my)
                        except Exception:
                            pass
                elif box["menu"] == 2:
                    # 通道 2 · 摇杆：五向键 = 虚拟手柄左摇杆的推杆方向。
                    # 游戏若用"自带光标"或"焦点导航"，会跟着动。
                    lx = ((1.0 if d_right else 0.0) - (1.0 if d_left else 0.0)) * MENU_STICK
                    ly = ((1.0 if d_up else 0.0) - (1.0 if d_down else 0.0)) * MENU_STICK
                    if lx and ly:
                        lx *= 0.7071
                        ly *= 0.7071
                    pad.left_joystick_float(x_value_float=lx, y_value_float=ly)
                else:
                    # 通道 3 · 方向键：只在按下沿敲一次，按住不会连发刷屏
                    for on, was, key in ((d_up, prev[0], "UP"),
                                         (d_down, prev[1], "DOWN"),
                                         (d_left, prev[2], "LEFT"),
                                         (d_right, prev[3], "RIGHT")):
                        if on and not was:
                            try:
                                win_key.tap(key)
                            except Exception:
                                pass

                # 物理按键照常透传：菜单里还要能按 A / B / START。
                # 但 KEY_ENTER（也是五向键中间的另一路上报）在菜单模式里要扣下：
                # 它已经由"确认"逻辑接管，再透传一次 A 会和鼠标左键/Enter 撞成两下。
                for nm, xbtn in BTN_X.items():
                    if nm == "KEY_ENTER" and box["menu"]:
                        continue
                    (pad.press_button if nm in held_ui
                     else pad.release_button)(xbtn)
                # "确认"发的那下 A 放在透传之后，否则会被上面的 release 冲掉
                if now < box["a_until"]:
                    pad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
                else:
                    pad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)

                pad.update()
                if now - last_print > 0.5:
                    last_print = now
                    print(f"\r[菜单:{menu_label()}] 五向键=移动 · 短按中间=确认 · "
                          f"长按中间=换通道 · Back=Esc   ", end="", flush=True)
                time.sleep(period)
                continue

            if a.demo:
                # 演示：左摇杆画圆、右摇杆走正弦，肉眼可辨
                ph = (now - t0) * 1.1
                nx, ny = math.cos(ph), math.sin(ph)
                rx, ry = math.sin(ph * 0.7), math.cos(ph * 0.5)
                ly = 0.5 + 0.5 * math.sin(ph * 0.4)
                throttle = ly * 0.5 + 0.5
            else:
                nx = dz(norm(raw.get("ABS_X", 0), -32768, 0, 32767))   # 左横 = yaw
                ny = dz(norm(raw.get("ABS_Y", 0), -32768, 0, 32767))   # 左纵 = 油门(上=+)
                rx = dz(norm(raw.get("ABS_RX", 0), -32768, 0, 32767))  # 右横 = roll
                ry = dz(norm(raw.get("ABS_RY", 0), -32768, 0, 32767))  # 右纵 = pitch(上=+)

                if box["latch"]:
                    throttle += ny * a.rate * dt          # 推加 / 拉减 / 松手保持
                    throttle = max(0.0, min(1.0, throttle))
                    ly = throttle * 2 - 1
                elif a.throttle == "dial":
                    ly = norm(raw.get("ABS_RZ", 127), 0, 127, 255)
                    throttle = (ly + 1) / 2
                else:
                    # 绝对值模式（硬件油门不回中）：杆位=油门。
                    # 不套死区，避免 50% 油门附近出现台阶。
                    ly = norm(raw.get("ABS_Y", THROTTLE_LO), THROTTLE_LO, 0, 32767)
                    throttle = (ly + 1) / 2

            pad.left_joystick_float(x_value_float=-nx, y_value_float=ly)
            pad.right_joystick_float(x_value_float=rx,
                                     y_value_float=(-ry if not a.invert_pitch else ry))

            held = {k for k, v in st.keys.items() if v}

            # 五向键 -> 手柄十字键（游戏菜单里上下左右选项目）。
            # 这台设备的能力表同时声明了三套可能与五向键有关的上报方式，
            # 全都认，谁先到算谁，用"或"合并就不会重复触发：
            #   a) ABS_HAT0X/Y 轴（-1/0/1）—— 多数固件把五向键报成 hat
            #   b) BTN_DPAD_* 按键        —— 有的固件报成四个手柄方向键
            #   c) KEY_UP/DOWN/LEFT/RIGHT —— RC Plus 上这套 Android 导航键
            #                              （同一个五向键的另一路映射）
            hx, hy = raw.get("ABS_HAT0X", 0), raw.get("ABS_HAT0Y", 0)
            d_up    = hy < 0 or "BTN_DPAD_UP" in held    or "KEY_UP" in held
            d_down  = hy > 0 or "BTN_DPAD_DOWN" in held  or "KEY_DOWN" in held
            d_left  = hx < 0 or "BTN_DPAD_LEFT" in held  or "KEY_LEFT" in held
            d_right = hx > 0 or "BTN_DPAD_RIGHT" in held or "KEY_RIGHT" in held
            for btn, on in ((vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,  d_left),
                            (vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT, d_right),
                            (vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,    d_up),
                            (vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,  d_down)):
                pad.press_button(btn) if on else pad.release_button(btn)
            box["dpad"] = (d_up, d_down, d_left, d_right)

            # 鼠标常开（2026-11-09 定案：实测键盘方向键在游戏里完全无效，
            # 三条通道里真正能选图的是"鼠标"那条）。五向键直接推系统光标，
            # 中间短按直接左键，不再需要长按进任何模式。
            # 游戏全屏时对系统光标不敏感，飞行中误推五向键最多是桌面光标
            # 悄悄挪个位置，不影响飞行。
            # 菜单模式（长按，摇杆等备用通道）里由各通道自己接管，这里不发，
            # 否则推一下动两下。
            if not box["menu"]:
                import win_key
                vx = ((1.0 if d_right else 0.0) - (1.0 if d_left else 0.0))
                vy = ((1.0 if d_down else 0.0) - (1.0 if d_up else 0.0))
                if vx and vy:                 # 斜推不超速
                    vx *= 0.7071
                    vy *= 0.7071
                box["mouse_acc"][0] += vx * a.mouse_speed * dt
                box["mouse_acc"][1] += vy * a.mouse_speed * dt
                mx = int(box["mouse_acc"][0])
                my = int(box["mouse_acc"][1])
                if mx or my:
                    box["mouse_acc"][0] -= mx
                    box["mouse_acc"][1] -= my
                    try:
                        win_key.mouse_move(mx, my)
                    except Exception:
                        pass

            # 物理按键 -> Xbox 按键（摔机重置、菜单确认都靠这个）
            for name, xbtn in BTN_X.items():
                (pad.press_button if name in held
                 else pad.release_button)(xbtn)

            # RC 的重置是"轴式"输入：把 RT 拉满（游戏里绑的是 Axis6）。
            # 两个触发源，互相备份：
            #   1) L1         —— 原来的方式，留着当后路
            #   2) 左拨轮往左 —— 更顺手，拨一下即可
            # 拨轮是弹簧回中的，"拨一下"往往只有几十毫秒，而游戏要抓一个
            # 完整的按下沿，所以加最短保持时间，保证一定被识别到。
            z = raw.get("ABS_Z", DIAL_C)
            if box["dial_reset"] and z <= a.reset_dial_lo:
                box["reset_until"] = now + RESET_MIN_HOLD
            reset_on = ("KEY_F1" in held) or (now < box["reset_until"])
            pad.right_trigger(255 if reset_on else 0)
            pad.left_trigger(0)

            pad.update()

            if now - last_print > 0.25:
                last_print = now
                bar = "█" * int(throttle * 20)
                mode = "锁存" if box["latch"] else "绝对"
                line = (f"\r[{mode}] 油门 {throttle*100:5.1f}% |{bar:<20}| "
                        f"yaw {nx:+.2f} roll {rx:+.2f} pitch {ry:+.2f}")
                if vol is not None:
                    if not vol.ready:
                        line += "  音量 --%（游戏未运行）"
                    else:
                        line += f"  音量 {vol.vol*100:3.0f}%"
                if reset_on:
                    line += "  [重置]"
                du, dd, dl, dr = box["dpad"]
                if box["menu"]:
                    line += f"  [菜单:{menu_label()}]"
                elif any((du, dd, dl, dr)):
                    line += "  [五向键 " + ("↑" if du else "") + ("↓" if dd else "") \
                            + ("←" if dl else "") + ("→" if dr else "") + "]"
                if box["kill_t"]:        # R3 按住中：显示还差多久生效
                    el = now - box["kill_t"]
                    line += f"  [R3 关游戏 {el:.1f}/{a.r3_hold:g}s]"
                if a.raw:
                    line += (f"  raw X{raw.get('ABS_X'):+7d} Y{raw.get('ABS_Y'):+7d}"
                             f" RX{raw.get('ABS_RX'):+7d} RY{raw.get('ABS_RY'):+7d}")
                if now - box["btn_t"] < 2 and box["btn"]:
                    line += f"  按键:{box['btn']}"
                if any(r.restarts for r in readers):
                    line += f"  [重连{sum(r.restarts for r in readers)}]"
                if readers:
                    # 用设备侧心跳判活，不再用"有没有事件"：摇杆静止时本来就没事件，
                    # 用数据判会一直误报停滞。心跳 2 秒一次，超过 4 秒才算真断。
                    beat = max(time.time() - r.last_beat for r in readers)
                    if beat > 4.0:
                        line += f"  [链路停滞 {beat:.1f}s]"   # adb 流真的卡了
                print(line + "   ", end="", flush=True)

            time.sleep(period)
    except KeyboardInterrupt:
        print("\n\n收到 Ctrl+C，正在释放虚拟手柄…")
    finally:
        for r in readers:
            r.stop.set()
            r.kill_proc()     # 杀 getevent 子进程：不杀的话终端窗口关不掉（见 kill_proc）
        if guard:
            guard.stop.set()
        if radio_ka is not None:
            radio_ka.stop.set()
        if vol is not None:
            vol.stop()
            try:
                VOL_FILE.write_text(f"{vol.vol:.3f}")   # 退出时落盘最终音量
            except Exception:
                pass
        try:
            pad.reset()
            pad.update()
        except Exception:
            pass
        print("已释放。手柄设备会随之从系统中移除（正常现象）")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
