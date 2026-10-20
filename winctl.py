"""Drive one desktop window from the phone: list windows, picture one, click and type into it.

Capture uses PrintWindow with PW_RENDERFULLCONTENT, so a window can be pictured while another
window covers it. Clicks and keys go through SendInput, which needs the target in the foreground;
focus() brings it there. All of this only works while the desktop session is unlocked.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import io
import threading
import time

import win32api
import win32con
import win32gui
import win32process
import win32ui
import win32service
from PIL import Image, ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:  # physical pixels everywhere, so rects, captures and clicks agree
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

PW_RENDERFULLCONTENT = 2
DWMWA_CLOAKED = 14
_lock = threading.Lock()


class WinError(Exception):
    """Something the person can act on: window gone, minimized, could not focus."""


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float | None:
    """Seconds since anyone used this PC's keyboard or mouse (None when Windows will not say)."""
    info = _LastInput()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


_sent_ticks: tuple[int, int] | None = None  # GetTickCount() before and after this service last pressed keys or clicked


def person_idle_seconds() -> float | None:
    """Seconds since a person used this PC's keyboard or mouse. None when Windows will not say, and when the last
    input was this service's own key presses or clicks (SendInput, sent for the phone): Windows counts those as use,
    so nothing then tells whether anyone is here."""
    info = _LastInput()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    if _sent_ticks is not None:
        def after(tick: int) -> int:  # signed milliseconds from tick to the last input; the count wraps every 49 days
            return ((info.dwTime - tick + 2 ** 31) & 0xFFFFFFFF) - 2 ** 31
        if after(_sent_ticks[0]) >= -50 and after(_sent_ticks[1]) <= 1000:
            return None
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def input_desktop_ready() -> bool:
    """Read the interactive desktop identity without switching or unlocking it."""
    desktop = None
    try:
        desktop = win32service.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS
        return win32service.GetUserObjectInformation(desktop, 2).casefold() == 'default'
    except Exception:
        return False
    finally:
        if desktop is not None:
            desktop.CloseDesktop()


# ---------------------------------------------------------------- windows


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.replace("\\", "/").rsplit("/", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _cloaked(hwnd: int) -> bool:
    value = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        return False
    return bool(value.value)


def list_windows() -> list[dict]:
    found: list[dict] = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            return
        if _cloaked(hwnd):
            return
        minimized = bool(win32gui.IsIconic(hwnd))
        if minimized:  # a minimized window sits off-screen with a tiny rect; use its normal size instead
            try:
                _, _, _, _, (left, top, right, bottom) = win32gui.GetWindowPlacement(hwnd)
            except Exception:
                left = top = right = bottom = 0
        else:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left < 80 or bottom - top < 60:
                return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        found.append({"hwnd": int(hwnd), "title": title[:90], "process": _process_name(pid),
                      "width": right - left, "height": bottom - top, "minimized": minimized,
                      "foreground": win32gui.GetForegroundWindow() == hwnd})

    win32gui.EnumWindows(visit, None)
    return found


def exists(hwnd: int) -> bool:
    return bool(hwnd) and bool(win32gui.IsWindow(hwnd))


def info(hwnd: int) -> dict:
    if not exists(hwnd):
        raise WinError("那个窗口已经不在了，重新选一个")
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return {"hwnd": int(hwnd), "title": win32gui.GetWindowText(hwnd)[:90], "left": left, "top": top,
            "width": right - left, "height": bottom - top, "minimized": bool(win32gui.IsIconic(hwnd)),
            "foreground": win32gui.GetForegroundWindow() == hwnd}


# ---------------------------------------------------------------- capture


def capture(hwnd: int, quality: int = 55, max_width: int | None = None) -> tuple[bytes, int, int]:
    """JPEG of the whole window (frame included) plus the window size in physical pixels.

    max_width shrinks the picture before encoding; taps still use relative coordinates, so the
    window size returned here is what matters for mapping, not the picture size."""
    image, width, height = grab_image(hwnd)
    if max_width and image.width > max_width:
        image = image.resize((max_width, max(1, round(image.height * max_width / image.width))), Image.BILINEAR)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), width, height


