"""实时盯 DUML 0x06/0xAE 状态包里的 byte 4（RC Plus 2 上就是右上滚轮）。

与 capture_wheel.py 的区别：不是录完再统计，而是边收边打——
一有变化立刻带时间戳打出来，这样"你什么时候拨、它什么时候报"能对上。

用法：
  python wheel_live.py 300            # 盯 300 秒
  python wheel_live.py 300 out.txt
"""
import socket
import struct
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
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    out = sys.argv[2] if len(sys.argv) > 2 else "wheel_live.txt"

    s = socket.create_connection(("127.0.0.1", 40007), timeout=3)
    s.setblocking(False)
    seq, buf, prev = 0, b"", None
    t0 = time.time()
    wheel_hits = 0
    other_last = 0.0
    beat_at = time.time()
    log = open(out, "w", encoding="utf-8")
    print(f"开始盯 {secs:.0f} 秒 —— 现在请拨那个轮子（来回拨几次）", flush=True)

    # 60 秒内一个包都没收到，说明 forward 断了，早点报错别假装在录
    while time.time() - t0 < secs:
        if seq % 4 == 0:
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
            if not (len(f) > 12 and f[9] == 0x06 and f[10] == 0xAE and len(f) >= 28):
                continue
            p = f[11:28]
            t = time.time() - t0
            if prev is None:
                prev = p
                print(f"  首包: {p.hex()}", flush=True)
                continue
            if p == prev:
                continue
            # byte 4 = 右上滚轮
            if p[4:5] != prev[4:5]:
                wheel_hits += 1
                line = (f"[{t:7.2f}s] \u2605 byte4 {prev[4:5].hex()} -> {p[4:5].hex()}    "
                        f"raw={p.hex()}")
                print(line, flush=True)
                log.write(line + "\n")
                log.flush()
                prev = p
                continue
            # 其他字节变了：只关心"头部"（0-4，按钮/滚轮），摇杆噪声不刷屏
            diff = tuple(i for i in range(17) if p[i] != prev[i])
            if diff and diff[0] < 5 and t - other_last > 0.2:
                line = f"[{t:7.2f}s]    \u5934\u90e8\u53d8\u5316 {diff}   raw={p.hex()}"
                print(line, flush=True)
                log.write(line + "\n")
                other_last = t
            prev = p
        if time.time() - beat_at > 15:
            beat_at = time.time()
            cur = prev.hex() if prev else "(还没收到包)"
            print(f"[{time.time() - t0:7.2f}s] …在盯  byte4="
                  f"{prev[4:5].hex() if prev else '??'}  raw={cur}", flush=True)
        time.sleep(0.01)

    s.close()
    log.close()
    print(f"\n结束：byte 4 变化 {wheel_hits} 次", flush=True)
    if wheel_hits == 0:
        print("  结论：这次录制期间 byte 4 一直是同一个值 —— "
              "要么轮子没被拨动，要么这条协议根本不上报它", flush=True)


if __name__ == "__main__":
    main()
