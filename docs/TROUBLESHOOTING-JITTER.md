# 抖动 / 延迟 / 打杆不丝滑 —— 完整排查手册

> 这份文档来自 2026-11-19 ~ 11-21 三天真实排查的完整过程。当时症状是"飞机抖动、打杆延迟、不丝滑"，
> 最终发现叠了**四层互相独立的原因**，逐层剥掉才彻底解决。本文按排查顺序整理成可复用的排除清单，
> 每一层给出：症状特征 → 验证方法 → 修复方案。
>
> **核心教训：抖动从来不是一个原因。别抓到一个就停手，要一层层验证到全绿。**

## 症状速查表

| 症状特征 | 大概率原因 | 跳到 |
|---|---|---|
| 平时顺滑，飞行中突然"冻"一下又恢复 | 链路事件流塌陷（多流抢路） | 层 2 |
| 从头到尾持续抖、画面一顿一顿 | GPU 满载 / 帧率不稳 | 层 3 |
| 打杆总是慢半拍、极限转角不及时 | 链路延迟或帧率 | 层 1 / 层 3 |
| 重摔后才开始抖，重置无效、重进地图才好 | 螺旋桨损坏系统（2.43+ 默认开启） | 层 5 |
| 只有油门轴怪、其他轴正常 | 油门模式与拆弹簧不匹配 | 层 6 |
| 飞行流畅但仪表页数字乱跳 | 仪表页布局问题 | 已修（定宽数字） |

---

## 层 0：建立观测手段（先做这个）

排查前先让自己"看得见"，否则全程盲猜。

### 仪表页实时延迟

仪表页顶栏显示实时摇杆链路延迟（内核时间戳 vs PC 到达的漂移，EMA 平滑）和事件率：

- 延迟 <10ms 且绿色 → 链路基本健康
- 事件率（条/s）：静止约 1（事件驱动），推杆时 80~290
- **关键指标：推杆时事件率突然掉到个位数 = 链路塌陷**（塌陷太短不触发重连报警，但你的杆已经冻了一瞬）

### PresentMon 逐帧捕获（游戏侧）

