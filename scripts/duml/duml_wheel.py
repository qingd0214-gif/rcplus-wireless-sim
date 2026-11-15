"""DUML 滚轮读取模块 —— 把 RC Plus 那个「不回中的滚轮」变成可编程输入。

协议事实（实测，RC Plus 1 / RM700B，与 RC Plus 2 一致）：
  0x06/0xAE 状态包 17 字节，每 100ms 一个（有输入时更快）
    byte 2 : mode/back 键
    byte 4 : 滚轮 —— 00=静止，bit7=转动中，bit6=方向，bit5..1=速度 1~5
    byte 5..16 : 6 个 int16 LE 轴，中心 1024

用法：
  python duml_wheel.py --stats 15      # 抓 15 秒，打印包率 / 滚轮事件
  python duml_wheel.py --watch         # 实时打印滚轮方向与速度
  作为模块：
      from duml_wheel import DumlWheel
      w = DumlWheel(on_tick=lambda d, s: print(d, s)); w.start()
"""
import socket
import struct
import sys
import threading
import time

MAGIC = b"\x55\xcc\x30\x75"
PORT = 40007


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
    """DJI 要求 40ms 一次心跳，否则它把连接当作死客户端踢掉。"""
    total = 13
    b1, b2 = total & 0xFF, ((total >> 8) & 0x03) | (1 << 2)
    pkt = bytearray([0x55, b1, b2, crc8(bytes([0x55, b1, b2])), 2, 6,
                     seq & 0xFF, (seq >> 8) & 0xFF, 0, 0x00, 0x01])
    c = crc16(pkt)
    pkt += bytes([c & 0xFF, c >> 8])
    return MAGIC + struct.pack("<I", len(pkt)) + bytes(pkt)


def split_frames(buf):
    out, off = [], 0
    while True:
        i = buf.find(MAGIC, off)
        if i < 0 or i + 8 > len(buf):
            return out, (buf[max(off, len(buf) - 3):] if i < 0 else buf[i:])
        plen = struct.unpack_from("<I", buf, i + 4)[0]
        if i + 8 + plen > len(buf):
            return out, buf[i:]
        out.append(buf[i + 8:i + 8 + plen])
        off = i + 8 + plen


def decode_wheel(v):
    """byte4 -> (方向, 速度)。方向 +1 / -1，静止返回 (0, 0)。"""
    if v == 0 or not (v & 0x80):
        return 0, 0
    return (1 if v & 0x40 else -1), (v >> 1) & 0x1F


class DumlWheel(threading.Thread):
    """后台线程：持续读 DUML 状态包，把滚轮事件回调出去。

    断线自动重连 —— adb forward 掉线、遥控器休眠断 WiFi 都会让 socket 死掉，
    没有重连的话表现就是「轮子突然没反应」，很难现场排查。
    """

    def __init__(self, on_tick=None, port=PORT, host="127.0.0.1", verbose=False,
                 ensure=None):
        super().__init__(daemon=True)
        self.on_tick = on_tick
        self.port, self.host = port, host
        self.verbose = verbose
        self.ensure = ensure          # 连之前先跑一下（用来建 adb forward 隧道）
        self.stop_evt = threading.Event()
        self.pkts = 0
        self.ticks = 0
        self.connected = False
        self.last_err = None
        self._sock = None

    def _connect(self):
        if self.ensure:
            try:
                self.ensure()
            except Exception:
                pass
        s = socket.create_connection((self.host, self.port), timeout=3)
        s.setblocking(False)
        return s

    def run(self):
        seq = 0
        buf = b""
        while not self.stop_evt.is_set():
            try:
                self._sock = self._connect()
                self.connected = True
                if self.verbose:
                    print(f"[DUML] 已连接 {self.host}:{self.port}", flush=True)
            except Exception as e:
                self.connected = False
                self.last_err = e
                if self.verbose:
                    print(f"[DUML] 连接失败：{e}（2 秒后重试）", flush=True)
                self.stop_evt.wait(2.0)
                continue

            buf = b""
            try:
                while not self.stop_evt.is_set():
                    if seq % 4 == 0:                 # 25Hz 心跳
                        try:
                            self._sock.sendall(keepalive(seq))
                        except Exception:
                            break
                    seq += 1
                    try:
                        chunk = self._sock.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    except BlockingIOError:
                        chunk = None
                    except Exception:
                        break
                    frames, buf = split_frames(buf)
                    for f in frames:
                        if len(f) >= 28 and f[9] == 0x06 and f[10] == 0xAE:
                            self.pkts += 1
                            d, sp = decode_wheel(f[11 + 4])
                            if d and self.on_tick:
                                self.ticks += 1
                                try:
                                    self.on_tick(d, sp)
                                except Exception:
                                    pass
                    time.sleep(0.005 if chunk else 0.01)
            except Exception as e:
                self.last_err = e
            finally:
                self.connected = False
                try:
                    self._sock.close()
                except Exception:
                    pass
            if not self.stop_evt.is_set():
                self.stop_evt.wait(1.0)

    def stop(self):
        self.stop_evt.set()


def main():
    stats = "--stats" in sys.argv
    secs = 15.0
    if stats:
        for i, a in enumerate(sys.argv):
            if a == "--stats" and i + 1 < len(sys.argv):
                try:
                    secs = float(sys.argv[i + 1])
                except ValueError:
                    pass

    t0 = time.time()
    events = []

    def on_tick(d, sp):
        t = time.time() - t0
        events.append((t, d, sp))
        if not stats:
            arrow = "→" if d > 0 else "←"
            print(f"[{t:7.3f}s] {arrow} 速度 {sp}", flush=True)

    w = DumlWheel(on_tick=on_tick, verbose=True)
    w.start()
    print(f"监听 {secs:.0f} 秒…", flush=True)
    try:
        time.sleep(secs)
    except KeyboardInterrupt:
        pass
    w.stop()
    time.sleep(0.3)

    dur = time.time() - t0
    print(f"\n收到 {w.pkts} 个状态包 / {dur:.1f}s = {w.pkts / dur:.1f} 包/秒")
    print(f"滚轮事件 {len(events)} 次")
    if len(events) > 1:
        gaps = [events[i + 1][0] - events[i][0] for i in range(len(events) - 1)]
        gaps.sort()
        med = gaps[len(gaps) // 2]
        print(f"滚轮事件间隔：中位 {med * 1000:.0f}ms  "
              f"最小 {gaps[0] * 1000:.0f}ms  最大 {gaps[-1] * 1000:.0f}ms")
    if events:
        dirs = {}
        for _, d, _ in events:
            dirs[d] = dirs.get(d, 0) + 1
        print(f"方向分布：{dirs}   （+1 与 -1 各出现一次时，"
              f"说明你两个方向都拨过）")
    if w.last_err:
        print(f"最后一次错误：{w.last_err}")


if __name__ == "__main__":
    main()
