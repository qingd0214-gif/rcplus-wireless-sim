"""录 DUML 上【所有】报文，事后按报文类型逐字节找"会停住的列"。

为什么需要：0x06/0xAE 状态包里没有飞行模式档位（实测 17 字节里只有
左杆抖动的 col9 和每秒自跳的 col2 在变）。档位若真被本地上报，
一定在别的 cmd_set/cmd_id 里，需要"停在某档"的静态数据才能认出来。

用法：
  python duml_frames.py 90 cap.txt        录 90 秒（边收边写）
  python duml_frames.py --analyze cap.txt 逐字节分析
"""
import collections
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


def record(secs, out):
    import subprocess
    try:
        subprocess.run([ADB, "connect", SERIAL], capture_output=True, timeout=12)
        subprocess.run([ADB, "-s", SERIAL, "forward", "tcp:40007", "tcp:40007"],
                       capture_output=True, timeout=12)
    except Exception:
        pass

    s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
    s.setblocking(False)
    seq, buf, t0, n = 0, b"", time.time(), 0
    fh = open(out, "w", encoding="utf-8")
    print(f"录 {secs:.0f} 秒…", flush=True)
    while time.time() - t0 < secs:
        if seq % 4 == 0:
            try:
                s.sendall(_dw.keepalive(seq))
            except Exception:
                break
        seq += 1
        try:
            chunk = s.recv(8192)
            if not chunk:
                break
            buf += chunk
        except BlockingIOError:
            chunk = None
        except Exception:
            break
        fs, buf = _dw.split_frames(buf)
        for f in fs:
            if len(f) < 11:
                continue
            # 只存 cmd_set/cmd_id + 数据（丢掉 seq，否则每条都"唯一"）
            fh.write(f"{time.time()-t0:8.3f} {f[9]:02x}{f[10]:02x} {f[11:].hex()}\n")
            n += 1
        if fs:
            fh.flush()
        time.sleep(0.005 if chunk else 0.01)
    s.close()
    fh.close()
    print(f"{n} 条 → {out}", flush=True)


def analyze(path, only=None):
    by_type = collections.defaultdict(list)        # type -> [(t, data_hex)]
    for line in open(path, encoding="utf-8"):
        p = line.split()
        if len(p) != 3:
            continue
        t, typ, data = float(p[0]), p[1], p[2]
        if only and typ != only:
            continue
        by_type[typ].append((t, data))

    print(f"{len(by_type)} 种报文\n")
    for typ, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < 5:
            continue
        n = min(len(r[1]) // 2 for r in rows)
        cols = []
        for i in range(n):
            vals = [r[1][2 * i:2 * i + 2] for r in rows]
            uniq = sorted(set(vals))
            if len(uniq) < 2:
                continue
            best = cur = 1
            for j in range(1, len(vals)):
                cur = cur + 1 if vals[j] == vals[j - 1] else 1
                best = max(best, cur)
            cols.append((i, len(uniq), best, uniq[:6]))
        if not cols:
            print(f"  0x{typ[:2]}/{typ[2:]}  {len(rows):4d} 条  全部字节静止")
            continue
        # 只看"能停住 >=15 包(约1.5s)"的列：档位是这种特征
        held = [c for c in cols if c[2] >= 15]
        print(f"  0x{typ[:2]}/{typ[2:]}  {len(rows):4d} 条  变动列 {len(cols)} 个"
              f"，其中会停住的 {len(held)} 个")
        for i, k, best, uniq in held[:8]:
            print(f"       col{i:2d}  {k} 种  {' '.join(uniq):20s} 最长停 {best} 包")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--analyze":
        analyze(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        record(float(sys.argv[1]) if len(sys.argv) > 1 else 90,
               sys.argv[2] if len(sys.argv) > 2 else "frames.txt")
