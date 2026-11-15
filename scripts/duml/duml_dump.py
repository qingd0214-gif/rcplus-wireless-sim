"""把 DUML 0x06/0xAE 的完整 17 字节按时间顺序落盘，事后逐列对比。

用途：不知道某个开关对应哪一字节时，先录一段"某档位停住"的数据，
再逐列统计 —— 会"停住"的那一列才是档位，周期跳变的那列是状态/计数器。

用法：
  python duml_dump.py 30 out.txt      # 录 30 秒
  python duml_dump.py --analyze out.txt
"""
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("duml_wheel", HERE / "duml_wheel.py")
_dw = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_dw)

ADB = r"C:\tools\platform-tools\adb.exe"
SERIAL = "192.168.31.174:5555"


def ensure_link():
    import subprocess
    try:
        subprocess.run([ADB, "connect", SERIAL], capture_output=True, timeout=12)
        subprocess.run([ADB, "-s", SERIAL, "forward", "tcp:40007", "tcp:40007"],
                       capture_output=True, timeout=12)
    except Exception:
        pass


def record(secs, out):
    ensure_link()
    s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
    s.setblocking(False)
    seq, buf, t0 = 0, b"", time.time()
    rows = []
    fh = open(out, "w", encoding="utf-8")     # 边收边写：中途被 kill 也不丢数据
    print(f"录 {secs:.0f} 秒…", flush=True)
    while time.time() - t0 < secs:
        if seq % 4 == 0:
            try:
                s.sendall(_dw.keepalive(seq))
            except Exception:
                break
        seq += 1
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        except BlockingIOError:
            chunk = None
        except Exception:
            break
        fs, buf = _dw.split_frames(buf)
        for f in fs:
            if len(f) >= 28 and f[9] == 0x06 and f[10] == 0xAE:
                t = time.time() - t0
                h = f[11:28].hex()
                rows.append((t, h))
                fh.write(f"{t:8.3f} {h}\n")
        if fs:
            fh.flush()
        time.sleep(0.005 if chunk else 0.01)
    s.close()
    fh.close()
    print(f"{len(rows)} 包 → {out}", flush=True)
    return rows


def analyze(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        p = line.split()
        if len(p) == 2:
            rows.append((float(p[0]), p[1]))
    if not rows:
        print("空文件")
        return
    n = len(rows[0][1]) // 2
    print(f"{len(rows)} 包，{rows[-1][0]:.1f} 秒\n")
    print("列  取值数  取值分布（最多 6 个）        最大连续相同长度")
    for i in range(n):
        vals = [r[1][2 * i:2 * i + 2] for r in rows]
        uniq = sorted(set(vals))
        # 最长持续段：同一个值连续保持多久（按包数）
        best = cur = 1
        for j in range(1, len(vals)):
            cur = cur + 1 if vals[j] == vals[j - 1] else 1
            best = max(best, cur)
        flag = "  ← 会停住" if best >= 8 else ""
        print(f" {i:2d}   {len(uniq):4d}   {' '.join(uniq[:6]):28s} {best:5d}"
              f" ({best * 0.1:.1f}s){flag}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--analyze":
        analyze(sys.argv[2])
    else:
        secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
        out = sys.argv[2] if len(sys.argv) > 2 else "duml_dump.txt"
        record(secs, out)
        analyze(out)
