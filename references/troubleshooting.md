# 故障排查手册

症状 → 原因 → 处理。按出现频率排序。

## 1. 遥控器完全不在线（`adb devices` 空）

- USB：换数据线（充电线不带数据）、换口；`adb kill-server && adb devices` 重来。
- WiFi：遥控器没连同一 WiFi / IP 变了 → 删脚本同目录 `wifi_ip.txt`，插线重跑
  `adb tcpip 5555` 记录新 IP。
- 电脑装过安卓模拟器（MuMu/雷电）：它们的 adb 会抢 5037 端口并重启系统 adb server，
  一重启事件流就断。本项目固定用 `ANDROID_ADB_SERVER_PORT=5038`（launcher 已内置）。
  手动跑 adb 时记得带同样环境变量。

## 2. 连上了但读不到数据 / 状态栏出现 `[链路停滞]`

- 遥控器屏幕睡了：DJI 驱动休眠时零事件。KeepAwake 会自动补唤醒；手动救急：
  `adb shell input keyevent KEYCODE_WAKEUP`
- 设备侧 getevent 僵尸进程堆积（多见于脚本被强杀后）：

  ```sh
  adb shell "ps -A -o PID,ARGS | grep 'getevent -lt' | grep -v grep | awk '{print \$1}' | xargs -r kill -9"
  ```

- 无线掉线后 adb 条目失效：读线程会自动 `adb connect` 重连（退避 1→5s）。

## 3. 飞行中摇杆突然冻住几秒

- 无线 → 十有八九是 WiFi 省电休眠。确认保活线程活着（重启 `launcher.py --auto`），
  再 `ping` 验证。详见 [latency-wifi.md](latency-wifi.md)。
- 有线 → 查 USB 供电/ hubs；看状态栏 `[重连N]` 计数是否猛涨（流在反复断）。

## 4. 游戏里看不到手柄 / 摇杆不动

- **ViGEmBus 驱动没装**：`python -c "import vgamepad"` 不报错但 joy.cpl 里没设备 →
  去 https://vigem.org 装驱动。
- 游戏在桥接启动**之前**就开了：UE 游戏启动时才枚举设备，必须重启游戏
  （launcher 检测到游戏已运行会自动处理）。
- 绑定错误：SDL 轴 2/4 是扳机（恒 -1），别绑；Deadzone 设 0；
  Gamepad Throttle 功能关掉（油门直接走摇杆轴）。
- 油门手感不对：默认"绝对值"模式（杆在哪油门在哪）。遥控器硬件油门不回中的
  改装版直接用；原装回中杆按 Back 切"锁存"模式。

## 5. 关掉游戏又自动弹出来

退出码协议被改坏：10 = R3 主动关（待命不重启游戏），6 = 已有实例。
确认 `rcplus_sim.py` 的 R3 分支仍返回 10、launcher 对 10 转 `no_launch`。

## 6. 电量低自动断开

BatteryGuard：<25% 警告，<10% 主动断开保护。充电即可恢复。
低电量报警声：系统音量能压到最低档，固件层压不掉，充电即停。

## 7. 遥控器点图标仪表打不开 / 白屏

- 确认电脑防火墙放行 8123 端口（Python 或入站规则）。
- 遥控器 Firefox 停在错误页：重新点图标（APK 版有 3 秒自动重载 + onResume 重试）。
- 想要桌面图标直接是个 APP：参考 [apk-build.md](apk-build.md) 自己打一个 WebView APK。

## 8. APK 构建失败（assets/apk_build）

- `JAVA_HOME is set to an invalid directory` → 必须指向 JDK 根目录（如 `C:\tools\jdk21`），不是 bin。
- `UnicodeDecodeError: 0xd3` → bat 工具输出是 GBK，脚本里要 `encoding="gbk"`。
- d8 报 `String.length() because "<parameter1>" is null` → r8 对**匿名内部类**的 NPE，
  所有回调必须拆成顶级类（本项目已拆好：DashWebViewClient / DashRetryRun）。
- PE 图标提取拿不到数据 → 资源数据条目存的是 RVA，文件偏移 = `rsrc_base + (rva - rsrc_rva)`。

## 9. 诊断命令速查

```sh
# 链路（最重要）
ping -n 20 <遥控器IP>          # 平均 2ms=好，50ms+=省电休眠没压住

# 设备侧
adb shell getevent -p /dev/input/eventN    # 轴静止值/范围
adb shell dumpsys battery | grep level     # 电量
adb shell dumpsys power | grep Wakefulness # 屏幕状态

# 电脑侧
python probe_radio.py <IP>     # 省电休眠对照实验
python probe_latency.py <IP>   # adb 往返 + 事件流间隔分布
```
