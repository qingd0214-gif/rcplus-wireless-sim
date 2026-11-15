"""延迟探针 v3：复现正式链路的三路流量，逐一定位挤停源。

  A 纯事件流                    —— 基线
  B 事件流 + DUML 心跳(forward) —— 仪表线程的流量画像
  C 事件流 + 一次 dumpsys       —— BatteryGuard 的画像
  D 事件流 + 心跳(5Hz 降频)     —— 验证降频是否有效

用法: python probe_latency3.py [serial]
"""
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time

ADB = r"C:\tools\platform-tools\adb.exe"
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
DEV = "/dev/input/event6"
FWD_PORT = 41007
TS_RE = re.compile(r"^\[\s*(\d+)\.(\d{6})\]")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "duml"))
from duml_wheel import keepalive  # noqa: E402


def sh(serial, *args, timeout=15):
    cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
    t = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return (time.monotonic() - t) * 1000, r.returncode


def ensure_forward(serial):
    sh(serial, "forward", f"tcp:{FWD_PORT}", "tcp:40007")


def stream_phase(serial, dur, label, duml_hz=None, dumpsys_at=None):
    print(f"\n--- 阶段 {label} ---", flush=True)
    events = []
    stop = threading.Event()
    fwd_sock = None

    def duml_writer():
        nonlocal fwd_sock
        if duml_hz is None:
            return
        interval = 1.0 / duml_hz
        seq = 0
        # 模拟 DumlWheel：先收发包试探，失败静默重试
        while not stop.is_set():
            try:
                if fwd_sock is None:
                    fwd_sock = socket.create_connection(("127.0.0.1", FWD_PORT), timeout=2)
                    fwd_sock.setblocking(False)
                while not stop.is_set():
                    try:
                        fwd_sock.sendall(keepalive(seq))
                        seq += 1
                    except (BlockingIOError, OSError):
                        pass
                    try:
                        fwd_sock.recv(4096)
                    except (BlockingIOError, ConnectionResetError):
                        pass
                    except OSError:
                        fwd_sock = None
                        break
                    time.sleep(interval)
            except OSError:
                time.sleep(0.5)

    def dumpsys_later():
        if dumpsys_at is None:
            return
        time.sleep(dumpsys_at)
        ms, rc = sh(serial, "shell", "dumpsys", "battery")
        print(f"   [dumpsys] 用时 {ms:.0f} ms", flush=True)

    threading.Thread(target=duml_writer, daemon=True).start()
    threading.Thread(target=dumpsys_later, daemon=True).start()

    proc = subprocess.Popen(
        [ADB] + (["-s", serial] if serial else []) + ["shell", f"getevent -lt {DEV}"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, bufsize=1, universal_newlines=True,
        encoding="utf-8", errors="ignore",
    )
    t0 = time.monotonic()
    for line in proc.stdout:
        now = time.monotonic()
        m = TS_RE.match(line)
        kts = int(m.group(1)) + int(m.group(2)) / 1e6 if m else None
        events.append((now, kts))
        if now - t0 >= dur:
            break
    stop.set()
    proc.terminate()
    if fwd_sock:
        try:
            fwd_sock.close()
        except OSError:
            pass
    time.sleep(0.5)
    return events, t0


def analyze(events, t0, label):
    if len(events) < 3:
        print("   事件太少")
        return
    d0 = None
    drift_max = 0.0
    for arrival, kts in events:
        if kts is None:
            continue
        d = arrival - kts
        if d0 is None:
            d0 = d
        drift_max = max(drift_max, d - d0)
    gaps = []
    for i in range(1, len(events)):
        g = (events[i][0] - events[i - 1][0]) * 1000
        if g > 60:
            kb, ka = events[i - 1][1], events[i][1]
            if kb is not None and ka is not None:
                kg = (ka - kb) * 1000
                verdict = "内核也断" if kg > 60 else "攒包!"
            else:
                verdict = "?"
            gaps.append((events[i][0] - t0, g, verdict))
    n_buf = sum(1 for _, _, v in gaps if v == "攒包!")
    print(f"\n=== {label}: {len(events)} 条 · "
          f"漂移 +{drift_max*1000:.0f} ms · 断档 {len(gaps)} 次（其中攒包 {n_buf}）===")
    for t, g, v in sorted(gaps, key=lambda x: -x[1])[:6]:
        print(f"   t={t:5.1f}s  {g:5.0f} ms  [{v}]")


def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else None
    if not serial:
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                serial = line.split("\t")[0].strip()
                break
    print(f"设备: {serial}")
    ensure_forward(serial)

    ev, t0 = stream_phase(serial, 8, "A 纯流", duml_hz=None)
    analyze(ev, t0, "A 纯流")

    ev, t0 = stream_phase(serial, 8, "B 心跳25Hz", duml_hz=25)
    analyze(ev, t0, "B 心跳25Hz")

    ev, t0 = stream_phase(serial, 8, "C dumpsys一次(第4秒)", dumpsys_at=4)
    analyze(ev, t0, "C dumpsys")

    ev, t0 = stream_phase(serial, 8, "D 心跳降频5Hz", duml_hz=5)
    analyze(ev, t0, "D 心跳降频5Hz")


if __name__ == "__main__":
    main()
