"""清点 DUML 上到底有哪些报文在流动 —— 找"某开关走哪条报文"的第一步。

列出 (cmd_set, cmd_id) 组合、载荷长度、出现次数、载荷是否有变化。
"""
import socket
import sys
import time
import collections
from pathlib import Path

HERE = Path(__file__).parent
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("duml_wheel", HERE / "duml_wheel.py")
_dw = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_dw)

ADB = r"C:\tools\platform-tools\adb.exe"
SERIAL = "192.168.31.174:5555"


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    import subprocess
    try:
        subprocess.run([ADB, "connect", SERIAL], capture_output=True, timeout=12)
        subprocess.run([ADB, "-s", SERIAL, "forward", "tcp:40007", "tcp:40007"],
                       capture_output=True, timeout=12)
    except Exception:
        pass

    s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
    s.setblocking(False)
    seq, buf, t0 = 0, b"", time.time()
    seen = collections.OrderedDict()      # (set,id) -> [count, lens, sample, distinct]
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
            key = (f[9], f[10])
            rec = seen.setdefault(key, {"n": 0, "lens": collections.Counter(),
                                        "samples": [], "distinct": set()})
            rec["n"] += 1
            rec["lens"][len(f)] += 1
            rec["distinct"].add(bytes(f[11:]))
            if len(rec["samples"]) < 3:
                rec["samples"].append(bytes(f).hex())
        time.sleep(0.005 if chunk else 0.01)
    s.close()

    print(f"\n{secs:.0f} 秒内收到的报文类型：\n")
    print(f"{'set/id':>10}  {'次数':>5}  {'版本/长度':>12}  {'载荷种类':>8}  样例")
    for (cs, ci), r in sorted(seen.items(), key=lambda kv: -kv[1]["n"]):
        lens = "/".join(str(x) for x in r["lens"])
        print(f"  0x{cs:02x}/0x{ci:02x}  {r['n']:5d}  {lens:>12}  "
              f"{len(r['distinct']):8d}  {r['samples'][0][:60]}")
    print("\n载荷种类 > 1 的报文 = 每秒都在变；只有 1 种 = 静态。"
          "\n拨动开关时若某条报文从 1 种变成多种，那条就是它。")


if __name__ == "__main__":
    main()
