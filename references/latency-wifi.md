# 无线延迟：WiFi 省电休眠是根因（2026-11-14 实测记录）

环境：小米路由 5G（信道 60）、RSSI -62、协商 520Mbps、`adb connect 192.168.31.x:5555`。

## 症状

"延迟有点高，玩起来摇杆老是卡一下/掉一下"。游戏里表现为打杆不及时、
随机卡顿 0.1~1.5 秒、偶尔整段失灵。

## 测量

`probe_latency.py`（adb 往返 + 事件流间隔）：

| 指标 | 无保活 | 有保活（50 包/秒） |
|---|---|---|
| ping 平均 | 53~75ms（最长 195ms） | **2ms（最长 5ms）** |
| 事件间隔 p99 | 66ms | ~75ms* |
| >100ms 断档 | 12.7s 内 10 次，最长 **1524ms** | 10s 内 5 次，最长 134ms |

\* 事件间隔统计受"设备只在变化时上报"影响（静止就没事件），不能完全代表传输延迟；
ping 是干净的链路指标。

## 根因与修复路径

1. Android WiFi 省电（PS-Poll）：射频只在 beacon/DTIM 窗口醒来收包。
2. 试图真正关闭省电失败：`iw dev wlan0 set power_save off` → `Operation not permitted`；
   `cmd wifi` → Uid 2000 无权；`ro.debuggable=0`、无 su。**没有 root 关不掉。**
3. 但持续的小流量能让驱动保持唤醒：**每秒 30 个 24 字节 UDP 就把 ping 从 75ms 压到 2ms**。
   30/60/100/150 包/秒实测都是 2~3ms，取 50 留余量。代价 0.7KB/s。

## 落地：RadioKeepAlive（rcplus_sim.py）

- 无线模式（serial 含 `:`）才启动；有线完全没有这个问题。
- 目标端口 9998 没有监听者也没关系——ICMP 端口不可达被内核限流（约 1 条/秒）。
- 发送节奏用 deadline 对表，系统挂起后（delay < -2s）重新对表，不追帧。

## 判活：设备侧心跳（关键设计）

`getevent` 只在**状态变化**时输出，摇杆静止 = 0 事件。用"有没有数据"判活会把
静止误判成掉线（实测一启动就连杀 6 次重连，还误触了用户的 R3）。
所以读线程跑的是复合命令：

```sh
getevent -lt /dev/input/event6 & while true; do echo __HB__; sleep 2; done
```

- 有心跳、没事件 → 设备静止，正常。
- 连心跳都没有超过 STALL_KILL（8s）→ 流真死了，杀子进程重连。
  这处理的是 adb"半死"：子进程还在、TCP 还挂着，但数据再也不来，readline 永久阻塞。

## 已知限制（不影响飞行）

- `adb shell` 单次命令往返 ~100ms，是 Windows 起 adb 客户端进程 + 设备端开 shell 的
  固定开销。事件流走长连接不承担这笔开销，只影响"点图标到有反应"这类一次性命令。
- **两个 getevent 会话会互相饿死**（后开的 22 秒才吐 1 条）。诊断时先停掉桥接，
  或只测 ping。
- 被强杀的 adb 客户端会在设备侧留下 getevent 僵尸进程。清理：

```sh
adb shell "ps -A -o PID,ARGS | grep 'getevent -lt' | grep -v grep | awk '{print \$1}' | xargs -r kill -9"
```

  注意别用 `pkill -f getevent`——会把自己这条 shell 也匹配杀掉。

## 调参建议

- 手感发黏 → `RadioKeepAlive(ip, rate=100)`。
- 换路由/换信道后重测：`probe_radio.py` 直接给对照结论。
