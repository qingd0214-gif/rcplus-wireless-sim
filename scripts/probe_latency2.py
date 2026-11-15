"""延迟探针 v2：用内核时间戳区分「设备没出事件」vs「传输攒包」。

getevent -lt 每行开头是设备内核 uptime 时间戳。
对每条事件记录: arrival = PC 收到时刻, kts = 设备内核生成时刻。
  d = arrival - kts（随时间的变化量 = 传输延迟的变化）
  arrival gap 大但 kts 覆盖连续  ->  传输层攒包（元凶坐实）
  kts 也断                       ->  设备端确实没生成事件

两个阶段，各 8 秒：
  A: 纯事件流，不发任何命令
  B: 事件流 + 每 2 秒发一次 shell echo（测命令是否挤停事件流）

用法: python probe_latency2.py [serial]
"""
import os
import re
import subprocess
import sys
import threading
import time

ADB = r"C:\tools\platform-tools\adb.exe"
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
DEV = "/dev/input/event6"

TS_RE = re.compile(r"^\[\s*(\d+)\.(\d{6})\]")


def sh(serial, *args, timeout=15):
    cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
    t = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return (time.monotonic() - t) * 1000, r.returncode


def stream_phase(serial, dur, do_cmds, label):
    """跑一个阶段，返回事件列表 [(arrival, kts, raw)]"""
    print(f"\n--- 阶段 {label}（{dur} 秒, {'发命令' if do_cmds else '不发命令'}）---")
    events = []
    cmd_times = []
    stop = threading.Event()

    def commander():
        if not do_cmds:
            return
        time.sleep(2)
        while not stop.is_set():
            ms, rc = sh(serial, "shell", "echo", "hi", timeout=10)
            cmd_times.append((time.monotonic(), ms))
            print(f"   [cmd] shell echo {ms:.0f} ms", flush=True)
            time.sleep(2)

    th = threading.Thread(target=commander, daemon=True)
    th.start()

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
        if m:
            kts = int(m.group(1)) + int(m.group(2)) / 1e6
        else:
            kts = None
        events.append((now, kts, line.strip()))
        if now - t0 >= dur:
            break
    stop.set()
    proc.terminate()
    th.join(timeout=3)
    return events, cmd_times, t0


def analyze(events, cmd_times, t0, label):
    if len(events) < 3:
        print("   事件太少，跳过")
        return
    print(f"\n=== 阶段 {label} 分析 ===")
    print(f"   事件 {len(events)} 条 · {len(events)/8:.0f} 条/秒")

    # d = arrival - kts 的漂移（内核 uptime 与 PC 时钟起点不同，
    # 但 d 的【变化】= 传输延迟的变化，用相对第一个事件的漂移量）
    d0 = None
    drift_max = 0.0
    drift_at = 0.0
    for arrival, kts, _ in events:
        if kts is None:
            continue
        d = arrival - kts
        if d0 is None:
            d0 = d
        rel = d - d0
        if rel > drift_max:
            drift_max, drift_at = rel, arrival - t0
    print(f"   传输延迟漂移: 最大 +{drift_max*1000:.0f} ms（出现在 t={drift_at:.1f}s）")
    print(f"   （>0 表示数据被攒住，之后一次性吐出；完整排空时回落）")

    # arrival gap 分布
    gaps = []
    for i in range(1, len(events)):
        g = (events[i][0] - events[i-1][0]) * 1000
        if g > 60:
            gaps.append((events[i][0] - t0, g, i))
    gaps.sort(key=lambda x: -x[1])
    print(f"   arrival 断档(>60ms): {len(gaps)} 次")
    for t, g, i in gaps[:8]:
        # 这个 gap 期间内核产生了几个事件？内核间隔如何？
        k_before = events[i-1][1]
        k_after = events[i][1]
        if k_before is not None and k_after is not None:
            kgap = (k_after - k_before) * 1000
            verdict = "内核也断(设备没出)" if kgap > 60 else f"内核连续(kgap {kgap:.0f}ms) → 攒包!"
        else:
            verdict = "?"
        print(f"   t={t:5.1f}s  断档 {g:5.0f} ms  [{verdict}]")

    # 命令与断档的相关性
    if cmd_times:
        near = sum(1 for t, g, _ in gaps if any(abs(t - (ct - t0)) < 1.0 for ct, _ in cmd_times))
        print(f"   命令后 1 秒内出现断档: {near}/{len(cmd_times)} 次" + ("" if not gaps else f"（断档共 {len(gaps)} 次）"))


def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else None
    if not serial:
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                serial = line.split("\t")[0].strip()
                break
    print(f"设备: {serial}")

    ev_a, cmd_a, t0_a = stream_phase(serial, 8, False, "A 纯流")
    analyze(ev_a, cmd_a, t0_a, "A")

    ev_b, cmd_b, t0_b = stream_phase(serial, 8, True, "B 命令干扰")
    analyze(ev_b, cmd_b, t0_b, "B")


if __name__ == "__main__":
    main()
