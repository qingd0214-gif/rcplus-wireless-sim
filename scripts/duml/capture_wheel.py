"""盯 0x06/0xAE 状态包，抓"右上滚轮"（byte 4）到底有没有数据。

用法：python capture_wheel.py [秒数] [输出文件]
录制期间让用户拨动那个"不回中的拨轮"，录完对比哪个字节变了。
"""
import struct
import socket
import sys
import time

MAGIC = b"\x55\xcc\x30\x75"


def crc8(data):
    crc = 0x77
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def crc16(data):
    crc = 0x3692
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def keepalive(seq):
    total = 13
    b1, b2 = total & 0xFF, ((total >> 8) & 0x03) | (1 << 2)
    pkt = bytearray([0x55, b1, b2, crc8(bytes([0x55, b1, b2])), 2, 6,
                     seq & 0xFF, (seq >> 8) & 0xFF, 0, 0x00, 0x01])
    c = crc16(pkt)
    pkt += bytes([c & 0xFF, c >> 8])
    return MAGIC + struct.pack("<I", len(pkt)) + bytes(pkt)


def frames(buf):
    out, off = [], 0
    while True:
        i = buf.find(MAGIC, off)
        if i < 0 or i + 8 > len(buf):
            return out, buf[max(off, len(buf) - 3):] if i < 0 else buf[i:]
        plen = struct.unpack_from("<I", buf, i + 4)[0]
        if i + 8 + plen > len(buf):
            return out, buf[i:]
        out.append(buf[i + 8:i + 8 + plen])
        off = i + 8 + plen


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    out = sys.argv[2] if len(sys.argv) > 2 else "wheel_capture.txt"

    s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
    s.setblocking(False)
    seq = 0
    buf = b""
    t0 = time.time()
    rows = []
    print(f"录制 {secs:.0f} 秒… 现在请拨动那个轮子（来回拨几次）", flush=True)
    while time.time() - t0 < secs:
        if seq % 4 == 0:                      # 每 40ms 一次 keepalive
            try:
                s.sendall(keepalive(seq))
            except Exception:
                pass
        seq += 1
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        except BlockingIOError:
            pass
        except Exception:
            break
        fs, buf = frames(buf)
        for f in fs:
            if len(f) > 12 and f[9] == 0x06 and f[10] == 0xAE and len(f) >= 11 + 17:
                p = f[11:28]
                rows.append((time.time() - t0, p.hex()))
        time.sleep(0.01)
    s.close()

    with open(out, "w", encoding="utf-8") as fh:
        for t, h in rows:
            fh.write(f"{t:7.2f} {h}\n")

    print(f"\n收到 {len(rows)} 个状态包 → {out}")
    if not rows:
        return
    # 逐字节统计：哪些字节在录制期间发生过变化
    n = len(rows[0][1]) // 2
    changing = []
    for i in range(n):
        vals = {r[1][2 * i:2 * i + 2] for r in rows}
        if len(vals) > 1:
            changing.append((i, len(vals), sorted(vals)[:6]))
    print("变化过的字节：")
    for i, cnt, sample in changing:
        print(f"  byte {i:2d}: {cnt} 种取值  例: {' '.join(sample)}")
    if not any(i == 4 for i, _, _ in changing):
        print("  ⚠ byte 4（右上滚轮）全程没变化 —— 这个轮子没有在这条协议里上报")


if __name__ == "__main__":
    main()
