"""验证：持续 PC→遥控器 流量能否抑制 WiFi 省电休眠（从而降 RTT）。

对照组：不发包 → ping 平均 ~53-71ms（射频在睡，等 beacon 唤醒）
实验组：每秒 200 个小 UDP 包 → 看 ping 是否降到个位数

用法：python probe_radio.py [ip]
"""
import re
import socket
import subprocess
import sys
import threading
import time

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.31.174"


def ping_stats(n=25):
    """跑 n 次 ping，返回 (min, avg, max, 超过50ms的个数)。"""
    out = subprocess.run(["ping", "-n", str(n), "-w", "1000", IP],
                         capture_output=True, text=True, errors="ignore").stdout
    # 中文 Windows 输出：最短 = 1ms，最长 = 123ms，平均 = 53ms
    nums = [int(x) for x in re.findall(r"[=＝]\s*(\d+)\s*ms", out)]
    if not nums:
        # 英文格式 fallback
        t = re.search(r"Minimum = (\d+)ms, Maximum = (\d+)ms, Average = (\d+)ms", out)
        if t:
            nums = [int(t.group(1)), int(t.group(3)), int(t.group(2))]
    if not nums:
        print(out)
        return None
    lo, hi = min(nums), max(nums)
    avg = nums[-1] if len(nums) >= 3 else sum(nums) // len(nums)

    # 逐包时间（中文：时间=53ms / 时间<1ms）
    samples = [int(x) for x in re.findall(r"时间[=<](\d+)ms", out)]
    over50 = sum(1 for s in samples if s > 50) if samples else -1
    return lo, avg, hi, over50, len(samples)


def spam(stop, rate=200):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    payload = b"x" * 24
    t0 = time.monotonic()
    n = 0
    while not stop.is_set():
        try:
            s.sendto(payload, (IP, 9998))
            n += 1
        except Exception:
            pass
        nxt = t0 + n / rate
        d = nxt - time.monotonic()
        if d > 0:
            time.sleep(d)
    s.close()
    return n


def main():
    print(f"目标: {IP}\n")

    print("== 对照组：不发包 ==")
    r = ping_stats()
    if r:
        print(f"   最短 {r[0]}ms · 平均 {r[1]}ms · 最长 {r[2]}ms "
              f"· >50ms 有 {r[3]}/{r[4]} 个")

    print("\n== 实验组：每秒 200 个 UDP 包 ==")
    stop = threading.Event()
    th = threading.Thread(target=spam, args=(stop,), daemon=True)
    th.start()
    time.sleep(1.0)
    r2 = ping_stats()
    stop.set()
    if r2:
        print(f"   最短 {r2[0]}ms · 平均 {r2[1]}ms · 最长 {r2[2]}ms "
              f"· >50ms 有 {r2[3]}/{r2[4]} 个")

    if r and r2:
        print("\n== 结论 ==")
        if r2[1] < r[1] * 0.6:
            print(f"   流量能显著压低 RTT（{r[1]}ms → {r2[1]}ms）：省电休眠是主因，"
                  f"可以用持续心跳解决。")
        else:
            print(f"   流量压不下去（{r[1]}ms → {r2[1]}ms）：射频休眠由 AP 的 "
                  f"DTIM/信标驱动，客户端侧改不了，得换传输方案。")


if __name__ == "__main__":
    main()
