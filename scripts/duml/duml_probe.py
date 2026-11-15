#!/usr/bin/env python3
"""Probe the DJI RC DUML TCP stream (port 40007) through `adb forward`.

Sends the harmless General/Version-Query keepalive used by stiad/dji-rc-linux
and reports which DUML cmd_set/cmd_id frames arrive. With --watch it prints
decoded 0x06/0xAE stick frames whenever they change.
"""
import argparse, socket, struct, sys, time
from collections import Counter

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

def axis(p, ch):
    pos, wrap = 2 * ch + 1, 2 * ch + 2
    if wrap >= len(p):
        return None
    return -((p[wrap] - 4) * 256 + p[pos])

def decode(p):
    ch0 = p[0] | p[1] << 8 if len(p) > 1 else 0
    ch1 = p[2] | p[3] << 8 if len(p) > 3 else 0
    names = {"RH": 2, "RV": 3, "LV": 4, "LH": 5, "LW": 6, "RW": 7}
    ax = " ".join(f"{k}={axis(p, c)}" for k, c in names.items())
    return f"btn=0x{ch0:04x} mode/back=0x{ch1:04x} {ax} raw={p.hex()}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=40007)
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()

    s = socket.create_connection(("127.0.0.1", a.port), timeout=3)
    s.settimeout(0.02)
    seen, buf, seq, last = Counter(), b"", 0, None
    sizes = {}
    t_end = time.time() + a.seconds
    next_ka = 0
    while time.time() < t_end:
        if time.time() >= next_ka:
            s.sendall(keepalive(seq)); seq = (seq + 1) & 0xFFFF
            next_ka = time.time() + 0.04
        try:
            chunk = s.recv(65536)
            if not chunk:
                print("connection closed by RC", flush=True); break
            buf += chunk
        except socket.timeout:
            continue
        fs, buf = frames(buf)
        for f in fs:
            if len(f) < 13 or f[0] != 0x55:
                seen["non-duml"] += 1; continue
            key = f"{f[4]:02x}->{f[5]:02x} set=0x{f[9]:02x} id=0x{f[10]:02x}"
            seen[key] += 1; sizes[key] = len(f) - 13
            if a.watch and f[9] == 0x06 and f[10] == 0xAE:
                p = f[11:-2]
                state = (p[0:4], [axis(p, c) for c in range(2, 8)])
                if last is None or state[0] != last[0] or any(
                        x is not None and y is not None and abs(x - y) > 60
                        for x, y in zip(state[1], last[1])):
                    print(time.strftime("%H:%M:%S"), decode(p), flush=True)
                    last = state
    s.close()
    print("summary:", flush=True)
    for k, n in seen.most_common():
        print(f"  {n:6d}  {k}  payload={sizes.get(k)}", flush=True)

if __name__ == "__main__":
    main()