下载 [PresentMon](https://github.com/GameTechDev/PresentMon/releases)：

```powershell
PresentMon.exe -session_name run1 -process_name Uncrashed-Win64-Shipping.exe -output_file fps.csv -timed 120
```

飞行 2 分钟后分析帧时间分布：

- 平均帧时间 → 真实 FPS
- **p99 / max → 有没有硬冻结**（200ms+ 的帧 = 半秒完全停摆，玩家感受就是"抖一下、打杆突然不跟"）
- 注意：GPU 占用率 50% 不代表帧时间稳，必须看 p99

### DUML 心跳降频实验脚本

`scripts/probe_hb.py`：对每个心跳间隔测遥测包速率，验证 DUML 会话的保活下限。

---

## 层 1：WiFi / adb 传输链路

### 验证

```bash
ping 192.168.31.174          # 期望 <5ms、0 丢包
adb devices                  # 设备在线
adb shell settings get global wifi_suspend_optimizations_enabled   # null/1 = 省电优化开着
```

### 关闭 WiFi 省电优化（Android 会间歇性挂起连接）

```bash
adb shell settings put global wifi_suspend_optimizations_enabled 0
adb shell settings put global wifi_sleep_policy 2
```

### 排除adb 假象

排查时自己起的 adb server 可能被工具沙箱回收，造成"adb 老是死"的假象。
以 `tasklist` 复核进程后再下结论，别被自己的探测器骗了。

### 注意端口

本机可能同时存在多个 adb server（不同端口）。sim 用哪个端口，探测就用哪个端口，
否则会看到"流健康但 adb devices 是空"的怪象。

---

## 层 2：DUML 心跳与摇杆流抢路（本案最大凶手）

### 机制

拨轮数据走 DUML 客户端（adb forward → 遥控器 loopback:40007）。旧实现按"40ms 一次心跳"发
保活包 = 25Hz，**与两条 getevent 事件流挤同一张 WiFi 网卡和遥控器同一个协议服务**。
实测后果：推杆时事件率周期性塌到 1 条/s —— 塌一瞬就是"抖一下"，连塌就是"打杆不跟手"。

### 验证

1. `--no-wheel` 启动模拟器（`python rcplus_sim.py ... --no-wheel`），再飞一次
2. 不抖了 = DUML 心跳嫌疑实锤
3. 用 `scripts/probe_hb.py` 测心跳下限

### 实测结论（2026-11-21）

心跳降到 **1 秒一次**，遥测照样满速 10 包/s —— 遥控器是**主动推送**遥测的，
心跳只是保活，"40ms 不发就被踢"是旧误判。25Hz 心跳纯属浪费 25 倍空口。

### 修复（已入库）

`duml/duml_wheel.py`：待机心跳 1Hz；静默 >2s 自动提速 40ms×3s 抢回会话。
拨轮响应不变（遥测本来就是 10Hz 推送）。

### 顺带的坑

- **多条 adb 流会互相饿死**（getevent ×2 + forward），SSE 推流也从 30Hz 降到 15Hz 才稳
- 后台常驻的探测/记录脚本会抢 CPU，导致"排查时更抖"的错觉

---

## 层 3：GPU / 帧率

### 验证

```powershell
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
Get-Process Uncrashed* | Select-Object Id,CPU
```

- GPU **连续 100%** = 帧生成时间必然不稳 → 抖 + 输入排队延迟
- 显存接近满 → 纹理流送卡顿
- 用 PresentMon 的 p99/max 定帧时间尖峰

### 修复

1. **清后台**：ComfyUI / 各类 AI 服务吃几 GB 显存还占 GPU，飞前关掉
2. **降画质三巨头**：`GameUserSettings.ini`（需先关游戏再改，UE 退出时会回写覆盖）
   ```ini
   sg.ResolutionQuality=75.000000
   sg.AntiAliasingQuality=2
   sg.ViewDistanceQuality=2
   sg.FoliageQuality=2
   ```
   实测：GPU 100% → 30~45%
3. **Defender 排除游戏目录**：实时扫描拦截流送读盘会造成 IO 卡顿
   ```powershell
   Add-MpPreference -ExclusionPath "D:\游戏目录"
   ```
4. **加大纹理流送池**（`Engine.ini` 追加）：
   ```ini
   [SystemSettings]
   r.Streaming.PoolSize=4000
   r.Streaming.FullyLoadUsedTextures=1
   ```

### 数据基准（修复后）

平均 119 FPS，99% 帧时间 <10ms，120 秒内仅 4 次孤立硬冻结（资源加载，非持续问题）。

---

## 层 4：游戏内设置（新装模拟器必查）

新装/重装模拟器后，以下设置全是默认值，必须过一遍：

1. **校准**：控制 → 选 XInput Controller #1 → **Stick Calibration**（四轴推到头再回中）
2. **Deadzone = 0**（我们自己已带 2% 死区，游戏再叠一层会发涩）
3. **Gamepad Throttle 关**（油门直接走摇杆轴）
4. 屏幕提示：SDL 轴 2/4 是扳机，恒 -1，绑轴千万别选

---

## 层 5：螺旋桨损坏系统（2.43+ 默认开启，最容易漏！）

### 症状特征（本案终章）

- **重摔后飞机没挂、自己摆正，之后起飞一直抖**
- 单次"重置"重生的是同一架带伤飞机，照样抖
- **完全重头开始飞（重载地图）就平顺** —— 这是唯一能和层 1~3 区分的特征

### 原因

Uncrashed 2.43（2025-05 更新）新增螺旋桨损坏系统，**默认开启**。
重摔 → 桨叶变形 → 持续震动。旧版没有此系统，所以"以前重摔也没事、更新/重装后开始抖"。

### 验证

- 官方更新日志：*Update 2.43 – Added propeller damage (Enabled by default. If you prefer to play
  without it, you can disable it in Menu → Gameplay)*
- 开发者确认：连按两次重置键 = 修桨；重载地图 = 换新桨

### 修复

- 练飞效率优先：**菜单 → Gameplay → 关闭 Propeller damage**
- 保留真实感：摔了之后**连按两次重置**修桨（可绑到遥控器顺手键位）

---

## 层 6：油门模式与拆弹簧

左摇杆弹簧拆除后（穿越机手感），油门杆停在哪就是哪：

- **绝对模式**（`--throttle absolute`）：杆位 = 油门。**拆弹簧后必须用这个**
- **锁存模式**（默认）：推杆积分油门——弹簧还在时好用，拆了弹簧会持续积分爆冲
- `Back` 键运行中随时切换
- 坠机重置前先把油门拉到底，避免重生瞬间高油门弹起

---

## 排查决策树

```
抖动/延迟
├─ 仪表延迟读数异常（>20ms / 塌陷）？
│   ├─ 是 → ping 正常？ → 正常：层 2（--no-wheel 试）/ 关 WiFi 省电
│   └─                    异常：修 WiFi/路由
├─ PresentMon p99 有 200ms+ 硬冻结？
│   ├─ 是 → 层 3（GPU 满载 / Defender / 流送池）
│   └─ 否 ↓
├─ 规律是"重摔后才开始抖"？
│   ├─ 是 → 层 5（螺旋桨损坏：关闭或双击重置修桨）
│   └─ 否 ↓
├─ 新装模拟器后首次出现？
│   ├─ 是 → 层 4（校准 / Deadzone / Gamepad Throttle）
│   └─ 否 ↓
└─ 只有油门轴异常？ → 层 6（油门模式与弹簧状态匹配）
```

## 修复清单（本案全部改动，已入库）

| 提交 | 内容 |
|---|---|
| `0147a54` | DUML 仪表线程跟随游戏生命周期（真实飞行让路） |
| `6b42a31` | 新游戏路径 + 启动失败不再静默 |
| `da30c70` | 仪表页定宽数字防布局跳动 |
| `b6eb167` | 拨轮音量缺依赖显式报错 |
| `db63350` | **DUML 心跳 25Hz→1Hz 自适应（本案最大元凶）** |
| 本文档 | 排查手册 + Defender 排除 + 流送池配置 |

## 工具

| 脚本 | 用途 |
|---|---|
| `scripts/probe_hb.py` | DUML 心跳下限实验（测会话保活阈值） |
| PresentMon（外部） | 游戏逐帧时间捕获，分析 p99/max |
| 仪表页顶栏 | 实时链路延迟 + 事件率，飞行中肉眼监控 |
