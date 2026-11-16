#!/usr/bin/env python3
"""
stick_screen.py — 遥控器屏幕上的摇杆仪表（独立入口）

一般不用它：手柄脚本（rcplus_sim.py）里已经内置了同一个仪表服务，
双击「RC Plus 手柄」后遥控器浏览器打开 http://<PC_IP>:8123 即可。
这个独立入口用于【不开手柄脚本、只看仪表】的场景。

用法:
    python stick_screen.py                # 连遥控器（自动选设备）
    python stick_screen.py --fake         # 假数据调试页面
Ctrl+C 退出。
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import dashboard                              # noqa: E402
import rcplus_sim as R                        # noqa: E402  (RcReader/KeepAwake/norm)
from rcplus_bridge import CONFIG, State       # noqa: E402

PORT = dashboard.PORT


def main():
    ap = argparse.ArgumentParser(description="遥控器屏幕上的摇杆仪表（独立入口）")
    ap.add_argument("--adb", default=CONFIG["adb"])
    ap.add_argument("--device", default=CONFIG["input_dev"])
    ap.add_argument("--wifi", help="遥控器 IP")
    ap.add_argument("--serial", help="adb -s 串号")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--fake", action="store_true", help="不连遥控器，用假数据调试")
    ap.add_argument("--no-wheel", action="store_true",
                    help="不读第三拨轮（右拨轮下方那个不回中的）")
    a = ap.parse_args()

    st = State()
    st.raw.update(R.AXIS_DEFAULTS)
    readers = []

    if a.fake:
        import math

        def fake():
            ph = 0.0
            while True:
                ph += 0.05
                st.raw["ABS_X"] = int(32000 * math.sin(ph))
                st.raw["ABS_Y"] = int(30000 * math.sin(ph * 0.7))
                st.raw["ABS_RX"] = int(32000 * math.cos(ph * 1.1))
                st.raw["ABS_RY"] = int(30000 * math.cos(ph * 0.9))
                time.sleep(0.02)
        import threading
        threading.Thread(target=fake, daemon=True).start()
        print("== 假数据模式 ==")
        serial = None
    else:
        serial = R.adb_preflight(a.adb, wifi=bool(a.wifi))
        if not serial:
            print("[!] 遥控器没连上。可加 --wifi 遥控器IP")
            return 2
        for dev in sorted({a.device, R.BUTTON_DEV}):
            r = R.RcReader(a.adb, dev, st, None, serial)
            r.start()
            readers.append(r)
        awaker = R.KeepAwake(a.adb, serial)   # 屏幕不休眠，事件流才不会断
        awaker.prepare()
        awaker.start()
        print(f"遥控器已连接({serial}) · 数据读 {a.device}")

    def snapshot():
        raw = st.raw
        # 与 rcplus_sim._dash_snapshot 同一套显示符号：油门/俯仰取反
        snap = {"thr": round(-R.norm(raw.get("ABS_Y", R.THROTTLE_LO),
                                        R.THROTTLE_LO, 0, 32767), 3),
                "yaw": round(R.norm(raw.get("ABS_X", 0), -32768, 0, 32767), 3),
                "roll": round(R.norm(raw.get("ABS_RX", 0), -32768, 0, 32767), 3),
                "pitch": round(-R.norm(raw.get("ABS_RY", 0), -32768, 0, 32767), 3),
                "dl": round(R.norm(raw.get("ABS_Z", 127), 0, 127, 255), 3),
                "dr": round(R.norm(raw.get("ABS_RZ", 127), 0, 127, 255), 3),
                "hx": raw.get("ABS_HAT0X", 0), "hy": raw.get("ABS_HAT0Y", 0),
                "btns": sorted(k for k, v in st.keys.items() if v),
                # 第三拨轮（只在 DUML 里）：{"wd": 方向, "ws": 速度档}
                **dashboard.wheel_snapshot()}
        # 实时摇杆链路延迟（同 rcplus_sim._dash_snapshot）。
        # 必须选摇杆节点的 reader（readers 按路径排序，event4 在前）。
        rd = next((r for r in readers if getattr(r, "device", "") == a.device), None)
        if rd is not None and getattr(rd, "latency_ms", None) is not None:
            snap["lat"] = int(round(rd.latency_ms))
            snap["eps"] = round(rd.eps, 1)
        return snap

    if not a.no_wheel:
        dashboard.start_wheel(a.adb, serial)
        print("[i] 仪表已连 DUML（滚轮/FSN 可用）。注意：本工具是常驻连接，")
        print("    要遥控飞机请先关掉它 —— 飞行时它会和飞行链路抢遥控器。")

    url = f"http://{dashboard.local_ip()}:{a.port}"
    try:
        dashboard.start_server(snapshot, a.port)
    except OSError:
        print(f"[i] 端口 {a.port} 已被占用 —— 手柄脚本里已开着同一个仪表，直接用它即可。")
        print(f"    地址: {url}")

    print(f"\n★ 仪表屏地址: {url}")

    # 在遥控器上拉起 Firefox（拿不到串号就让用户手动开浏览器输地址）
    if not a.fake and readers:
        import subprocess
        r = subprocess.run(
            [a.adb, "-s", readers[0].serial or serial or "", "shell",
             f"am start -a android.intent.action.VIEW -d '{url}' org.mozilla.firefox"],
            capture_output=True, timeout=20)
        if r.returncode == 0:
            print("★ 已在遥控器上打开 Firefox。")
        else:
            print("[!] 自动打开 Firefox 失败，请在遥控器浏览器里手动输入上面的地址。")

    print("\n提示：在 Firefox 菜单里选【添加到主屏幕】，遥控器桌面就有了仪表图标。")
    print("Ctrl+C 退出。\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n退出。")
    finally:
        for r in readers:
            r.stop.set()
            r.kill_proc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
