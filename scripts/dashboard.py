#!/usr/bin/env python3
"""
dashboard.py — 摇杆仪表网页服务（被 rcplus_sim.py 和 stick_screen.py 共用）

电脑读遥控器摇杆数据 → HTTP/SSE 推给遥控器自带的 Firefox，
遥控器屏幕显示 FPV 遥控器风格仪表：双摇杆圆点 + 通道条 + 按键灯。
遥控器端不用装任何东西；在 Firefox 里"添加到主屏幕"后，
遥控器桌面就有一个图标，点开即仪表。
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8123

# favicon：内嵌 SVG（绿色摇杆点），Firefox"添加到主屏幕"会用它当图标
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='18' "
           "fill='%230b0f12'/%3E%3Ccircle cx='32' cy='40' r='14' "
           "fill='%234cd97b'/%3E%3Ccircle cx='70' cy='62' r='10' "
           "fill='%232c8f5b'/%3E%3C/svg%3E")

PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#0b0f12">
<link rel="icon" href="__FAVICON__">
<title>摇杆仪表</title>
<style>
  html,body{margin:0;height:100%;background:#0b0f12;color:#cfe3d4;
    font-family:Consolas,monospace;overflow:hidden}
  /* 三列网格：左通道条 | 摇杆(正中) | 右通道条 */
  /* 摇杆居中；左右两条留白给"贴边的竖排按键"和"上角拨轮"绝对定位用 */
  #wrap{position:relative;height:100%;box-sizing:border-box;padding:6px 66px;
    display:flex;flex-direction:column}
  #top{display:flex;justify-content:space-between;
    align-items:center;font-size:17px;color:#7fdca0;white-space:nowrap}
  #main{flex:1;display:flex;align-items:center;justify-content:center}
  /* 2×3 网格：上排两条(油门/横滚) · 中排两个摇杆 · 下排两条(偏航/俯仰) */
  #cluster{display:grid;grid-template-columns:auto auto;gap:8px 26px;
    align-items:center;justify-items:center}
  .stick{position:relative;width:44vh;height:44vh;border:2px solid #29433a;border-radius:10px;
    background:radial-gradient(circle,#131b18 62%,#0b0f12)}
  .grid{position:absolute;inset:0}
  .grid:before,.grid:after{content:"";position:absolute;background:#29433a}
  .grid:before{left:50%;top:0;bottom:0;width:1px}
  .grid:after{top:50%;left:0;right:0;height:1px}
  .dot{position:absolute;width:28px;height:28px;border-radius:50%;
    background:#4cd97b;box-shadow:0 0 14px #4cd97b;transform:translate(-50%,-50%);left:50%;top:50%}
  .lbl{position:absolute;color:#4a6b5b;font-size:15px}
  /* 通道条：宽度跟摇杆一致，正好在摇杆上下方 */
  .row{width:44vh;display:flex;align-items:center;gap:8px;box-sizing:border-box}
  .name{width:46px;font-size:16px;color:#8fb8a3;text-align:right}
  .track{flex:1;height:16px;background:#131b18;border:1px solid #29433a;border-radius:4px;
    position:relative;overflow:hidden}
  .fill{position:absolute;top:0;bottom:0;background:linear-gradient(90deg,#2c8f5b,#4cd97b);opacity:.85}
  .val{width:42px;font-size:16px;color:#4cd97b;text-align:right}
  /* 拨轮：左右上角 */
  .drow{position:absolute;top:44px;display:flex;align-items:center;gap:6px;width:178px}
  #dialL{left:8px}
  #dialR{right:8px}
  /* 第三拨轮：右拨轮正下方 —— 与实机位置一一对应。
     它不回中、不在 evdev 里，只从 DUML 状态包读得到，
     所以屏幕上只能显示"这时候在往哪个方向转、几档"，没有位置可言。 */
  #whl{position:absolute;top:78px;right:8px;width:178px;display:flex;
    align-items:center;gap:6px}
  .warr{font-size:15px;color:#2b453a}
  .warr.on{color:#4cd97b;text-shadow:0 0 10px #4cd97b}
  .wsp{width:34px;font-size:13px;color:#4cd97b;text-align:right}
  /* 飞行模式三档（F/S/N）：左拨轮正下方 —— 与实机拨杆位置对应。
     也是 DUML 里读的（byte2），evdev 完全没有它。 */
  #mode{position:absolute;top:78px;left:8px;width:178px;display:flex;
    align-items:center;gap:5px}
  .mpc{border:1px solid #29433a;border-radius:5px;padding:2px 8px;
    font-size:13px;color:#3d5b4c}
  .mpc.on{background:#2c8f5b;color:#06120c;box-shadow:0 0 8px #4cd97b}
  .dname{font-size:14px;color:#8fb8a3;white-space:nowrap}
  .dtrack{flex:1;height:12px;background:#131b18;border:1px solid #29433a;border-radius:4px;
    position:relative;overflow:hidden}
  .dval{width:32px;font-size:14px;color:#4cd97b;text-align:right}
  /* 按键：左右下角贴边 */
  #botL{position:absolute;left:8px;bottom:8px}
  #botR{position:absolute;right:8px;bottom:8px}
  /* 肩键 LB/RB + Back：底部正中 */
  #botC{position:absolute;left:50%;bottom:8px;transform:translateX(-50%)}
  .grp{display:flex;gap:8px}
  .key{border:1px solid #29433a;border-radius:6px;padding:5px 12px;
    font-size:15px;color:#4a6b5b;white-space:nowrap}
  .key.on{background:#2c8f5b;color:#06120c;box-shadow:0 0 10px #4cd97b}
  /* 五向键：紧贴在 R1/R2/R3 上方（右侧一列：拨轮—五向键—R键，与实机一致） */
  #pad{position:absolute;right:14px;bottom:52px;
    display:flex;flex-direction:column;align-items:center;gap:3px}
  #padT{font-size:13px;color:#4a6b5b}
  .cross{display:grid;grid-template-columns:repeat(3,32px);grid-template-rows:repeat(3,26px);
    gap:4px}
  .pkey{border:1px solid #29433a;border-radius:6px;color:#4a6b5b;font-size:14px;
    display:flex;align-items:center;justify-content:center}
  .pkey.on{background:#2c8f5b;color:#06120c;box-shadow:0 0 10px #4cd97b}
  #conn{font-size:14px;color:#c85a5a}
  #conn.ok{color:#7fdca0}
  /* 摇杆链路延迟：绿=好(<30ms) 黄=注意(<100ms) 红=差(≥100ms) */
  #lat{font-size:14px;color:#4a6b5b}
  #lat b{color:#4cd97b;font-weight:normal}
  #lat.warn b{color:#e8c840}
  #lat.bad b{color:#c85a5a}
</style></head>
<body><div id="wrap">
  <div id="top"><span>Uncrashed · 摇杆仪表</span>
    <span><button id="launchBtn" onclick="launchSim()"
      style="background:#1c3a2d;color:#7fdca0;border:1px solid #2c8f5b;border-radius:6px;
      padding:4px 12px;font-size:15px;font-family:inherit;margin-right:10px">▶ 启动模拟器</button>
    <span id="lat">摇杆延迟 <b>--</b> ms · <span id="eps">--</span> 条/s　</span>
    <span id="conn">连接中…</span></span></div>

  <div id="dialL" class="drow"><span class="dname">左拨轮</span><div class="dtrack"><div class="fill" id="bDL"></div></div><span class="dval" id="vDL"></span></div>
  <div id="dialR" class="drow"><span class="dname">右拨轮</span><div class="dtrack"><div class="fill" id="bDR"></div></div><span class="dval" id="vDR"></span></div>

  <div id="whl"><span class="dname">滚轮</span><span class="warr" id="wL">◀</span><span class="warr" id="wR">▶</span><span class="wsp" id="wS"></span></div>

  <div id="mode"><span class="dname">模式</span><span class="mpc" id="mF">F</span><span class="mpc" id="mS">S</span><span class="mpc" id="mN">N</span></div>

  <div id="botL"><div class="grp" id="gL"></div></div>
  <div id="botR"><div class="grp" id="gR"></div></div>
  <div id="botC"><div class="grp">
    <div class="key" id="kLB">LB</div><div class="key" id="kBK">Back</div><div class="key" id="kRB">RB</div>
  </div></div>

  <div id="pad"><div id="padT">五向键</div>
    <div class="cross">
      <div></div><div class="pkey" id="pkU">▲</div><div></div>
      <div class="pkey" id="pkL">◀</div><div class="pkey" id="pkC">●</div><div class="pkey" id="pkR">▶</div>
      <div></div><div class="pkey" id="pkD">▼</div><div></div>
    </div></div>

  <div id="main">
    <div id="cluster">
      <div class="row"><span class="name">油门</span><div class="track"><div class="fill" id="bT"></div></div><span class="val" id="vT"></span></div>
      <div class="row"><span class="name">横滚</span><div class="track"><div class="fill" id="bR"></div></div><span class="val" id="vR"></span></div>

      <div class="stick"><div class="grid"></div><div class="dot" id="L"></div></div>
      <div class="stick"><div class="grid"></div><div class="dot" id="R"></div></div>

      <div class="row"><span class="name">偏航</span><div class="track"><div class="fill" id="bY"></div></div><span class="val" id="vY"></span></div>
      <div class="row"><span class="name">俯仰</span><div class="track"><div class="fill" id="bP"></div></div><span class="val" id="vP"></span></div>
    </div>
  </div>
</div>
<script>
// C1~C6：左边三个 = L1/L2/L3，右边三个 = R1/R2/R3
const LEFT = [["KEY_F1","L1"],["KEY_F2","L2"],["KEY_F3","L3"]];
const RIGHT = [["KEY_F4","R1"],["KEY_F5","R2"],["KEY_F6","R3"]];
const chips = {};
function mkChips(id, list) {
  const box = document.getElementById(id);
  for (const [k, label] of list) {
    const d = document.createElement("div");
    d.className = "key"; d.textContent = label;
    box.appendChild(d); chips[k] = d;
  }
}
mkChips("gL", LEFT); mkChips("gR", RIGHT);
const pkT = {u:0, d:0, l:0, r:0, c:0};   // 五向键各方向"最后亮起"的时刻（余亮用）
function bar(id, vid, v, mid) {
  const el = document.getElementById(id), tx = document.getElementById(vid);
  const p = (v + 1) / 2 * 100;
  if (mid) { el.style.left = "0%"; el.style.width = p + "%"; }
  else { el.style.left = Math.min(50, p) + "%"; el.style.width = Math.abs(p - 50) + "%"; }
  tx.textContent = Math.round(v * 100);
}
const es = new EventSource("/events");
let launched = false;
es.onopen = () => { const c = document.getElementById("conn"); c.textContent = "● 实时"; c.className = "ok";
  if (!launched) { launched = true; launchSim(); } };
es.onerror = () => { document.getElementById("conn").textContent = "断开，重连中…"; };
function launchSim() {
  const btn = document.getElementById("launchBtn");
  fetch("/launch", {method: "POST"}).then(r => r.json()).then(d => {
    btn.textContent = d.running ? "● 模拟器运行中" : "▶ 已启动 ✓";
  }).catch(() => { btn.textContent = "▶ 启动模拟器"; });
}
es.onmessage = (e) => {
  const d = JSON.parse(e.data);
  const L = document.getElementById("L");
  L.style.left = (50 + d.yaw * 42) + "%";
  L.style.top = (50 - d.thr * 42) + "%";
  const R = document.getElementById("R");
  R.style.left = (50 + d.roll * 42) + "%";
  R.style.top = (50 - d.pitch * 42) + "%";
  bar("bT","vT",d.thr,true); bar("bY","vY",d.yaw); bar("bR","vR",d.roll); bar("bP","vP",d.pitch);
  bar("bDL","vDL",d.dl || 0); bar("bDR","vDR",d.dr || 0);
  // 实时摇杆链路延迟：getevent 内核时间戳 vs PC 到达时刻的漂移
  // （相对滑动窗口内最优路径，≥0）。绿 <30ms / 黄 <100ms / 红 ≥100ms。
  // 注意：只在推杆时才产生新事件，静止时显示的是最后一次的值。
  const latEl = document.getElementById("lat");
  if (d.lat == null) {
    latEl.querySelector("b").textContent = "--";
  } else {
    latEl.querySelector("b").textContent = d.lat;
    latEl.className = d.lat >= 100 ? "bad" : (d.lat >= 30 ? "warn" : "");
  }
  document.getElementById("eps").textContent = d.eps == null ? "--" : d.eps;
  // 第三拨轮：wd = 最近 300ms 内往哪边转（+1/-1/0），ws = 速度档位 1~5。
  // 它是相对量、不回中，所以没有"位置"可画 —— 只能亮箭头表示正在转。
  const wdir = d.wd || 0;
  document.getElementById("wL").className = "warr" + (wdir < 0 ? " on" : "");
  document.getElementById("wR").className = "warr" + (wdir > 0 ? " on" : "");
  document.getElementById("wS").textContent = wdir ? (d.ws || "") : "";
  // 飞行模式三档：md 是 "F"/"S"/"N"（来自 DUML byte2，位置型，会一直停住）
  const md = d.md || "";
  document.getElementById("mF").className = "mpc" + (md === "F" ? " on" : "");
  document.getElementById("mS").className = "mpc" + (md === "S" ? " on" : "");
  document.getElementById("mN").className = "mpc" + (md === "N" ? " on" : "");
  const on = new Set(d.btns || []);
  for (const k in chips) chips[k].className = "key" + (on.has(k) ? " on" : "");
  // 肩键 / Back
  document.getElementById("kLB").className = "key" + (on.has("BTN_TL") ? " on" : "");
  document.getElementById("kRB").className = "key" + (on.has("BTN_TR") ? " on" : "");
  document.getElementById("kBK").className = "key" +
    (on.has("KEY_BACK") || on.has("BTN_SELECT") ? " on" : "");
  // 五向键十字：hx/hy 是 -1/0/1，中心按下上报 BTN_THUMBL。
  // 它是脉冲式上报（推一下→±1→立刻回 0），所以这里留 450ms 余亮，不然看不到。
  const hy = d.hy || 0, hx = d.hx || 0;
  const now = Date.now();
  function lit(key, pressed) {
    if (pressed) pkT[key] = now;
    return now - pkT[key] < 450;
  }
  document.getElementById("pkU").className = "pkey" + (lit("u", hy < 0) ? " on" : "");
  document.getElementById("pkD").className = "pkey" + (lit("d", hy > 0) ? " on" : "");
  document.getElementById("pkL").className = "pkey" + (lit("l", hx < 0) ? " on" : "");
  document.getElementById("pkR").className = "pkey" + (lit("r", hx > 0) ? " on" : "");
  document.getElementById("pkC").className = "pkey" +
    (lit("c", on.has("BTN_THUMBL") || on.has("KEY_ENTER")) ? " on" : "");
};
</script></body></html>""".replace("__FAVICON__", FAVICON)


