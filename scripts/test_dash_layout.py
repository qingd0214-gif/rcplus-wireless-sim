"""仪表页布局自检：假数据 + 延迟在 1~3 位数之间跳，截图对比布局是否稳定。"""
import os
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\WorkBuddy\2026-11-05-03-00-04\rcplus")
import dashboard  # noqa: E402

_seq = [3, 12, 128, 5, 240, 999]
_i = {"n": 0}


def snap():
    lat = _seq[int(time.time() / 1.5) % len(_seq)]     # 每 1.5 秒换一个位数
    return {"thr": 0.42, "yaw": 0.1, "roll": -0.2, "pitch": 0.3,
            "dl": 0.6, "dr": -0.35, "hx": 0, "hy": 0,
            "btns": ["KEY_F1", "BTN_TL"], "wd": 1, "ws": 3, "md": "S",
            "lat": lat, "eps": 220}


if __name__ == "__main__":
    dashboard.start_server(snap, 8798)
    print("serving on 8798", flush=True)
    time.sleep(900)