def grab_image(hwnd: int):
    """The window as a PIL image plus its size."""
    if not exists(hwnd):
        raise WinError("那个窗口已经不在了，重新选一个")
    if win32gui.IsIconic(hwnd):
        restore(hwnd)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise WinError("窗口没有大小，可能被最小化了")
    with _lock:
        image = _print_window(hwnd, width, height)
    if image is None or image.getbbox() is None:  # PrintWindow failed or gave a black frame
        focus(hwnd, strict=False)
        time.sleep(0.15)
        image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
    return image, width, height


def thumbprint(image) -> bytes:
    """A small grayscale version, for telling whether the picture changed."""
    return image.resize((160, 90), Image.BILINEAR).convert("L").tobytes()


def changed(a: bytes | None, b: bytes, min_pixels: int = 3, min_delta: int = 24) -> bool:
    """True when at least a few thumbnail pixels moved clearly; a few typed letters count, sensor noise does not."""
    if a is None or len(a) != len(b):
        return True
    n = 0
    for x, y in zip(a, b):
        if abs(x - y) > min_delta:
            n += 1
            if n >= min_pixels:
                return True
    return False


def _print_window(hwnd: int, width: int, height: int):
    window_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(window_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        ok = user32.PrintWindow(wt.HWND(hwnd), save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if not ok:
            return None
        meta = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer("RGB", (meta["bmWidth"], meta["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    finally:
        try:
            win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)


# ---------------------------------------------------------------- focus


def restore(hwnd: int) -> None:
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.3)


def minimize(hwnd: int) -> None:
    if not exists(hwnd):
        raise WinError("那个窗口已经不在了，重新选一个")
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)


def _is_front(hwnd: int) -> bool:
    fg = win32gui.GetForegroundWindow()
    if fg == hwnd:
        return True
    try:
        return win32gui.GetAncestor(fg, 2) == hwnd  # GA_ROOT: a popup of the target counts
    except Exception:
        return False


def focus(hwnd: int, strict: bool = True) -> bool:
    """Bring the window to the front so keys and clicks reach it."""
    if not exists(hwnd):
        raise WinError("那个窗口已经不在了，重新选一个")
    if win32gui.IsIconic(hwnd):
        restore(hwnd)
    if _is_front(hwnd):
        return True
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.12)
    if _is_front(hwnd):
        return True
    # Windows refuses foreground changes from a background process; attaching to the
    # current foreground thread is the quiet way around it (no fake key presses, which
    # would open an app's menu bar).
    fg = win32gui.GetForegroundWindow()
    fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if fg_thread and fg_thread != me:
            attached = bool(user32.AttachThreadInput(me, fg_thread, True))
        win32gui.BringWindowToTop(hwnd)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    time.sleep(0.12)
    if _is_front(hwnd):
        return True
    _key_tap(win32con.VK_CONTROL)  # last resort: a harmless real input event unlocks the foreground
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.15)
    if _is_front(hwnd):
        return True
    if strict:
        raise WinError("没能把窗口拉到前台；电脑可能锁屏了，或者有别的程序霸着前台")
    return False


# ---------------------------------------------------------------- input (SendInput)


PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", PUL)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", PUL)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800

