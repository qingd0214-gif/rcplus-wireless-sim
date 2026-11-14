"""测延迟用的小探针（一次性诊断，不参与正式链路）。

量三件事：
1. adb 单次命令往返（shell echo）——分辨 USB / WiFi 的基线差异
2. getevent 事件流的事件间隔分布（gap）——看抖动和"掉数据"
3. 心跳命令（shell true）执行期间，事件流是否被挤停

用法：python probe_latency.py [serial]
"""
import subprocess
import sys
import threading
import time

ADB = r"C:\tools\platform-tools\adb.exe"
import os
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
DEV = "/dev/input/event6"


def sh(serial, *args, timeout=15):
    cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
    t = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return (time.monotonic() - t) * 1000, r.returncode
    except subprocess.TimeoutExpired:
        return (time.monotonic() - t) * 1000, -1


def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else None
    if not serial:
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                serial = line.split("\t")[0].strip()
                break
    print(f"设备: {serial}  ({'无线' if ':' in (serial or '') else 'USB'})\n")

    # 1) 单次往返
    print("== 1) adb 单次命令往返 ==")
    for i in range(6):
        ms, rc = sh(serial, "shell", "echo", "hi")
        print(f"   shell echo  #{i+1}: {ms:7.1f} ms  rc={rc}")
    for i in range(3):
        ms, rc = sh(serial, "exec-out", "echo", "hi")
        print(f"   exec-out    #{i+1}: {ms:7.1f} ms  rc={rc}")

    # 2) 事件间隔 + 3) 心跳干扰
    print("\n== 2) 事件流间隔（12 秒，其中第 4~8 秒每 1.5s 发一次 shell true）==")
    stop = threading.Event()
    gaps = []
    events = [0]

    def heartbeat():
        time.sleep(4)
        while not stop.is_set():
            ms, rc = sh(serial, "shell", "true", timeout=10)
            print(f"   [心跳] shell true 用时 {ms:.0f} ms rc={rc}", flush=True)
            time.sleep(1.5)

    th = threading.Thread(target=heartbeat, daemon=True)
    th.start()

    proc = subprocess.Popen(
        [ADB] + (["-s", serial] if serial else []) + ["shell", f"getevent -lt {DEV}"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, bufsize=1, universal_newlines=True,
        encoding="utf-8", errors="ignore",
    )
    t_end = time.monotonic() + 12
    last = None
    t_proc = time.monotonic()
    for line in proc.stdout:
        now = time.monotonic()
        events[0] += 1
        if last is not None:
            gaps.append((now - last) * 1000)
        last = now
        if now >= t_end:
            break
    stop.set()
    proc.terminate()

    dur = time.monotonic() - t_proc
    gaps.sort()
    if gaps:
        p = lambda q: gaps[min(len(gaps) - 1, int(len(gaps) * q))]
        print(f"\n   时长 {dur:.1f}s · 事件 {events[0]} 条 · {events[0]/dur:.0f} 条/秒")
        print(f"   间隔 中位 {p(0.5):5.1f} ms | p90 {p(0.9):6.1f} | p99 {p(0.99):6.1f} "
              f"| 最大 {gaps[-1]:7.1f} ms")
        over = [g for g in gaps if g > 100]
        print(f"   >100ms 的断档 {len(over)} 次（这些就是游戏里'摇杆卡一下'）")
        if over:
            print(f"   最长几次: " + ", ".join(f"{g:.0f}ms" for g in sorted(over)[-5:]))


if __name__ == "__main__":
    main()