# --------------------------------------------------------------- DUML 滚轮
# 遥控器上"右拨轮下面那个不回中的轮子"，硬件和固件都是通的，
# 但内核没给它开 evdev 轴（event6 连 EV_REL 都没声明），
# 它只活在 DJI 私有的 DUML 协议里：0x06/0xAE 状态包的第 4 个字节。
_wheel = None
_wheel_thread = None


class WheelFeed:
    """把 DUML 那条相对量整理成仪表页能画的状态。

    DUML 每 100ms 一个状态包，byte4 只说"这一刻在转没转、往哪边、几档"，
    转完立刻回 00 —— 没有位置概念。所以没法画成滑块，只能亮一下。
    DECAY 决定亮多久：15Hz 推送下约 4~5 帧，扫一眼就能看见。

    同一个包里 byte2 是飞行模式三档拨杆（位置型，会停住，实测静止时
    25 秒零跳变）。实测映射：0x02=F 0x00=S 0x01=N。
    注意它不在 evdev 里 —— 7 个节点全盯过，拨杆期间零事件。
    """

    DECAY = 0.30
    MODES = {0x02: "F", 0x00: "S", 0x01: "N"}

    def __init__(self):
        self.lock = threading.Lock()
        self.dir = 0
        self.sp = 0
        self.at = 0.0
        self.mode = None

    def on_tick(self, d, s):
        with self.lock:
            self.dir, self.sp, self.at = d, s, time.monotonic()

    def on_mode(self, raw):
        with self.lock:
            self.mode = raw

    def snapshot(self):
        with self.lock:
            mode = self.MODES.get(self.mode, "")
            if not self.at:
                return {"wd": 0, "ws": 0, "md": mode}
            if time.monotonic() - self.at > self.DECAY:
                return {"wd": 0, "ws": 0, "md": mode}
            return {"wd": self.dir, "ws": self.sp, "md": mode}


