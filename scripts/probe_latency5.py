"""延迟探针 v5：A/B 对决——仪表线程(DumlWheel)开 vs 关。

关键指标:【内核级断档】(设备内核 >100ms 没生成摇杆事件)。
  阶段 A: DumlWheel 关,纯事件流
  阶段 B: DumlWheel 开(真实 start_wheel)
如果 B 的内核断档远多于 A → 设备端被 DUML 客户端拖慢,坐实。

用法: python probe_latency5.py [serial]
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
import dashboard  # noqa: E402


def capture(serial, dur):
    events = []
    proc = subprocess.Popen(
        [ADB, "-s", serial, "shell", f"getevent -lt {DEV}"],
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
    proc.terminate()
    return events, t0


def stats(events, t0, label, dur):
    if len(events) < 20:
        print(f"\n=== {label}: 事件太少({len(events)}),作废 ===")
        return None
    # 内核级断档: kts 间隔 >100ms
    k_gaps = []
    for i in range(1, len(events)):
        kb, ka = events[i-1][1], events[i][1]
        if kb and ka:
            kg = (ka - kb) * 1000
            if kg > 100:
                k_gaps.append(kg)
    # 传输漂移
    d0, drift_max = None, 0.0
    for a, k in events:
        if k is None:
            continue
        d = a - k
        if d0 is None:
            d0 = d
        drift_max = max(drift_max, d - d0)
    # 攒包
    n_buf = 0
    for i in range(1, len(events)):
        g = (events[i][0] - events[i-1][0]) * 1000
        kb, ka = events[i-1][1], events[i][1]
        if g > 60 and kb and ka and (ka - kb) < 0.06:
            n_buf += 1
    print(f"\n=== {label} ===")
    print(f"   事件 {len(events)} 条 · {len(events)/dur:.0f} 条/秒")
    print(f"   内核级断档(>100ms): {len(k_gaps)} 次" +
          (f"  最长 {max(k_gaps):.0f}ms  平均 {sum(k_gaps)/len(k_gaps):.0f}ms" if k_gaps else ""))
    print(f"   传输漂移 +{drift_max*1000:.0f} ms · 攒包 {n_buf} 次")
    return len(k_gaps)


def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else None
    if not serial:
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                serial = line.split("\t")[0].strip()
                break
    print(f"设备: {serial}")
    print(">>> 阶段 A 开始(12s)：请持续匀速画圈推杆 <<<<", flush=True)

    ev_a, t_a = capture(serial, 12)
    ka = stats(ev_a, t_a, "A: 仪表线程关", 12)

    print("\n>>> 启动仪表线程(DumlWheel)…", flush=True)
    dashboard.start_wheel(ADB, serial)
    time.sleep(3)
    print(">>> 阶段 B 开始(12s)：请继续画圈，节奏和刚才一致 <<<<", flush=True)

    ev_b, t_b = capture(serial, 12)
    kb = stats(ev_b, t_b, "B: 仪表线程开", 12)

    if ka is not None and kb is not None:
        print(f"\n=== 对决 ===")
        print(f"   内核断档 A(关)={ka}  B(开)={kb}", flush=True)
        if kb > ka * 2 and kb >= 3:
            print("   >>> B 显著更多: DUML 客户端拖慢设备端,坐实!")
        elif ka == 0 and kb == 0:
            print("   >>> 两阶段都干净: 仪表线程无罪,延迟另有原因")
        else:
            print("   >>> 差异不显著或 A 本身有断档(可能推杆停顿了),建议重跑")


if __name__ == "__main__":
    main()
