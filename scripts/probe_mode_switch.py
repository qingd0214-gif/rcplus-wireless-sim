"""飞行模式拨杆（F/S/N 三档）探测：evdev 和 DUML 两条路同时盯。

用法：
  python probe_mode_switch.py 180 [serial]

输出两类行：
  [EV]   <节点> <类型> <码> <值>     —— evdev 有任何动静
  [DUML] byte2=0x02                 —— DUML 状态包头部的档位字节变化时
盯 180 秒，期间把拨杆来回拨到每个档位，停一秒再换下一个档位。
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))          # rcplus/，让 dashboard 的加载逻辑可用

ADB = r"C:\tools\platform-tools\adb.exe"
MAGIC = b"\x55\xcc\x30\x75"

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("duml_wheel", HERE / "duml" / "duml_wheel.py")
_dw = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_dw)


def frames(buf):
    out, off = [], 0
    while True:
        i = buf.find(MAGIC, off)
        if i < 0 or i + 8 > len(buf):
            return out, (buf[max(off, len(buf) - 3):] if i < 0 else buf[i:])
        plen = int.from_bytes(buf[i + 4:i + 8], "little")
        if i + 8 + plen > len(buf):
            return out, buf[i:]
        out.append(buf[i + 8:i + 8 + plen])
        off = i + 8 + plen


t0 = time.time()
lock = threading.Lock()
last_duml = {"b2": None, "at": 0.0}


def _adb(*args, timeout=12):
    try:
        return subprocess.run([ADB] + list(args), capture_output=True,
                              timeout=timeout)
    except Exception:
        return None


def ensure_link(serial):
    """adb server 被回收/重启后「已连接」状态会丢，必须补 connect 再 forward。"""
    if serial and ":" in serial:
        _adb("connect", serial)
    r = _adb("-s", serial, "forward", "tcp:40007", "tcp:40007")
    return r is not None and r.returncode == 0


def duml_thread(serial):
    seq = 0
    buf = b""
    s = None
    while True:
        try:
            import socket
            if s is None:
                ensure_link(serial)
                s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
                s.setblocking(False)
                print(f"[{time.time()-t0:7.2f}s] [DUML] 隧道已建立", flush=True)
            if seq % 4 == 0:
                try:
                    s.sendall(_dw.keepalive(seq))
                except Exception:
                    s.close(); s = None; seq = 0
                    time.sleep(1.0); continue
            seq += 1
            try:
                chunk = s.recv(4096)
                if not chunk:
                    raise ConnectionError("closed")
                buf += chunk
            except BlockingIOError:
                chunk = None
            except Exception:
                s.close(); s = None; seq = 0
                time.sleep(1.0); continue
            fs, buf = frames(buf)
            for f in fs:
                if len(f) >= 28 and f[9] == 0x06 and f[10] == 0xAE:
                    b2 = f[13]          # 状态数据从 f[11] 起，byte2 = f[13]
                    with lock:
                        changed = b2 != last_duml["b2"]
                        last_duml["b2"], last_duml["at"] = b2, time.time()
                    if changed:
                        print(f"[{time.time()-t0:7.2f}s] [DUML] byte2 = "
                              f"0x{b2:02x}", flush=True)
            time.sleep(0.005 if chunk else 0.01)
        except Exception as e:
            print(f"[{time.time()-t0:7.2f}s] [DUML] 断线：{e}（2s 后重试）",
                  flush=True)
            time.sleep(2.0)
            s = None


def evdev_thread(serial):
    # 不指定设备 = 盯全部 7 个节点。拨杆如果在任何一路走 evdev，都会被抓住。
    cmd = [ADB, "-s", serial, "shell",
           "getevent -lt & while true; do echo __HB__; sleep 2; done"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True,
                         errors="replace", bufsize=1)
    last_beat = time.time()
    for line in p.stdout:
        line = line.rstrip()
        if "__HB__" in line:
            last_beat = time.time()
            continue
        if not line:
            continue
        # 过滤噪声：SYN 行、以及 event6 的轴抖动（油门轴静止时也在 ±0x60 抖）
        if "SYN_REPORT" in line:
            continue
        if "/dev/input/event6" in line and "EV_ABS" in line:
            continue
        print(f"[{time.time()-t0:7.2f}s] [EV  ] {line}", flush=True)


def sample_thread(every=2.0):
    """每秒采样一次当前 byte2 —— 只看变化看不出"停在哪一档"，必须看静止值。"""
    while True:
        time.sleep(every)
        with lock:
            v = last_duml["b2"]
        print(f"[{time.time()-t0:7.2f}s] [采样] byte2 = "
              f"{'?' if v is None else f'0x{v:02x}'}", flush=True)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 180
    serial = sys.argv[2] if len(sys.argv) > 2 else "192.168.31.174:5555"
    ensure_link(serial)                      # 先把链路立起来，别让两个线程各撞各的
    threading.Thread(target=duml_thread, args=(serial,), daemon=True).start()
    threading.Thread(target=evdev_thread, args=(serial,), daemon=True).start()
    threading.Thread(target=sample_thread, daemon=True).start()
    print(f"盯 {secs:.0f} 秒", flush=True)
    print("请按这个顺序：【F 停 3 秒】→【S 停 3 秒】→【N 停 3 秒】，"
          "最后停在 N。中间不要碰摇杆/拨轮。", flush=True)
    end = time.time() + secs
    prev = None
    while time.time() < end:
        time.sleep(0.5)
    print("结束", flush=True)


if __name__ == "__main__":
    main()
