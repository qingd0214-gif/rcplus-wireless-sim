"""验证 wheel 线程 start/stop 往返：连接、收包、断开后端口真的释放。"""
import os
import time

os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
import dashboard

ADB = r"C:\tools\platform-tools\adb.exe"
SERIAL = "192.168.31.174:5555"

print("== start_wheel ==")
dashboard.start_wheel(ADB, SERIAL, verbose=True)
time.sleep(3)
w = dashboard._wheel
print(f"running={dashboard.wheel_running()}  快照={dashboard.wheel_snapshot()}")
if w is not None:
    print(f"DUML 收包 {getattr(w, 'pkts', '?')}……")
    time.sleep(2)
    print(f"DUML 收包 {getattr(w, 'pkts', '?')}")
    th = dashboard._wheel_thread
    print(f"线程 socket 状态: connected={getattr(th, 'connected', None)}")

print("\n== stop_wheel ==")
t0 = time.time()
dashboard.stop_wheel()
print(f"stop 用时 {time.time()-t0:.2f}s  running={dashboard.wheel_running()}"
      f"  快照={dashboard.wheel_snapshot()}")

print("\n== 再 start（模拟游戏再次启动）==")
dashboard.start_wheel(ADB, SERIAL)
time.sleep(2)
print(f"running={dashboard.wheel_running()}")
dashboard.stop_wheel()
print(f"final running={dashboard.wheel_running()}")
print("PASS" if not dashboard.wheel_running() else "FAIL")
