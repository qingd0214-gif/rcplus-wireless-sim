"""延迟探针 v4：完整复刻正式链路，测真实配置下的传输漂移。

组成 = rcplus_sim 的真实配置：
  - getevent 事件流（常驻，带内核时间戳）
  - DumlWheel 仪表线程（25Hz DUML 心跳）
  - BatteryGuard（每 120s 一次 dumpsys，15 秒窗口内不会触发）

用法: python probe_latency4.py [serial] [秒数]
"""
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ADB = r"C:\tools\platform-tools\adb.exe"
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
DEV = "/dev/input/event6"
TS_RE = re.compile(r"^\[\s*(\d+)\.(\d{6})\]")

sys.path.insert(0, HERE)
import dashboard  # noqa: E402  提供 start_wheel


def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else None
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 20
    if not serial:
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                serial = line.split("\t")[0].strip()
                break
    print(f"设备: {serial} · 窗口 {secs:.0f}s · 配置=正式链路复刻\n")

    # 1) 仪表线程（真实 DumlWheel）
    dashboard.start_wheel(ADB, serial)
    time.sleep(1.5)

    # 2) 事件流 + 逐事件记 (arrival, kts)
    events = []
    proc = subprocess.Popen(
        [ADB, "-s", serial, "shell", f"getevent -lt {DEV}"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, bufsize=1, universal_newlines=True,
        encoding="utf-8", errors="ignore",
    )
    t0 = time.monotonic()

    def reporter():
        while time.monotonic() - t0 < secs:
            time.sleep(2)
            if not events:
                continue
            n = len(events)
            d0 = None
            drift = 0.0
            for a, k in events:
                if k is None:
                    continue
                d = a - k
                if d0 is None:
                    d0 = d
                drift = max(drift, d - d0)
            print(f"   t={time.monotonic()-t0:5.1f}s  事件 {n:5d}  漂移 +{drift*1000:4.0f} ms",
                  flush=True)

    threading.Thread(target=reporter, daemon=True).start()
    for line in proc.stdout:
        now = time.monotonic()
        m = TS_RE.match(line)
        kts = int(m.group(1)) + int(m.group(2)) / 1e6 if m else None
        events.append((now, kts))
        if now - t0 >= secs:
            break
    proc.terminate()

    # 3) 汇总
    if len(events) < 3:
        print("事件太少——期间没推杆？")
        return
    d0 = None
    drift_max = 0.0
    for a, k in events:
        if k is None:
            continue
        d = a - k
        if d0 is None:
            d0 = d
        drift_max = max(drift_max, d - d0)
    gaps = []
    for i in range(1, len(events)):
        g = (events[i][0] - events[i-1][0]) * 1000
        if g > 60:
            kb, ka = events[i-1][1], events[i][1]
            verdict = "攒包!" if (kb and ka and ka - kb < 0.06) else "内核也断"
            gaps.append((events[i][0] - t0, g, verdict))
    n_buf = sum(1 for _, _, v in gaps if v == "攒包!")
    print(f"\n=== 汇总 ===")
    print(f"   事件 {len(events)} 条 · {len(events)/secs:.0f} 条/秒")
    print(f"   传输漂移最大 +{drift_max*1000:.0f} ms")
    print(f"   >60ms 断档 {len(gaps)} 次（攒包 {n_buf}）")
    for t, g, v in sorted(gaps, key=lambda x: -x[1])[:8]:
        print(f"   t={t:5.1f}s  {g:5.0f} ms  [{v}]")


if __name__ == "__main__":
    main()
