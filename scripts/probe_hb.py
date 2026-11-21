# -*- coding: utf-8 -*-
"""心跳降频实验：测出 DUML 服务的真实心跳下限。

对每个心跳间隔，连上 40007、以该间隔发心跳、统计遥测包(0x06 0xAE)
到达速率。若遥测依旧 10 包/s 说明会话活着；掉到 0 说明被踢/断了。
"""
import socket, time, sys, subprocess, importlib.util

HERE = r"C:\Users\Administrator\WorkBuddy\2026-11-05-03-00-04\rcplus"
ADB = r"C:\tools\platform-tools\adb.exe"
spec = importlib.util.spec_from_file_location("duml_wheel", HERE + r"\duml\duml_wheel.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def setup_forward():
    subprocess.run([ADB, "connect", "192.168.31.174:5555"],
                   capture_output=True, timeout=10)
    subprocess.run([ADB, "forward", "tcp:40007", "tcp:40007"],
                   capture_output=True, timeout=10)

def run_interval(hb_ms, seconds=10.0):
    s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
    s.setblocking(False)
    buf = b""
    pkts = 0
    seq = 0
    last_hb = 0.0
    t0 = time.monotonic()
    rate_samples = []
    window_t0, window_pkts = t0, 0
    while time.monotonic() - t0 < seconds:
        now = time.monotonic()
        if now - last_hb >= hb_ms / 1000.0:
            try:
                s.sendall(mod.keepalive(seq))
                seq += 1
                last_hb = now
            except Exception as e:
                print(f"  send fail: {e}")
                break
        try:
            chunk = s.recv(4096)
            if not chunk:
                print("  连接被远端关闭")
                break
            buf += chunk
        except BlockingIOError:
            chunk = None
        except Exception as e:
            print(f"  recv fail: {e}")
            break
        frames, buf = mod.split_frames(buf)
        for f in frames:
            if len(f) >= 28 and f[9] == 0x06 and f[10] == 0xAE:
                pkts += 1
                window_pkts += 1
        if now - window_t0 >= 2.0:
            rate_samples.append(window_pkts / (now - window_t0))
            window_t0, window_pkts = now, 0
        time.sleep(0.005 if chunk else 0.008)
    s.close()
    return pkts / seconds, rate_samples

setup_forward()
print("遥控器:", end=" ")
r = subprocess.run([ADB, "devices"], capture_output=True, timeout=10)
print(r.stdout.decode(errors="ignore").strip().splitlines()[1] if len(r.stdout.decode(errors='ignore').strip().splitlines()) > 1 else "?")

for hb in (40, 100, 200, 500, 1000):
    try:
        rate, samples = run_interval(hb)
        s_txt = "  ".join(f"{x:.1f}" for x in samples)
        verdict = "OK 会话活" if rate > 3 else ("弱" if rate > 0.5 else "断流")
        print(f"心跳 {hb:5d}ms  遥测平均 {rate:5.1f} 包/s  [{s_txt}]  -> {verdict}")
    except Exception as e:
        print(f"心跳 {hb:5d}ms  异常: {e}")
    time.sleep(1.5)
