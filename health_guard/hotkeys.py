import ctypes
import logging
import threading
from ctypes import wintypes

from health_guard import winapi

log = logging.getLogger("health_guard.hotkeys")

WM_HOTKEY = 0x0312


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class HotkeyManager:
    def __init__(self):
        self._callbacks = {}
        self._thread = None
        self._stop = threading.Event()
        self._next_id = 1
        self._registered = {}
        self._pending = []

    def register(self, keys: list, callback) -> bool:
        hk_id = self._next_id
        self._next_id += 1
        mods, vk = winapi.mods_and_vk(keys)
        self._pending.append((hk_id, mods, vk, callback))
        return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._pump, daemon=True, name="hotkeys"
        )
        self._thread.start()

    def _pump(self) -> None:
        msg = MSG()
        _ = ctypes.windll.user32.PeekMessageW(
            ctypes.byref(msg), None, 0, 0, 0x0001
        )
        self._register_all()
        log.info("hotkey pump started")
        while not self._stop.is_set():
            result = ctypes.windll.user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0
            )
            if result == 0:
                break
            if result == -1:
                break
            if msg.message == WM_HOTKEY:
                cb = self._callbacks.get(int(msg.wParam))
                if cb:
                    try:
                        cb()
                    except Exception as exc:
                        log.error("hotkey callback error: %s", exc)
        self._cleanup()
        log.info("hotkey pump stopped")

    def _register_all(self) -> None:
        for hk_id, mods, vk, callback in self._pending:
            ok = winapi.register_hotkey(None, hk_id, mods, vk)
            if ok:
                self._callbacks[hk_id] = callback
                self._registered[hk_id] = (mods, vk)
                log.info("hotkey registered: id=%s", hk_id)
            else:
                log.warning("hotkey registration failed: id=%s", hk_id)
        self._pending.clear()

    def _cleanup(self) -> None:
        for hk_id in list(self._registered.keys()):
            winapi.unregister_hotkey(None, hk_id)
        self._registered.clear()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.ident is not None:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread.ident, 0x0012, 0, 0
            )
        self._cleanup()