def start_wheel(adb, serial=None, verbose=False):
    """起一条 DUML 读取线程，只读不写：不碰手柄轴、不碰任何键。

    为什么需要 adb forward：40007 是遥控器 loopback 上的端口，
    DJI 的协议服务监听着它，必须从 PC 侧打一条隧道进去。
    """
    global _wheel
    if _wheel is not None:
        return _wheel

    import importlib.util
    import subprocess

    # 两种放法都认：duml/duml_wheel.py（本机布局）、同目录 duml_wheel.py（平铺拷走）
    here = Path(__file__).parent
    path = next((p for p in (here / "duml" / "duml_wheel.py",
                             here / "duml_wheel.py") if p.exists()), None)
    if path is None:
        _wheel = WheelFeed()          # 没有滚轮模块就退化成"永远不亮"，不影响仪表
        return _wheel
    spec = importlib.util.spec_from_file_location("duml_wheel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    feed = WheelFeed()
    last = {"at": 0.0}

    def ensure():
        """建隧道；限流 10s，别把 adb 调用刷爆。

        两个坑（都实测踩过）：
        1) adb server 被别的东西重启后，"已连接"状态会丢 —— 这时 forward
           会报 no devices。所以无线串号要顺手补一次 connect。
        2) 端口被占用不算失败 —— 多半是另一个实例（或上次运行残留）
           已经开好了一条到同一台遥控器的隧道，连上去照样能用。
        """
        now = time.monotonic()
        if now - last["at"] < 10:
            return
        last["at"] = now

        def run(*args):
            try:
                return subprocess.run([adb] + list(args),
                                      capture_output=True, timeout=12,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                return None

        r = run("-s", serial, "forward", "tcp:40007", "tcp:40007") if serial \
            else run("forward", "tcp:40007", "tcp:40007")
        if r is not None and r.returncode != 0 and serial and ":" in serial:
            run("connect", serial)                    # 顺手重连
            run("-s", serial, "forward", "tcp:40007", "tcp:40007")

    th = mod.DumlWheel(on_tick=feed.on_tick, on_mode=feed.on_mode,
                       ensure=ensure, verbose=verbose)
    th.start()
    global _wheel_thread
    _wheel_thread = th
    _wheel = feed
    return feed


def stop_wheel():
    """断开 DUML 客户端（关线程 + 关 socket）。

    为什么要断：飞行时遥控器的飞行链路也在走 DUML，我们的常驻
    客户端会和它抢遥控器的处理能力 —— 实测"极限转角不及时、打杆
    不丝滑"（2026-11-16）。所以仪表线程跟随游戏生命周期：
    游戏进行中才连，游戏退出/待命时断开，把遥控器完整让给飞行。
    """
    global _wheel, _wheel_thread
    th, _wheel_thread = _wheel_thread, None
    _wheel = None
    if th is None:
        return
    try:
        th.stop()
        th.join(timeout=2)
    except Exception:
        pass
    sock = getattr(th, "_sock", None)
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass


def wheel_running():
    """仪表 DUML 线程是否还活着（stop_wheel 后为 False）。"""
    return _wheel_thread is not None and _wheel_thread.is_alive()


def wheel_snapshot():
    """没起滚轮线程（比如 --no-wheel / 演示模式）时也要能安全调用。"""
    return _wheel.snapshot() if _wheel is not None else \
        {"wd": 0, "ws": 0, "md": ""}


def local_ip():
    """本机在遥控器所在局域网里的 IP。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def start_server(snapshot, port=PORT, commands=None):
    """后台起 HTTP 服务。snapshot: 无参函数，返回 JSON 可序列化的 dict。
    commands: {"名字": 无参函数} —— 页面 POST /<名字> 时执行，返回 JSON。
    端口被占（另一个实例已在跑）时抛 OSError，调用方自行处理。"""
    page = PAGE.encode("utf-8")
    commands = commands or {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    while True:
                        self.wfile.write(b"data: " +
                                         json.dumps(snapshot()).encode() + b"\n\n")
                        self.wfile.flush()
                        time.sleep(0.066)          # 15Hz：
                        # 原来是 30Hz。仪表页和手柄数据流走的是同一个 WiFi 网卡，
                        # 30 包/秒的 SSE 会和 getevent 的事件流抢空口，实测事件
                        # 间隔 p99 被顶到 66ms。15Hz 对指针/通道条完全够用，
                        # 空口占用减半（2026-11-14）。
                except Exception:
                    pass                            # 客户端断开
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            name = self.path.strip("/")
            if name in commands:
                try:
                    result = bool(commands[name]())
                except Exception:
                    result = False
                body = json.dumps({"ok": True, "running": result}).encode()
                self.send_response(200)
            else:
                body = b'{"ok":false}'
                self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
