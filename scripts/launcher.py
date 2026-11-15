#!/usr/bin/env python3
"""
launcher.py — RC Plus 模拟器手柄 中文菜单
由「RC Plus 手柄.bat」双击调用；也可以 python launcher.py 直接跑。

加 --auto 参数 = 跳过菜单，直接开飞：
    有线优先（延迟最低）→ 没线自动连无线 → 都不通才落回菜单。
桌面的 bat 就是带 --auto 的，双击即可，不用再敲回车。

中文菜单放在 Python 里而不是 .bat 里，是因为 cmd.exe 按控制台代码页解析批处理，
含中文的 .bat 在 GBK/UTF-8 混用时会把它拆成乱码命令。
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# 独占 adb server 端口，防模拟器（MuMu 等）的 adb 抢 5037 重启 server、
# 掐断摇杆数据流。必须设在任何 adb 调用之前（详见 rcplus_sim.py 同段注释）。
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")

# ---- 后台模式（pythonw）支持 ------------------------------------
# pythonw 下 sys.stdout/sys.stderr 是 None，print 会直接崩；
# 且没有控制台后，每个控制台子进程（adb 等）都会闪一个黑框。
# 对策：stdout 重定向到日志文件 + 子进程统一加 CREATE_NO_WINDOW。
_NOWIN = 0x08000000 if os.name == "nt" else 0     # CREATE_NO_WINDOW
BG_LOG = Path(__file__).resolve().parent / "launcher_bg.log"
_bg_handle = None

HERE = Path(__file__).resolve().parent
HERE_STR = str(HERE)


def _setup_background():
    """pythonw 启动时把输出接到日志文件，print 才能用，也方便排查。"""
    global _bg_handle
    try:
        _bg_handle = open(BG_LOG, "a", buffering=1,
                          encoding="utf-8", errors="ignore")
        sys.stdout = sys.stderr = _bg_handle
        print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 后台启动 =====")
    except Exception:
        pass

# 关键：不能用裸的 python。系统 PATH 里第一个 python 是别的虚拟环境，没有 vgamepad。
# 2026-11-15 事故：WorkBuddy 的托管 python 在重启时被重置成干净环境，
# site-packages 只剩 pip，vgamepad 被抹掉 —— 表现就是"重启后游戏里没手柄"。
# 所以不再写死路径，改成"挨个试，谁能 import vgamepad 就用谁"。
def _pick_python():
    cands = [
        os.environ.get("RCPLUS_PYTHON"),        # 手动指定优先
        sys.executable,                          # 谁启动的 launcher 就用谁
        r"C:\rcplus-env\Scripts\python.exe",     # 独立环境（setup_env.bat 建的）
        r"C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe",
    ]
    for c in cands:
        if not c or not os.path.exists(c):
            continue
        try:
            r = subprocess.run([c, "-c", "import vgamepad"],
                               capture_output=True, timeout=25,
                               creationflags=_NOWIN)
            if r.returncode == 0:
                return os.path.normpath(c)
        except Exception:
            continue
    # 一个都不行，还是返回独立环境那个，让子进程报出原本的错误信息
    return os.path.normpath(r"C:\rcplus-env\Scripts\python.exe")


PYEXE = _pick_python()
ADB = os.path.normpath("C:/tools/platform-tools/adb.exe")
GAME = "D:/穿越机模拟器/Uncrashed免安装/Uncrashed.FPV/Uncrashed.exe"

SAVE_DIR = Path.home() / r"AppData\Local\Uncrashed\Saved\SaveGames"
BACKUP_DIR = HERE / "bind_backup"


def backup_bindings():
    """每天一份快照：把游戏里的轴绑定/校准存档拷到 rcplus/bind_backup/。

    背景（2026-11-14 事故）：游戏某次启动/操作后把 5 个轴绑定槽清空了，
    推杆飞机完全不动，查了半天链路才发现是游戏自己的存档被清。
    绑定做一次要几分钟、丢一次要重绑半天 —— 每天开机自动快照一份，
    以后再被清，直接把备份拷回去就能恢复。
    """
    if not SAVE_DIR.exists():
        return
    day = time.strftime("%Y-%m-%d")
    dst = BACKUP_DIR / day
    changed = False
    for sub in ("Settings", "RC"):
        src = SAVE_DIR / sub
        if not src.exists():
            continue
        for f in src.glob("*.sav"):
            target = dst / sub / f.name
            if not target.exists() or target.read_bytes() != f.read_bytes():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.write_bytes(f.read_bytes())
                    changed = True
                except Exception:
                    pass
    if changed:
        print(f"★ 游戏绑定存档已备份到: {dst}")

MENU = """
============================================================
  DJI RC Plus  ->  虚拟 Xbox 360 手柄
