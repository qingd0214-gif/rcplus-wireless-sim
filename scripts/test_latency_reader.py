"""验证 RcReader 的实时延迟统计（只读，几秒）。"""
import os
import sys
import time

os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
sys.path.insert(0, r"C:\Users\Administrator\WorkBuddy\2026-11-05-03-00-04\rcplus")
import rcplus_sim as R  # noqa: E402

st = R.State()
r = R.RcReader(r"C:\tools\platform-tools\adb.exe", "/dev/input/event6",
               st, None, "192.168.31.174:5555")
r.start()
for i in range(8):
    time.sleep(1)
    print(f"t={i+1}s  latency={r.latency_ms}  eps={r.eps:.1f}  "
          f"samples={len(r._delays)}  ABS_Y={st.raw.get('ABS_Y')}")
r.stop.set()
r.kill_proc()
