#!/usr/bin/env python3
"""
rcplus_bridge.py — DJI RC Plus / RC Pro  ->  CRSF(ELRS) 桥接

数据源: RC 内部 /dev/input/event6 ("DJI embedded joystick")
  ABS_X / ABS_Y    : 左摇杆  -32768..32767  中心 0
  ABS_RX / ABS_RY  : 右摇杆  -32768..32767  中心 0
  ABS_Z / ABS_RZ   : 拨轮     0..255        中点 127
  ABS_HAT0X/Y      : 五向键  -1/0/1
  EV_KEY           : KEY_BACK / KEY_ENTER ...

用法:
  # 1) 离线回放已抓的日志，检查映射
  python rcplus_bridge.py replay C:/temp/rc_joystick.log

  # 2) 实时从 USB 连接的 RC 读取，输出到串口上的 ELRS TX 模块
  python rcplus_bridge.py live --serial COM5

  # 3) 实时但不发串口，只打印通道值(调试)
  python rcplus_bridge.py live --print

  # 4) 控制端(飞控/小车)还没接好时，用 UDP 广播通道值
  python rcplus_bridge.py live --udp 127.0.0.1:14550

通道约定 (Betaflight / iNav / ArduPilot 通用 AETR):
  CH1 Roll      <- ABS_RX
  CH2 Pitch     <- ABS_RY
  CH3 Throttle  <- ABS_Y    (默认 -32768..32767 线性映射到 988..2012us)
  CH4 Yaw       <- ABS_X
  CH5 / CH6     <- ABS_Z / ABS_RZ 拨轮
  CH7 / CH8     <- HAT0X / HAT0Y 五向键
  CH9..CH16     <- 预留物理按键 (KEY_* 映射见 KEY_MAP)

所有方向、行程、死区都在 CONFIG 里改，不用动代码逻辑。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

# 后台模式（pythonw）必需：控制台子进程禁止弹黑框（见 rcplus_sim.py 同名常量）
_NOWIN = 0x08000000 if os.name == "nt" else 0
from dataclasses import dataclass, field
from pathlib import Path

# ----------------------------------------------------------------------------
# CONFIG — 现场标定后改这里
# ----------------------------------------------------------------------------
CONFIG = {
    "adb": r"C:\tools\platform-tools\adb.exe",
    "input_dev": "/dev/input/event6",
    "crsf_addr": 0xC8,          # 0xC8 = 发往飞控
    "crsf_baud": 420000,        # ELRS TX 模块 CRSF 输入波特率
    "rate_hz": 150,             # 通道刷新率
    "deadband_us": 3,           # 中位死区(微秒)
    "failsafe_us": 1000,        # throttle 在无输入时的安全值
}

# 可选：脚本同目录放一个 rcplus_config.json 就能覆盖 CONFIG，
# 不用改代码。示例：
#   { "adb": "D:\\adb\\platform-tools\\adb.exe", "input_dev": "/dev/input/event6" }
_cfg_file = Path(__file__).with_name("rcplus_config.json")
if _cfg_file.exists():
    try:
        CONFIG.update(json.loads(_cfg_file.read_text(encoding="utf-8")))
        print(f"[i] 已加载配置文件 {_cfg_file.name}")
    except Exception as e:
        print(f"[!] rcplus_config.json 解析失败，忽略：{e}")

# axis -> (通道号, 下限, 中心, 上限, 反向)
# 标定方法: 把摇杆推到两端, 读 live --print 的 raw 值, 填进上下限
AXIS_MAP = {
    "ABS_RX":   {"ch": 1, "lo": -32768, "ctr": 0, "hi": 32767, "inv": False},  # Roll
    "ABS_RY":   {"ch": 2, "lo": -32768, "ctr": 0, "hi": 32767, "inv": True},   # Pitch
    "ABS_Y":    {"ch": 3, "lo": -32768, "ctr": 0, "hi": 32767, "inv": True},   # Throttle
    "ABS_X":    {"ch": 4, "lo": -32768, "ctr": 0, "hi": 32767, "inv": True},   # Yaw
    "ABS_Z":    {"ch": 5, "lo": 0, "ctr": 127, "hi": 255, "inv": False},       # 拨轮 1
    "ABS_RZ":   {"ch": 6, "lo": 0, "ctr": 127, "hi": 255, "inv": False},       # 拨轮 2
    "ABS_HAT0X": {"ch": 7, "lo": -1, "ctr": 0, "hi": 1, "inv": False},         # 五向左右
    "ABS_HAT0Y": {"ch": 8, "lo": -1, "ctr": 0, "hi": 1, "inv": False},         # 五向上下
}

# 物理按键 -> 通道 (按下 = 2000us, 松开 = 1000us)
KEY_MAP = {
    "KEY_BACK": 9,
    "KEY_ENTER": 10,
    "KEY_MENU": 11,
    "KEY_HOMEPAGE": 12,
}

CH_MIN, CH_MAX = 172, 1811          # CRSF 11bit: 988us..2012us
US_MIN, US_MAX = 988, 2012


# ----------------------------------------------------------------------------
# CRSF 编码
# ----------------------------------------------------------------------------
def crc8_dvb_s2(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crsf_channels_frame(channels_us, addr=0xC8) -> bytes:
    """16 通道, 每通道 11bit, 打包成 22 字节 payload。"""
    vals = [max(0, min(2047, int(round((us - US_MIN) / (US_MAX - US_MIN) * (CH_MAX - CH_MIN) + CH_MIN))))
            for us in channels_us[:16]]
    vals += [992] * (16 - len(vals))          # 992 ≈ 1500us 中位

    packed = bytearray()
    bits = 0
    nbits = 0
    for v in vals:
        bits |= (v & 0x7FF) << nbits
        nbits += 11
        while nbits >= 8:
            packed.append(bits & 0xFF)
            bits >>= 8
            nbits -= 8
    assert len(packed) == 22, len(packed)

    body = bytes([0x16]) + bytes(packed)
    frame = bytes([addr, len(body) + 1]) + body
    return frame + bytes([crc8_dvb_s2(frame[2:])])


# ----------------------------------------------------------------------------
# 轴 -> 微秒
# ----------------------------------------------------------------------------
@dataclass
class State:
    raw: dict = field(default_factory=dict)
    keys: dict = field(default_factory=dict)

    def channels(self):
        chs = [1500] * 16
        chs[2] = CONFIG["failsafe_us"]      # 未收到油门数据前，油门保持最低，别让电机转
        for axis, m in AXIS_MAP.items():
            if axis not in self.raw:
                continue
            v = self.raw[axis]
            lo, ctr, hi = m["lo"], m["ctr"], m["hi"]
            if v >= ctr:
                norm = (v - ctr) / max(1, hi - ctr)
            else:
                norm = (v - ctr) / max(1, ctr - lo)
            norm = max(-1.0, min(1.0, norm))
            if m["inv"]:
                norm = -norm
            us = 1500 + norm * 500
            if abs(us - 1500) < CONFIG["deadband_us"]:
                us = 1500
            chs[m["ch"] - 1] = int(round(us))
        for key, ch in KEY_MAP.items():
            chs[ch - 1] = 2000 if self.keys.get(key) else 1000
        return chs


# ----------------------------------------------------------------------------
# getevent 解析
# ----------------------------------------------------------------------------
RE_ABS = re.compile(r"EV_ABS\s+(\w+)\s+([0-9a-fA-F]{8})")
RE_KEY = re.compile(r"EV_KEY\s+(\w+)\s+(DOWN|UP)")
RE_SYN = re.compile(r"EV_SYN\s+SYN_REPORT")


def parse_line(line: str, st: State) -> bool:
    """返回 True 表示一个完整报告(SYN)结束。"""
    m = RE_ABS.search(line)
    if m:
        v = int(m.group(2), 16)
        if v >= 0x80000000:
            v -= 0x100000000
        st.raw[m.group(1)] = v
        return False
    m = RE_KEY.search(line)
    if m:
        st.keys[m.group(1)] = (m.group(2) == "DOWN")
        return False
    return bool(RE_SYN.search(line))


# ----------------------------------------------------------------------------
# 输出后端
# ----------------------------------------------------------------------------
class SerialOut:
    def __init__(self, port, baud):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0)

    def send(self, frame: bytes):
        self.ser.write(frame)


class UdpOut:
    def __init__(self, target):
        import socket
        host, port = target.rsplit(":", 1)
        self.addr = (host, int(port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, frame: bytes):
        self.sock.sendto(frame, self.addr)


class PrintOut:
    def __init__(self):
        self.last = 0

    def send(self, frame: bytes):
        now = time.time()
        if now - self.last < 0.1:
            return
        self.last = now
        st = CURRENT
        raw = " ".join(f"{a}={v}" for a, v in sorted(st.raw.items()))
        print(f"\r{raw}", end="", flush=True)


CURRENT = State()


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def run_replay(path, out):
    st = State()
    for line in open(path, encoding="utf-8", errors="ignore"):
        if parse_line(line, st):
            out.send(crsf_channels_frame(st.channels()))
    print("\n回放完成")


def run_live(out):
    """固定速率发送：摇杆不动也要持续出帧，否则飞控会判失控。"""
    import threading

    cmd = [CONFIG["adb"], "shell", f"getevent -lt {CONFIG['input_dev']}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            bufsize=1, universal_newlines=True, encoding="utf-8", errors="ignore",
                            creationflags=_NOWIN)

    stop = threading.Event()
    period = 1.0 / CONFIG["rate_hz"]

    def sender():
        nxt = time.time()
        while not stop.is_set():
            out.send(crsf_channels_frame(CURRENT.channels()))
            nxt += period
            sleep = nxt - time.time()
            if sleep > 0:
                time.sleep(sleep)
            else:
                nxt = time.time()          # 落后了就重新对齐，不累积漂移

    t = threading.Thread(target=sender, daemon=True)
    t.start()
    try:
        for line in proc.stdout:
            parse_line(line, CURRENT)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        t.join(timeout=1)
        proc.terminate()


def run_selftest(seconds=10):
    """摇杆自检：判断每个轴松手后是否自动回中。"""
    cmd = [CONFIG["adb"], "shell", f"getevent -lt {CONFIG['input_dev']}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            bufsize=1, universal_newlines=True, encoding="utf-8", errors="ignore",
                            creationflags=_NOWIN)
    st = State()
    import collections
    hist = collections.defaultdict(list)
    t0 = time.time()
    print(f"开始 {seconds} 秒自检：把每个摇杆推到底再松手，手离开不碰。")
    try:
        for line in proc.stdout:
            parse_line(line, st)
            for a, v in st.raw.items():
                hist[a].append(v)
            if time.time() - t0 > seconds:
                break
    finally:
        proc.terminate()

    print("\n轴         最小值    最大值    末值     判断")
    for a in ("ABS_X", "ABS_Y", "ABS_RX", "ABS_RY"):
        v = hist.get(a, [])
        if not v:
            print(f"{a:9s} 无数据")
            continue
        last = v[-1]
        verdict = "自动回中" if abs(last) < 3000 else f"不回中(停在 {last:+d})"
        print(f"{a:9s} {min(v):8d} {max(v):8d} {last:8d}   {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["live", "replay", "selftest"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--serial")
    ap.add_argument("--udp")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--seconds", type=int, default=10)
    a = ap.parse_args()

    if a.mode == "selftest":
        return run_selftest(a.seconds)

    if a.serial:
        out = SerialOut(a.serial, CONFIG["crsf_baud"])
    elif a.udp:
        out = UdpOut(a.udp)
    else:
        out = PrintOut()

    if a.mode == "replay":
        run_replay(a.file, out)
    else:
        run_live(out)


if __name__ == "__main__":
    main()