============================================================


  [1] 演示模式：不接遥控器，手柄自己摆杆
      先用这一步确认 Uncrashed 到底认不认这个虚拟手柄

  [2] 接遥控器 + 自动启动 Uncrashed（有线）
      先建手柄、再拉起游戏，顺序是对的

  [3] 接遥控器，游戏自己手动开

  [4] 只检查遥控器有没有连上

  [5] 打开 Windows 手柄面板 (joy.cpl)

  [6] 盯 Uncrashed 的轴绑定存档
      去游戏里绑轴，这里实时告诉你游戏有没有记住

  [7] 等遥控器上线 / 查电量
      遥控器没开机、没插电、或怀疑没电时用这个

  [8] 重置 Uncrashed 的摇杆绑定（先备份再清空）
      绑乱了、轴对不上号的时候用

  [9] 按键监视器（查重置键为什么没反应）
      按遥控器按键，实时显示对应的手柄按键

  [10] 无线模式：WiFi 连接 + 自动启动 Uncrashed   <-- 回车默认
      遥控器重启过就连不上，此时插线选本项一次即可

  [11] 遥控器屏幕：摇杆仪表（FPV 遥控器风格，用自带浏览器显示）
      电脑读摇杆 → 推给遥控器 Firefox 实时画出来，不用装任何 App

  [0] 退出
