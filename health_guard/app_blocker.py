import logging
import threading
import time

from health_guard import winapi

log = logging.getLogger("health_guard.app_blocker")


class AppBlocker:
    def __init__(self, cfg_provider, interval: float = 2.0):
        self._cfg_provider = cfg_provider
        self._interval = interval
        self._enabled = False
        self._hidden = set()
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            changed = self._enabled != enabled
            self._enabled = enabled
        if changed:
            if enabled:
                self._start()
            else:
                self._stop_thread()
                self._restore_all()

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="app-blocker"
        )
        self._thread.start()

    def _stop_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=2)
        self._thread = None

    def _restore_all(self) -> None:
        with self._lock:
            hidden = list(self._hidden)
            self._hidden = set()
        for hwnd in hidden:
            try:
                if hwnd and winapi.is_window_visible(hwnd) is False:
                    winapi.user32.ShowWindow(hwnd, 5)
            except Exception:
                pass

    def _loop(self) -> None:
        log.info("app blocker started")
        exe_cache: dict = {}
        while not self._stop.is_set():
            try:
                with self._lock:
                    if not self._enabled:
                        break
                    blocked = self._cfg_provider().get("strategy", {}).get(
                        "blocked_apps", []
                    )
                blocked = {b.strip().lower() for b in blocked if b.strip()}
                if blocked:
                    now_hidden = set()
                    for w in winapi.enumerate_visible_windows(exe_cache):
                        if self._stop.is_set():
                            break
                        exe = (w.get("exe") or "").lower()
                        if exe in blocked:
                            try:
                                if winapi.is_window_visible(w["hwnd"]):
                                    winapi.hide_window(w["hwnd"])
                                    log.info("blocked window: %s (%s)", w["title"], exe)
                                now_hidden.add(w["hwnd"])
                            except Exception:
                                pass
                    with self._lock:
                        if now_hidden:
                            self._hidden |= now_hidden
                        if len(self._hidden) > 256:
                            self._hidden = {
                                hwnd
                                for hwnd in self._hidden
                                if winapi.is_window_valid(hwnd)
                            }
            except Exception as exc:
                log.error("app blocker error: %s", exc)
            self._stop.wait(self._interval)
        log.info("app blocker stopped")
