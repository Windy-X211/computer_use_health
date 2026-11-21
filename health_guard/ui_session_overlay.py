import datetime
import logging
import tkinter as tk

from health_guard import winapi

log = logging.getLogger("health_guard.ui_session_overlay")

TRANSPARENT_COLOR = "#010203"

POSITIONS = {
    "top-right": "右上角",
    "top-left": "左上角",
    "bottom-right": "右下角",
    "bottom-left": "左下角",
}


class SessionOverlayWindow:
    """透明置顶浮层，显示连续使用时间。

    - 默认位于屏幕右上角
    - 支持鼠标拖动改变位置(松手后记住坐标)
    - 通过 set_config 动态更新透明度 / 大小 / 是否显示
    """

    REFRESH_MS = 1000

    def __init__(self, root, controller, cfg):
        self.controller = controller
        self.cfg = cfg
        self._refresh_job = None
        self._drag_data = {"x": 0, "y": 0, "dragging": False}

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT_COLOR)
        self.win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        self._build_widgets()
        self._apply_config(cfg)
        self._bind_drag()

    def _build_widgets(self):
        self.container = tk.Frame(self.win, bg="#1a1f2e", padx=14, pady=10)
        self.container.pack(fill="both", expand=True)

        self.label_title = tk.Label(
            self.container,
            text="连续使用",
            font=("Microsoft YaHei UI", 10),
            bg="#1a1f2e",
            fg="#8899aa",
        )
        self.label_title.pack(anchor="w")

        self.label_time = tk.Label(
            self.container,
            text="00:00",
            font=("Consolas", 28, "bold"),
            bg="#1a1f2e",
            fg="#ffffff",
        )
        self.label_time.pack(anchor="w")

        self.label_hint = tk.Label(
            self.container,
            text="",
            font=("Microsoft YaHei UI", 9),
            bg="#1a1f2e",
            fg="#667788",
        )
        self.label_hint.pack(anchor="w")

    def _bind_drag(self):
        for widget in (self.win, self.container, self.label_title,
                       self.label_time, self.label_hint):
            widget.bind("<Button-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_end)

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x_root - self.win.winfo_x()
        self._drag_data["y"] = event.y_root - self.win.winfo_y()

    def _on_drag_motion(self, event):
        x = event.x_root - self._drag_data["x"]
        y = event.y_root - self._drag_data["y"]
        self.win.geometry(f"+{x}+{y}")

    def _on_drag_end(self, event):
        if self._drag_data["x"] == 0 and self._drag_data["y"] == 0:
            return
        x = self.win.winfo_x()
        y = self.win.winfo_y()
        self._drag_data["x"] = 0
        self._drag_data["y"] = 0
        self._remember_position(x, y)

    def _remember_position(self, x, y):
        try:
            import copy
            new_cfg = copy.deepcopy(self.controller.get_cfg())
            so = new_cfg.setdefault("session_overlay", {})
            so["pos_x"] = int(x)
            so["pos_y"] = int(y)
            self.controller.save_settings(new_cfg)
            log.info("overlay position saved: %d,%d", x, y)
        except Exception as exc:
            log.warning("failed to save overlay position: %s", exc)

    BASE_WIDTH = 180
    BASE_HEIGHT = 80

    def _apply_config(self, cfg):
        so = cfg.get("session_overlay", {}) if cfg else {}
        opacity_raw = max(0, min(100, float(so.get("opacity", 85))))
        opacity = opacity_raw / 100.0
        scale = max(20, min(200, int(so.get("scale", 100))))
        width = int(self.BASE_WIDTH * scale / 100)
        height = int(self.BASE_HEIGHT * scale / 100)
        self.win.attributes("-alpha", opacity)

        base = min(width, height)
        time_size = max(12, int(base * 0.30))
        title_size = max(8, int(base * 0.12))
        hint_size = max(7, int(base * 0.10))
        self.label_time.config(font=("Consolas", time_size, "bold"))
        self.label_title.config(
            font=("Microsoft YaHei UI", title_size)
        )
        self.label_hint.config(
            font=("Microsoft YaHei UI", hint_size)
        )

        if so.get("enabled", True):
            self._place(so, width, height)
            self.win.deiconify()
            self.win.lift()
            self._start_refresh()
        else:
            self._stop_refresh()
            self.win.withdraw()

    def _place(self, so, w, h):
        rect = winapi.virtual_screen_rect()
        margin = 16
        self.win.update_idletasks()

        px = so.get("pos_x")
        py = so.get("pos_y")
        if px is not None and py is not None:
            x, y = int(px), int(py)
        else:
            pos = so.get("position", "top-right")
            if pos == "top-left":
                x = rect.left + margin
                y = rect.top + margin
            elif pos == "bottom-right":
                x = rect.right - w - margin
                y = rect.bottom - h - margin - 60
            elif pos == "bottom-left":
                x = rect.left + margin
                y = rect.bottom - h - margin - 60
            else:
                x = rect.right - w - margin
                y = rect.top + margin
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _start_refresh(self):
        if self._refresh_job is None:
            self._refresh()

    def _stop_refresh(self):
        if self._refresh_job is not None:
            try:
                self.win.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None

    def _refresh(self):
        self._refresh_job = None
        try:
            state = self.controller.get_state()
            elapsed = state.session_seconds(datetime.datetime.now())
            dur_cfg = self.controller.get_cfg().get("duration", {})
            limit_min = int(dur_cfg.get("session_limit_minutes", 60))
            used_min = elapsed // 60
            self.label_time.config(text=f"{used_min}/{limit_min}分钟")

            if elapsed > limit_min * 60 * 0.8:
                remaining = max(0, limit_min * 60 - elapsed)
                self.label_hint.config(
                    text=f"剩余 {remaining // 60} 分钟,注意休息",
                    fg="#f0c040",
                )
            else:
                self.label_hint.config(
                    text="拖动可调整位置",
                    fg="#667788",
                )
        except tk.TclError:
            return
        except Exception as exc:
            log.warning("overlay refresh error: %s", exc)
        self._refresh_job = self.win.after(self.REFRESH_MS, self._refresh)

    def update_config(self, cfg):
        self.cfg = cfg
        try:
            self._apply_config(cfg)
        except Exception as exc:
            log.warning("overlay apply config failed: %s", exc)

    def refresh_now(self):
        try:
            self._refresh()
        except Exception:
            pass

    def destroy(self):
        self._stop_refresh()
        try:
            self.win.destroy()
        except tk.TclError:
            pass