"""


def run_sim(*args, wait=True):
    """在当前控制台跑 rcplus_sim.py，Ctrl+C 能正常打断。

    wait=False 用于双击自动启动：跑完直接退出，不再要你按回车。
    后台模式（pythonw）下把子进程输出接到日志文件，并把窗口类
    子进程设为不弹窗。
    """
    cmd = [PYEXE, "-u", str(HERE / "rcplus_sim.py"), *args]
    kw = {"creationflags": _NOWIN}
    if _bg_handle is not None:
        kw["stdout"] = kw["stderr"] = _bg_handle
    try:
        code = subprocess.call(cmd, cwd=HERE_STR, **kw)
    except KeyboardInterrupt:
        if not wait:
            raise          # 常驻模式下 Ctrl+C = 真退出，交给上层处理
        code = 0
    if wait:
        input("\n按回车返回菜单…")
    return code


def check():
    print("\n--- adb 设备列表 ---")
    subprocess.call([ADB, "devices", "-l"])
    print("\n--- 摇杆设备节点 ---")
    subprocess.call([ADB, "shell", "grep -A5 'DJI embedded joystick' /proc/bus/input/devices"])
    print("\n说明: 上面必须出现一行以 device 结尾的序列号，")
    print("      并且 Handlers=event6 才算正常。")
    input("\n按回车返回菜单…")


def main():
    # 后台模式（pythonw 双击 .vbs/.bat 启动）：先接管输出，print 才能用
    if sys.stdout is None:
        _setup_background()
    # launcher 也加单实例锁：launcher 本身没锁，双击两次会拉起两个 launcher，
    # 各自 spawn 一份 rcplus_sim（rcplus_sim 自己的互斥体之前也是坏的）。
    import ctypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _h = _k32.CreateMutexW(None, True, "Global\\RCPlusSimLauncherMutex")
    if _h and ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        print("[!] 已经有一个启动器在运行了（可能双击了两次）。")
        print("    多开会拉起两个手柄实例互相抢事件流，五向键/按键会丢。")
        print("    用正在跑的那个就行；确实要重启请先关掉旧的窗口。")
        time.sleep(4)
        return 0

    # 双击启动（bat 传了 --auto）：跳过菜单直接开飞，全程不用按键
    auto = "--auto" in sys.argv[1:]
    keep_screen = False
    try:
        backup_bindings()      # 每天一份绑定快照，被清了能整体恢复（见函数注释）
    except Exception as e:
        print(f"[!] 绑定备份失败（不影响启动）: {e}")
    if auto:
        # 常驻模式：遥控器没上线就原地等待重试，不落回菜单。
        # 配合开机自启：窗口藏在后台，遥控器任何时候点图标，
        # 8123 的 /launch 都有人接 —— 这是"点图标启动模拟器"能成立的前提。
        no_launch = False       # R3 关游戏后转 True：手柄待命但不自动开游戏
        offline = 0             # 连续"遥控器不在线"次数（用于退避 + 日志限流）
        try:
            while True:
                code = auto_start(no_launch=no_launch)
                if code == 6:
                    print("\n[*] 已经有一个手柄窗口在跑了，直接用那个就行。")
                    print("    本窗口将在 3 秒后自动关闭。")
                    time.sleep(3)
                    return 0
                if code == 10:
                    # R3 主动关游戏：游戏保持关闭，但手柄+仪表服务要留在后台，
                    # 这样遥控器点图标（/launch）还能随时把模拟器再拉起来。
                    print("\n[*] 你按 R3 关掉了游戏。手柄转入待命：游戏不会自动弹出，")
                    print("    想再玩时点遥控器上的仪表图标即可重新启动模拟器。")
                    no_launch = True
                    time.sleep(3)
                    continue
                if code is None:
                    # 2026-11-14：遥控器关机/长时间离线的等待策略。
                    # 原来固定 8 秒一轮且每次都打印，遥控器关一晚上会刷几千行；
                    # 现在 8s 起步、每 5 次 +8s，最多 60s 一轮，日志只在
                    # 第一次和每 15 次说一句。遥控器一开机几分钟内就能接上。
                    offline += 1
                    if offline == 1:
                        print("\n[*] 遥控器不在线（没插线，无线也连不上）。")
                        print("    后台会自动重试，遥控器开机并连上同一 WiFi 后自己接上。")
                        print("    （不想等的话，在这个窗口按 Ctrl+C 退出）")
                    elif offline % 15 == 0:
                        mins = offline * 8 // 60
                        print(f"    [等待中] 已重试 {offline} 次(约 {mins} 分钟)，继续等遥控器上线…")
                    time.sleep(min(8 + (offline // 5) * 8, 60))
                    continue
                offline = 0
                # 其他退出码（异常/掉线）：重新等待，保持常驻
                # Ctrl+C 算正常退出：run_sim 在 wait=False 下会把它抛上来
                print(f"\n[*] 手柄已停止(码 {code})。5 秒后重新等待遥控器上线（Ctrl+C 退出）。")
                time.sleep(5)
        except KeyboardInterrupt:
            return 0

    while True:
        if not keep_screen:
            os.system("cls")
        keep_screen = False
        print(MENU)
        try:
            ch = input("请选择 0-11 (直接回车 = 10 无线启动) : ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if ch == "":
            ch = "10"         # 直接回车 = 无线启动（最常用）

        if ch == "1":
            os.system("cls")
            print("演示模式：手柄会自动摆杆。")
            print("现在切到 Uncrashed，看摇杆能不能动、能不能在 Controls 里绑定。")
            print("注意：Uncrashed 要在本窗口启动之后才打开。\n")
            run_sim("--demo", "--raw")
        elif ch == "2":
            os.system("cls")
            run_sim("--launch", "--raw")
        elif ch == "3":
            os.system("cls")
            print("窗口启动后，再去开游戏。按 Ctrl+C 结束。\n")
            run_sim("--raw")
        elif ch == "4":
            check()
        elif ch == "5":
            subprocess.call(["control", "joy.cpl"])
        elif ch == "6":
            os.system("cls")
            print("去 Uncrashed -> Controls 里绑定轴，本窗口会实时报告结果。")
            print("按 Ctrl+C 退出。\n")
            try:
                subprocess.call([PYEXE, "-u", str(HERE / "check_bindings.py")],
                                cwd=HERE_STR)
            except KeyboardInterrupt:
                pass
            input("\n按回车返回菜单…")
        elif ch == "7":
            os.system("cls")
            try:
                subprocess.call([PYEXE, "-u", str(HERE / "wait_rc.py")],
                                cwd=HERE_STR)
            except KeyboardInterrupt:
                pass
            input("\n按回车返回菜单…")
        elif ch == "8":
            reset_bindings()
        elif ch == "9":
            os.system("cls")
            print("注意：启动器窗口（rcplus_sim.py）必须保持运行，手柄才存在。")
            print("依次按遥控器上的每个键，看它对应哪个手柄按键。\n")
            try:
                subprocess.call([PYEXE, "-u", str(HERE / "btn_monitor.py")],
                                cwd=HERE_STR)
            except KeyboardInterrupt:
                pass
            input("\n按回车返回菜单…")
        elif ch == "10":
            wireless()
        elif ch == "11":
            os.system("cls")
            args = ["--wifi", (WIFI_IP_FILE.read_text().strip()
                               if WIFI_IP_FILE.exists() else None) or "192.168.31.174"]
            try:
                subprocess.call([PYEXE, "-u", str(HERE / "stick_screen.py"), *args],
                                cwd=HERE_STR)
            except KeyboardInterrupt:
                pass
            input("\n按回车返回菜单…")
        elif ch == "0":
            return 0
    return 0


WIFI_IP_FILE = HERE / "wifi_ip.txt"


def _rc_ip_from_usb():
    """趁遥控器插着线，读它的 WiFi IP。"""
    try:
        r = subprocess.run([ADB, "shell", "ip -f inet addr show wlan0"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=_NOWIN)
    except Exception:
        return None
    import re
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r.stdout or "")
    return m.group(1) if m else None


def _usb_serials():
    """当前插着线的 adb 设备（不含 IP:端口 这类无线设备）。"""
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True,
                           timeout=15, creationflags=_NOWIN)
    except Exception:
        return []
    return [l.split("\t")[0].strip() for l in (r.stdout or "").splitlines()[1:]
            if "\tdevice" in l and ":" not in l.split("\t")[0]]


def _wifi_up(ip):
    """确认 ip:5555 真的连上了（adb connect 返回成功也可能是假的）。

    2026-11-14 改：遥控器关机/不在同一网段时 adb connect 会一直卡到超时，
    原来没接住 TimeoutExpired，直接把常驻进程整个炸掉——遥控器一关机，
    launcher 就退出，开机后不会自动重连。现在超时=没连上，安静的返回 False。
    """
    try:
        subprocess.run([ADB, "connect", f"{ip}:5555"], capture_output=True,
                       timeout=12, creationflags=_NOWIN)
    except subprocess.TimeoutExpired:
        print("      （adb connect 超时，遥控器可能已关机或不在同一网络）")
        return False
    except Exception:
        return False
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True,
                           timeout=15, creationflags=_NOWIN)
    except Exception:
        return False
    return f"{ip}:5555" in (r.stdout or "")


def auto_start(no_launch=False):
    """双击启动用的全自动流程：有线优先（延迟最低、最稳），没线才走无线。

    2026-11-09 改的优先级：原来"无线优先"是为了图方便，但 WiFi adb 上
    dumpsys 这类命令会周期性把控制流挤停，飞行中每隔一阵"短暂断连"。
    现在插着线就用线（严格更稳），没线才自动连无线。

    no_launch=True：手柄待命模式——只起手柄+仪表服务，不自动开游戏。
    （R3 关游戏后转入这个模式：游戏保持关闭，但遥控器点图标仍能再启动）

    返回 rcplus_sim.py 的退出码；返回 None 表示两种连接方式都没成功，
    交给调用方落回菜单（那时候需要人介入，按回车是合理的）。
    """
    print("\n--- 自动启动：有线优先，没线自动转无线 ---\n")
    launch_args = [] if no_launch else ["--launch"]

    usb = _usb_serials()
    if usb:
        print(f"[1/3] 检测到 USB 数据线（{usb[0]}），直接走有线（延迟最低）…\n")
        return run_sim(*launch_args, "--raw", "--yes", wait=False)

    print("[1/3] 没插线，尝试无线…")
    ip = WIFI_IP_FILE.read_text().strip() if WIFI_IP_FILE.exists() else None
    print(f"      上次记住的 IP: {ip or '（没有记录）'}")
    if ip and _wifi_up(ip):
        WIFI_IP_FILE.write_text(ip)
        print(f"[2/3] 无线已连上（{ip}），正在启动手柄…\n")
        return run_sim("--wifi", ip, *launch_args, "--raw", "--yes", wait=False)

    print("[2/3] 无线没连上。")
    print("[3/3] 有线也没检测到设备。")
    return None


def wireless():
    """WiFi 无线模式：确保 adb-over-WiFi 连上，然后走正常启动流程。"""
    os.system("cls")
    print("--- 无线模式（adb over WiFi） ---\n")

    ip = None
    # 情况1：遥控器插着线 → 直接开 tcpip 并拿 IP
    if _usb_serials():
        print("[1/2] 检测到 USB 连接，开启 WiFi 调试模式…")
        subprocess.run([ADB, "tcpip", "5555"], capture_output=True, timeout=20)
        ip = _rc_ip_from_usb()
        if not ip:
            print("[!] 遥控器没连 WiFi。先在遥控器上连上和电脑同一个 WiFi 再试。")
            input("按回车返回菜单…")
            return
        print(f"      遥控器 WiFi IP: {ip}")
    else:
        # 情况2：没插线 → 用上次记住的 IP
        ip = WIFI_IP_FILE.read_text().strip() if WIFI_IP_FILE.exists() else None
        if not ip:
            print("[!] 遥控器没插线，也没有记住过 IP。")
            print("    第一次使用请插上数据线再选本项。")
            input("按回车返回菜单…")
            return
        print(f"[1/2] 使用上次的 IP: {ip}")

    print("[2/2] 连接无线 adb…")
    ok = _wifi_up(ip)
    if not ok:
        print("[!] 无线连接失败。可能原因：")
        print("    1) 遥控器没开机 / 没连同一个 WiFi")
        print("    2) 遥控器重启过 → WiFi 调试被关：插上数据线重跑本项")
        print("    3) IP 变了 → 插线重跑本项会自动更新")
        ans = input("\n按回车改为【有线】启动，输入 q 返回菜单：").strip().lower()
        if ans == "q":
            return
        run_sim("--launch", "--raw")
        return
    WIFI_IP_FILE.write_text(ip)
    print("      无线已连上，可以直接开飞。")
    run_sim("--wifi", ip, "--launch", "--raw")


def reset_bindings():
    """备份并清空 Uncrashed 的摇杆绑定存档。必须先关游戏。"""
    import shutil
    import time as _t

    saved = Path.home() / r"AppData\Local\Uncrashed\Saved\SaveGames"
    targets = [
        saved / "Settings" / "MyOptions.sav",
        saved / "RC" / "RC_.sav",
        saved / "RC" / "RC_actual.sav",
    ]
    os.system("cls")
    print("这一步会把 Uncrashed 的按键/轴绑定存档【备份后删除】，")
    print("下次启动游戏会重新生成默认值，相当于把绑乱的东西清零。\n")

    pids = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Uncrashed-Win64-Shipping.exe",
         "/FO", "CSV", "/NH"], capture_output=True).stdout.decode("gbk", "ignore")
    if "Uncrashed" in pids:
        print("[!] Uncrashed 正在运行。游戏退出时会把内存里的设置写回去，")
        print("    现在删了也白删。先关掉游戏再来。\n")
        ans = input("要我现在帮你关掉游戏吗？[y/N] ").strip().lower()
        if ans == "y":
            subprocess.run(["taskkill", "/IM", "Uncrashed-Win64-Shipping.exe", "/F"],
                           capture_output=True)
            time.sleep(3)
        else:
            input("已取消。按回车返回…")
            return

    print("\n将备份并删除以下文件：")
    for t in targets:
        print("  " + str(t) + ("  (存在)" if t.exists() else "  (不存在，跳过)"))
    ans = input("\n确认继续？[y/N] ").strip().lower()
    if ans != "y":
        input("已取消。按回车返回…")
        return

    bak = HERE / "binding_backup" / _t.strftime("%Y%m%d_%H%M%S")
    bak.mkdir(parents=True, exist_ok=True)
    for t in targets:
        if t.exists():
            rel = t.relative_to(saved)
            dst = bak / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(t), str(dst))
            print("  已备份 -> " + str(dst))

    print("\n完成。下次启动 Uncrashed 会生成全新的默认绑定。")
    print("然后：进 Controls → 选 XInput Controller #1 → Stick Calibration → 重新绑轴。")
    input("\n按回车返回菜单…")


if __name__ == "__main__":
    sys.exit(main())