VK = {
    "Enter": 0x0D, "Escape": 0x1B, "Tab": 0x09, "Backspace": 0x08, "Delete": 0x2E, "Space": 0x20,
    "ArrowUp": 0x26, "ArrowDown": 0x28, "ArrowLeft": 0x25, "ArrowRight": 0x27,
    "PageUp": 0x21, "PageDown": 0x22, "Home": 0x24, "End": 0x23, "Insert": 0x2D,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75, "F11": 0x7A, "F12": 0x7B,
    "Control": 0x11, "Shift": 0x10, "Alt": 0x12, "Win": 0x5B,
}
MODIFIERS = {"Control": 0x11, "Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12, "Win": 0x5B}


def _send(inputs: list[INPUT]) -> None:
    global _sent_ticks
    array = (INPUT * len(inputs))(*inputs)
    before = kernel32.GetTickCount()
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    _sent_ticks = (before, kernel32.GetTickCount())
    if sent != len(inputs):
        raise WinError("按键没送进去；电脑可能锁屏了")


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.u.ki = KEYBDINPUT(vk, scan, flags, 0, None)
    return item


def _mouse_input(flags: int, data: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_MOUSE
    item.u.mi = MOUSEINPUT(0, 0, data, flags, 0, None)
    return item


def _key_tap(vk: int) -> None:
    _send([_key_input(vk), _key_input(vk, flags=KEYEVENTF_KEYUP)])


def type_text(hwnd: int, text: str, enter: bool = False) -> None:
    focus(hwnd)
    for ch in text:
        if ch == "\n":
            _key_tap(VK["Enter"])
            continue
        if ch == "\t":
            _key_tap(VK["Tab"])
            continue
        raw = ch.encode("utf-16-le")
        units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]  # surrogate pairs for emoji
        _send([_key_input(0, u, KEYEVENTF_UNICODE) for u in units] + [_key_input(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP) for u in units])
        time.sleep(0.01)
    if enter:
        time.sleep(0.05)
        _key_tap(VK["Enter"])


def press(hwnd: int, combo: str) -> None:
    """'Enter', 'Control+c', 'Control+Shift+v', 'a' ..."""
    focus(hwnd)
    parts = [p for p in combo.replace(" ", "").split("+") if p]
    if not parts:
        raise WinError("没有按键")
    *mods, key = parts
    mod_vks = []
    for m in mods:
        if m not in MODIFIERS:
            raise WinError(f"不认识的修饰键 {m}")
        mod_vks.append(MODIFIERS[m])
    if key in VK:
        vk = VK[key]
    elif len(key) == 1:
        vk = win32api.VkKeyScan(key) & 0xFF
    else:
        raise WinError(f"不认识的按键 {key}")
    seq = [_key_input(v) for v in mod_vks] + [_key_input(vk), _key_input(vk, flags=KEYEVENTF_KEYUP)]
    seq += [_key_input(v, flags=KEYEVENTF_KEYUP) for v in reversed(mod_vks)]
    _send(seq)


def _to_screen(hwnd: int, x_rel: float, y_rel: float) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    x = left + int(round(max(0.0, min(1.0, x_rel)) * (right - left - 1)))
    y = top + int(round(max(0.0, min(1.0, y_rel)) * (bottom - top - 1)))
    return x, y


def click(hwnd: int, x_rel: float, y_rel: float, button: str = "left", double: bool = False) -> tuple[int, int]:
    focus(hwnd)
    x, y = _to_screen(hwnd, x_rel, y_rel)
    win32api.SetCursorPos((x, y))
    time.sleep(0.05)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right" else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    _send([_mouse_input(down), _mouse_input(up)])
    if double:
        time.sleep(0.08)
        _send([_mouse_input(down), _mouse_input(up)])
    return x, y


def click_screen(hwnd: int, x: int, y: int) -> None:
    """Left click at a screen position (from UI Automation) after bringing hwnd to the front."""
    focus(hwnd)
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.05)
    _send([_mouse_input(MOUSEEVENTF_LEFTDOWN), _mouse_input(MOUSEEVENTF_LEFTUP)])


def scroll(hwnd: int, x_rel: float, y_rel: float, notches: int) -> None:
    """Positive notches scroll up, negative down, at the given spot."""
    focus(hwnd)
    x, y = _to_screen(hwnd, x_rel, y_rel)
    win32api.SetCursorPos((x, y))
    time.sleep(0.05)
    _send([_mouse_input(MOUSEEVENTF_WHEEL, ctypes.c_ulong(notches * 120 & 0xFFFFFFFF).value)])
