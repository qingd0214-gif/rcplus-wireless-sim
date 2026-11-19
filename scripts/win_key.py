# -*- coding: utf-8 -*-
"""win_key.py — 向当前前台窗口发键盘/鼠标事件（SendInput）
用途：
  1. 某些游戏对手柄动作绑定支持有 bug，改绑键盘最稳（tap）
  2. 纯鼠标向的 UI（如 Uncrashed 选地图界面）不认手柄十字键，
     五向键就改成推鼠标 + 模拟左键（mouse_move / mouse_click）
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002

# 鼠标事件标志
MOUSEEVENTF_MOVE = 0x0001        # 相对移动
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# 虚拟键码（常用）
VK = {
    'M': 0x4D, 'R': 0x52, 'T': 0x54, 'G': 0x47, 'H': 0x48, 'Y': 0x59, 'U': 0x55,
    'SPACE': 0x20, 'ENTER': 0x0D, 'ESC': 0x1B, 'TAB': 0x09,
    'BACKSPACE': 0x08, 'DELETE': 0x2E, 'F1': 0x70, 'F2': 0x71,
    'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
    'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]
    _anonymous_ = ('u',)
    _fields_ = [('type', wintypes.DWORD), ('u', _U)]


def _send(*events):
    arr = (INPUT * len(events))()
    for i, (kind, data) in enumerate(events):
        arr[i].type = kind
        if kind == INPUT_KEYBOARD:
            arr[i].ki = KEYBDINPUT(*data)
        else:
            arr[i].mi = MOUSEINPUT(*data)
    # SendInput 的 cbSize 必须是 sizeof(INPUT)（含最大的联合成员）
    ok = user32.SendInput(len(arr), ctypes.byref(arr), ctypes.sizeof(INPUT))
    return ok == len(arr)


def tap(key: str):
    """按一下再松开。key 例如 'R'、'SPACE'、'ESC'。"""
    vk = VK.get(key.upper())
    if vk is None:
        return False
    return _send((INPUT_KEYBOARD, (vk, 0, 0, 0, None)),
                 (INPUT_KEYBOARD, (vk, 0, KEYEVENTF_KEYUP, 0, None)))


def mouse_move(dx: int, dy: int):
    """相对移动鼠标光标（像素）。受系统"提高指针精确度"加速影响，
    实际位移可能与 dx/dy 不完全成比例——用法上无妨，推得越久走得越远。"""
    return _send((INPUT_MOUSE, (dx, dy, 0, MOUSEEVENTF_MOVE, 0, None)))


def mouse_click(button: str = "left"):
    """模拟一次完整的按下+松开。button: left / right。"""
    down, up = ((MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left"
                else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP))
    return _send((INPUT_MOUSE, (0, 0, 0, down, 0, None)),
                 (INPUT_MOUSE, (0, 0, 0, up, 0, None)))


if __name__ == '__main__':
    import sys
    import time
    k = sys.argv[1] if len(sys.argv) > 1 else 'R'
    print(f'3 秒后发送 {k}（请先切到目标窗口）')
    time.sleep(3)
    if k == 'click':
        print('已发送左键:', mouse_click())
    elif k == 'move':
        print('已发送移动:', mouse_move(200, 0))
    else:
        print('已发送:', tap(k))
