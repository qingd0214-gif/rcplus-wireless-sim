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
</style></head>
<body><div id="wrap">
  <div id="top"><span>Uncrashed · 摇杆仪表</span>
    <span><button id="launchBtn" onclick="launchSim()"
      style="background:#1c3a2d;color:#7fdca0;border:1px solid #2c8f5b;border-radius:6px;
      padding:4px 12px;font-size:15px;font-family:inherit;margin-right:10px">▶ 启动模拟器</button>
    <span id="conn">连接中…</span></span></div>

  <div id="dialL" class="drow"><span class="dname">左拨轮</span><div class="dtrack"><div class="fill" id="bDL"></div></div><span class="dval" id="vDL"></span></div>
  <div id="dialR" class="drow"><span class="dname">右拨轮</span><div class="dtrack"><div class="fill" id="bDR"></div></div><span class="dval" id="vDR"></span></div>

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
