# 给遥控器打一个"Uncrashed"启动图标 APK（可选）

目的：遥控器桌面上有一个 Uncrashed 图标的 APP，点开 = 打开电脑上的仪表页
（并顺带 POST /launch 自动拉起模拟器）。

不做 APK 也行：遥控器 Firefox 打开 `http://<电脑IP>:8123` → 菜单 → 添加到主屏幕。

## 文件

`assets/apk_build/` 下：

```
build.py                    # 一键构建（aapt2 → javac → d8 → 打包 dex → apksigner）
app/AndroidManifest.xml     # application-label="Uncrashed"，图标 ic.png
app/java/com/rcplus/dashboard/
    MainActivity.java       # WebView 壳，加载 http://<电脑IP>:8123
    DashWebViewClient.java  # 主框架加载失败 → 3 秒后自动重载
    DashRetryRun.java       # 重载 Runnable（必须是顶级类，见坑 3）
app/res/drawable/ic.png     # 从 Uncrashed.exe 提取的 256px 图标
extract_icon.py             # 从 PE(.exe) 的 .rsrc 提取图标（纯 Python）
gen_icon.py                 # 备用：程序化生成图标
```

## 依赖（自备，不随仓库分发）

- JDK 21（`build.py` 里 `JAVA_HOME` 必须指到 JDK **根目录**，指到 bin 会报
  `JAVA_HOME is set to an invalid directory`）
- Android build-tools（aapt2 / d8 / apksigner）+ platform android.jar。
  按脚本约定的目录放：`apk_build/bt/android-14/...`（与 build.py 中 `BT` 对应），
  platform jar 放 `apk_build/android.jar`。

## 改成你自己的电脑 IP

`MainActivity.java` 里的 URL 常量（形如 `http://192.168.31.29:8123`）改成
你电脑的局域网 IP，重新 `python build.py`，然后：

```sh
adb install -r rcplus-dashboard.apk
```

## 踩过的坑（构建失败先看这里）

1. **d8/r8 NPE**：`String.length() because "<parameter1>" is null`——
   r8 处理**匿名内部类**（`MainActivity$1.class`）时的 bug。`-g:none` 救不了，
   必须把所有匿名类拆成顶级类（本仓库已拆好，新增回调时照做）。
2. **GBK 输出**：经 `cmd /c` 调用的 bat 工具输出是 GBK，Python 里读输出必须
   `encoding="gbk", errors="replace"`，否则 `UnicodeDecodeError`。
3. **JAVA_HOME 指错**：要 JDK 根目录，不能是 `bin`。
4. **d8 报 `Invalid output: dex_out`**：先 `mkdir dex_out`。
5. **PE 图标提取 buffer size 0**：`.rsrc` 里资源**数据条目存的是 RVA 不是文件偏移**，
   正确算法 `foff = rsrc_base + (rva - rsrc_rva)`（extract_icon.py 已实现）。
6. **WebView 停在错误页**：WiFi 抖动导致首次加载失败后白屏死等。
   DashWebViewClient 里 `onReceivedError(isForMainFrame)` → 3 秒自动重载，
   `onResume` 时若仍处于错误态立即重载。

## 应用名/图标

Manifest 的 `android:label` 改显示名；`ic.png` 替换图标（drawable 即可，
不选 mipmap 也能装）。
