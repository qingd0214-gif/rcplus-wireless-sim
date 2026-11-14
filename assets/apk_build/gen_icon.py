#!/usr/bin/env python3
"""gen_icon.py — 纯 Python 生成应用图标 PNG（深色圆角底 + 双摇杆绿点）。"""

import struct
import sys
import zlib

W = H = 192


def in_rounded(x, y, r=28):
    # 圆角矩形判定（48px 圆角半径缩放）
    rad = 40
    if x < rad and y < rad:
        return (x - rad) ** 2 + (y - rad) ** 2 <= rad ** 2
    if x > W - rad and y < rad:
        return (x - (W - rad)) ** 2 + (y - rad) ** 2 <= rad ** 2
    if x < rad and y > H - rad:
        return (x - rad) ** 2 + (y - (H - rad)) ** 2 <= rad ** 2
    if x > W - rad and y > H - rad:
        return (x - (W - rad)) ** 2 + (y - (H - rad)) ** 2 <= rad ** 2
    return True


def px(x, y):
    # 背景 #0b0f12
    r, g, b, a = 0x0B, 0x0F, 0x12, 255
    if not in_rounded(x, y):
        return (0, 0, 0, 0)
    # 主摇杆点：圆心 (74, 78) 半径 34 绿色 #4cd97b，带一点柔边
    for cx, cy, rad, col in ((74, 78, 34, (0x4C, 0xD9, 0x7B)),
                             (126, 112, 24, (0x2C, 0x8F, 0x5B))):
        d2 = (x - cx) ** 2 + (y - cy) ** 2
        if d2 <= (rad - 2) ** 2:
            r, g, b = col
        elif d2 <= (rad + 2) ** 2:          # 2px 抗锯齿边
            t = 1 - (d2 ** 0.5 - (rad - 2)) / 4
            if t > 0:
                r = int(r * (1 - t) + col[0] * t)
                g = int(g * (1 - t) + col[1] * t)
                b = int(b * (1 - t) + col[2] * t)
    return (r, g, b, a)


def main(path):
    raw = b"".join(b"\x00" + bytes(
        v for x in range(W) for v in px(x, y)) for y in range(H))
    idat = zlib.compress(raw, 9)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    open(path, "wb").write(png)
    print("icon saved:", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ic.png")
