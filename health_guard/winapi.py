import ctypes
import os
import threading
import time
import uuid
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GUID_CONSOLE_DISPLAY_STATE = uuid.UUID("6fe69556-704a-47a0-8f24-c28d936fda47")
DISPLAY_STATE_OFF = 0

_SCREEN_OFF_FALLBACK_SECONDS = 300.0

SW_HIDE = 0
SW_MINIMIZE = 6
SW_RESTORE = 9

EWX_LOGOFF = 0
EWX_SHUTDOWN = 0x01
EWX_FORCE = 0x04
EWX_FORCEIFHUNG = 0x10

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_SCREENSAVE = 0xF140


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now = kernel32.GetTickCount()
    return max(0.0, (now - info.dwTime) / 1000.0)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_from_uuid(u: uuid.UUID) -> _GUID:
    g = _GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    g.Data4 = (ctypes.c_ubyte * 8)(
        u.clock_seq_hi_variant,
        u.clock_seq_low,
        (u.node >> 40) & 0xFF,
        (u.node >> 32) & 0xFF,
        (u.node >> 24) & 0xFF,
        (u.node >> 16) & 0xFF,
        (u.node >> 8) & 0xFF,
        u.node & 0xFF,
    )
    return g


_CONSOLE_DISPLAY_STATE_GUID = _guid_from_uuid(GUID_CONSOLE_DISPLAY_STATE)


class _PowerDisplayMonitor:
    """Background thread subscribing to display power-state changes via
    RegisterPowerSettingNotification and caching the latest state."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = 1
        self._last_notify_mono = None
        self._thread = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._run, name="powermon", daemon=True
        )
        self._thread.start()

    def state(self) -> int:
        with self._lock:
            return self._state

    def has_notification(self) -> bool:
        with self._lock:
            return self._last_notify_mono is not None

    def _set(self, value: int) -> None:
        with self._lock:
            self._state = value
            self._last_notify_mono = time.monotonic()

    def _run(self) -> None:
        LRESULT = ctypes.c_longlong
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        class WC(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        u = None
        hwnd = None
        nreg = None
        inst = None
        cls_name = "HealthGuard_PowerMon"
        try:
            u = ctypes.WinDLL("user32", use_last_error=True)
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            u.RegisterClassW.argtypes = [ctypes.POINTER(WC)]
            u.RegisterClassW.restype = wintypes.ATOM
            u.CreateWindowExW.argtypes = [
                wintypes.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p,
                wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                wintypes.HINSTANCE, ctypes.c_void_p,
            ]
            u.CreateWindowExW.restype = wintypes.HWND
            u.RegisterPowerSettingNotification.argtypes = [
                wintypes.HWND, ctypes.c_void_p, wintypes.DWORD,
            ]
            u.RegisterPowerSettingNotification.restype = ctypes.c_void_p
            u.UnregisterPowerSettingNotification.argtypes = [ctypes.c_void_p]
            u.UnregisterPowerSettingNotification.restype = wintypes.BOOL
            u.PeekMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                wintypes.UINT, wintypes.UINT,
            ]
            u.PeekMessageW.restype = wintypes.BOOL
            u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            u.DispatchMessageW.restype = LRESULT
            u.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            u.DefWindowProcW.restype = LRESULT
            u.DestroyWindow.argtypes = [wintypes.HWND]
            u.DestroyWindow.restype = wintypes.BOOL
            u.UnregisterClassW.argtypes = [
                ctypes.c_wchar_p, wintypes.HINSTANCE,
            ]
            u.UnregisterClassW.restype = wintypes.BOOL
            k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            k.GetModuleHandleW.restype = wintypes.HMODULE

            WM_DESTROY = 0x0002
            WM_QUIT = 0x0012
            WM_POWERBROADCAST = 0x0218
            PBT_POWERSETTINGCHANGE = 0x8013
            DEVICE_NOTIFY_WINDOW_HANDLE = 0

            def proc(hwnd, msg, wparam, lparam):
                if (
                    msg == WM_POWERBROADCAST
                    and wparam == PBT_POWERSETTINGCHANGE
                ):
                    try:
                        data = (ctypes.c_ubyte * 1).from_address(
                            lparam + 20
                        )
                        self._set(int(data[0]))
                    except Exception:
                        pass
                elif msg == WM_DESTROY:
                    u.PostQuitMessage(0)
                return u.DefWindowProcW(hwnd, msg, wparam, lparam)

            proc_ref = WNDPROC(proc)
            inst = k.GetModuleHandleW(None)
            wc = WC(
                lpfnWndProc=proc_ref,
                hInstance=inst,
                lpszClassName=cls_name,
            )
            atom = u.RegisterClassW(ctypes.byref(wc))
            if not atom:
                return
            hwnd = u.CreateWindowExW(
                0, cls_name, "hgpow", 0, 0, 0, 0, 0, None, None, inst, None,
            )
            if not hwnd:
                u.UnregisterClassW(cls_name, inst)
                return
            nreg = u.RegisterPowerSettingNotification(
                hwnd,
                ctypes.byref(_CONSOLE_DISPLAY_STATE_GUID),
                DEVICE_NOTIFY_WINDOW_HANDLE,
            )
            msg = wintypes.MSG()
            while True:
                while u.PeekMessageW(
                    ctypes.byref(msg), None, 0, 0, 1
                ):
                    u.DispatchMessageW(ctypes.byref(msg))
                    if msg.message == WM_QUIT:
                        break
                if msg.message == WM_QUIT:
                    break
                time.sleep(0.1)
        except Exception:
            return
        finally:
            if nreg and u:
                try:
                    u.UnregisterPowerSettingNotification(nreg)
                except Exception:
                    pass
            if hwnd and u:
                try:
                    u.DestroyWindow(hwnd)
                except Exception:
                    pass
            if inst and u:
                try:
                    u.UnregisterClassW(cls_name, inst)
                except Exception:
                    pass


_display_monitor = _PowerDisplayMonitor()
_display_monitor_started = False


def is_display_on() -> bool:
    """Return True when the monitor is on (or dimmed), False when fully off.

    Subscribes to live WM_POWERBROADCAST notifications for
    GUID_CONSOLE_DISPLAY_STATE, which the OS fires on every real display
    power change. Before the first notification arrives (or on systems where
    the API is unavailable), falls back to an idle heuristic so screen-off
    time still stops counting.
    """
    global _display_monitor_started
    if not _display_monitor_started:
        _display_monitor_started = True
        _display_monitor.start()
    if _display_monitor.has_notification():
        return _display_monitor.state() != DISPLAY_STATE_OFF
    return get_idle_seconds() < _SCREEN_OFF_FALLBACK_SECONDS


def lock_workstation() -> bool:
    return bool(user32.LockWorkStation())


def trigger_screensaver() -> bool:
    return bool(
        user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_SCREENSAVE, 0)
    )


def virtual_screen_rect() -> RECT:
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    SM_CXSCREEN = 0
    SM_CYSCREEN = 1
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if w <= 0 or h <= 0:
        x, y = 0, 0
        w = user32.GetSystemMetrics(SM_CXSCREEN)
        h = user32.GetSystemMetrics(SM_CYSCREEN)
    return RECT(x, y, x + w, y + h)


def is_screen_locked() -> bool:
    try:
        hwnd = user32.OpenInputDesktop(0, False, 0x0100)
        if not hwnd:
            return True
        user32.CloseDesktop(hwnd)
        return False
    except Exception:
        return False


EnumWindowsProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)


def _get_process_path(pid: int) -> str:
    if pid <= 0:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def enumerate_visible_windows(exe_cache: dict | None = None) -> list:
    results = []
    cache_ttl = 5.0
    now = time.monotonic()

    def _get_exe(pid: int) -> str:
        if exe_cache is not None:
            entry = exe_cache.get(pid)
            if entry and now - entry[1] < cache_ttl:
                return entry[0]
            path = _get_process_path(pid)
            exe = os.path.basename(path).lower() if path else ""
            exe_cache[pid] = (exe, now)
            return exe
        path = _get_process_path(pid)
        return os.path.basename(path).lower() if path else ""

    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _get_exe(pid.value)
        results.append(
            {
                "hwnd": hwnd,
                "title": title,
                "pid": pid.value,
                "exe": exe,
                "path": "",
            }
        )
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    if exe_cache is not None and len(exe_cache) > 512:
        cutoff = time.monotonic() - cache_ttl
        for pid, entry in list(exe_cache.items()):
            if entry[1] < cutoff:
                del exe_cache[pid]
    return results


def hide_window(hwnd) -> None:
    user32.ShowWindow(hwnd, SW_HIDE)


def minimize_window(hwnd) -> None:
    user32.ShowWindow(hwnd, SW_MINIMIZE)


def is_window_visible(hwnd) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_window_valid(hwnd) -> bool:
    return bool(user32.IsWindow(hwnd))


def shutdown_computer(message: str = "") -> None:
    os.system(f'shutdown /s /t 0 /c "{message[:120]}"')


def logoff_computer() -> None:
    os.system("shutdown /l")


def abort_shutdown() -> None:
    os.system("shutdown /a")


def register_hotkey(hwnd, hotkey_id: int, modifiers: int, vk: int) -> bool:
    return bool(
        user32.RegisterHotKey(wintypes.HWND(hwnd), hotkey_id, modifiers, vk)
    )


def unregister_hotkey(hwnd, hotkey_id: int) -> bool:
    return bool(user32.UnregisterHotKey(wintypes.HWND(hwnd), hotkey_id))


def mods_and_vk(keys: list) -> tuple:
    vk_map = {"u": 0x55, "x": 0x58, "h": 0x48, "s": 0x53, "q": 0x51}
    mod = 0
    vk = 0
    for k in keys:
        k = k.lower()
        if k == "ctrl" or k == "control":
            mod |= 0x0002
        elif k == "alt":
            mod |= 0x0001
        elif k == "shift":
            mod |= 0x0004
        elif k == "win":
            mod |= 0x0008
        elif k in vk_map:
            vk = vk_map[k]
    if vk == 0:
        vk = 0x55
    return mod, vk
