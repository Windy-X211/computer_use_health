import datetime
import logging
import tkinter as tk
from tkinter import ttk

log = logging.getLogger("health_guard.ui_dashboard")

BG = "#f5f6f8"
CARD_BG = "#ffffff"
BORDER = "#e6e8eb"
TEXT_DARK = "#1c1c1c"
TEXT_MED = "#5a6470"
TEXT_LIGHT = "#9aa3ad"
BLUE = "#2a6df4"
BLUE_DARK = "#1e55c4"
GREEN = "#1a7f37"
ORANGE = "#cc7a00"
RED = "#c0392b"
PURPLE = "#7d3cbd"

ACTION_LABELS = {
    "none": "仅提示",
    "overlay": "全屏拦截",
    "screensaver": "强制屏保",
    "lock": "锁定屏幕",
    "logoff": "注销",
    "shutdown": "关机",
}
MODE_LABELS = {
    "duration": "按时长",
    "schedule": "按时段",
    "both": "时长+时段",
}


def _color_for_ratio(ratio: float) -> str:
    if ratio < 0.7:
        return GREEN
    if ratio < 0.95:
        return ORANGE
    return RED


class ProgressBar:
    def __init__(self, parent, width, height=18, bg=BG):
        self.canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self._width = width
        self._height = height
        self._track_rect = self.canvas.create_rectangle(
            2, 2, width - 2, height - 2, fill="#eef0f2", outline=""
        )
        self._fill_rect = self.canvas.create_rectangle(
            2, 2, 2, height - 2, fill=GREEN, outline=""
        )
        self._pct_text = self.canvas.create_text(
            width // 2,
            height // 2,
            text="",
            fill=TEXT_DARK,
            font=("Microsoft YaHei UI", 8, "bold"),
        )

    def set(self, value, maximum, label=""):
        maximum = max(1, maximum)
        ratio = max(0.0, min(1.0, value / maximum))
        color = _color_for_ratio(ratio)
        fill_w = int((self._width - 4) * ratio) + 2
        self.canvas.coords(
            self._fill_rect, 2, 2, fill_w, self._height - 2
        )
        self.canvas.itemconfig(self._fill_rect, fill=color)
        text = label or f"{int(value)}/{int(maximum)}"
        self.canvas.itemconfig(self._pct_text, text=text)
        text_color = "#ffffff" if ratio > 0.45 else TEXT_DARK
        self.canvas.itemconfig(self._pct_text, fill=text_color)

    def pack(self, **kw):
        self.canvas.pack(**kw)


class Card:
    def __init__(self, parent, title=None, **kw):
        self.frame = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER,
                              highlightthickness=1, bd=0)
        if title:
            head = tk.Frame(self.frame, bg=CARD_BG)
            head.pack(fill="x", padx=14, pady=(12, 4))
            tk.Label(
                head,
                text=title,
                font=("Microsoft YaHei UI", 11, "bold"),
                bg=CARD_BG,
                fg=TEXT_MED,
            ).pack(anchor="w")
        self.body = tk.Frame(self.frame, bg=CARD_BG)
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def pack(self, **kw):
        self.frame.pack(**kw)


class DashboardWindow:
    """Controls and status view.

    Builds its widgets into the given container instead of owning a Toplevel,
    so it can be embedded as a tab of the merged control/settings window.
    """

    def __init__(self, parent, controller):
        self.controller = controller
        self.win = parent
        self._refresh_job = None
        self._build()
        self._schedule_refresh()

    def stop_refresh(self):
        if self._refresh_job is not None:
            try:
                self.win.after_cancel(self._refresh_job)
            except (tk.TclError, ValueError):
                pass
            self._refresh_job = None

    def _build(self):
        self._build_header()
        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self._build_status_cards(body)
        self._build_quick_controls(body)
        self._build_time_settings(body)

    def _build_header(self):
        header = tk.Frame(self.win, bg=CARD_BG, highlightbackground=BORDER,
                          highlightthickness=1)
        header.pack(fill="x", padx=16, pady=16)
        inner = tk.Frame(header, bg=CARD_BG)
        inner.pack(fill="x", padx=18, pady=14)

        left = tk.Frame(inner, bg=CARD_BG)
        left.pack(side="left", anchor="w")
        tk.Label(
            left,
            text="💻  电脑使用健康管家",
            font=("Microsoft YaHei UI", 20, "bold"),
            bg=CARD_BG,
            fg=TEXT_DARK,
        ).pack(anchor="w")
        self.lbl_status_line = tk.Label(
            left,
            text="",
            font=("Microsoft YaHei UI", 12),
            bg=CARD_BG,
            fg=TEXT_MED,
        )
        self.lbl_status_line.pack(anchor="w", pady=(2, 0))

        right = tk.Frame(inner, bg=CARD_BG)
        right.pack(side="right", anchor="e")
        self.lbl_clock = tk.Label(
            right,
            text="",
            font=("Consolas", 22, "bold"),
            bg=CARD_BG,
            fg=BLUE,
        )
        self.lbl_clock.pack(anchor="e")
        self.lbl_date = tk.Label(
            right,
            text="",
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=TEXT_LIGHT,
        )
        self.lbl_date.pack(anchor="e")

    def _build_status_cards(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 12))

        card_daily = Card(row, "今日使用")
        card_daily.frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.lbl_daily_value = tk.Label(
            card_daily.body,
            text="0 / 240 分钟",
            font=("Microsoft YaHei UI", 16, "bold"),
            bg=CARD_BG,
            fg=TEXT_DARK,
        )
        self.lbl_daily_value.pack(anchor="w")
        self.pb_daily = ProgressBar(card_daily.body, width=240)
        self.pb_daily.pack(fill="x", pady=(6, 0))
        self.lbl_daily_hint = tk.Label(
            card_daily.body,
            text="",
            font=("Microsoft YaHei UI", 9),
            bg=CARD_BG,
            fg=TEXT_LIGHT,
        )
        self.lbl_daily_hint.pack(anchor="w", pady=(4, 0))

        card_session = Card(row, "连续使用")
        card_session.frame.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.lbl_session_value = tk.Label(
            card_session.body,
            text="0 / 60 分钟",
            font=("Microsoft YaHei UI", 16, "bold"),
            bg=CARD_BG,
            fg=TEXT_DARK,
        )
        self.lbl_session_value.pack(anchor="w")
        self.pb_session = ProgressBar(card_session.body, width=240)
        self.pb_session.pack(fill="x", pady=(6, 0))
        self.lbl_session_hint = tk.Label(
            card_session.body,
            text="",
            font=("Microsoft YaHei UI", 9),
            bg=CARD_BG,
            fg=TEXT_LIGHT,
        )
        self.lbl_session_hint.pack(anchor="w", pady=(4, 0))

    def _build_quick_controls(self, parent):
        card = Card(parent, "⚡ 快速控制")
        card.frame.pack(fill="x", pady=(0, 12))

        row1 = tk.Frame(card.body, bg=CARD_BG)
        row1.pack(fill="x", pady=(0, 8))
        self._build_toggle(row1, "限制总开关", "enabled")
        self._build_toggle(row1, "拦截指定应用", "block_apps")
        self._build_toggle(row1, "AI 门卫", "gatekeeper_enabled")

        row2 = tk.Frame(card.body, bg=CARD_BG)
        row2.pack(fill="x")
        self._build_mode_selector(row2)
        self._build_action_selector(row2)

    def _build_toggle(self, parent, label, key):
        wrap = tk.Frame(parent, bg=CARD_BG)
        wrap.pack(side="left", padx=(0, 18))
        tk.Label(
            wrap,
            text=label,
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=TEXT_MED,
        ).pack(anchor="w")
        switch = tk.Frame(wrap, bg=CARD_BG)
        switch.pack(anchor="w", pady=(2, 0))
        self._toggles = getattr(self, "_toggles", {})
        btn = tk.Label(
            switch,
            text="●○",
            font=("Segoe UI", 16),
            bg=CARD_BG,
            fg="#cccccc",
            cursor="hand2",
        )
        btn.pack(side="left")
        lbl = tk.Label(
            switch,
            text="关闭",
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=TEXT_MED,
        )
        lbl.pack(side="left", padx=(4, 0))
        self._toggles[key] = (btn, lbl)

        def on_click(e, k=key, b=btn, l=lbl):
            cur = self._toggle_states.get(k, False)
            self.controller.apply_quick_change(k, not cur)

        btn.bind("<Button-1>", on_click)
        lbl.bind("<Button-1>", on_click)

    def _build_mode_selector(self, parent):
        wrap = tk.Frame(parent, bg=CARD_BG)
        wrap.pack(side="left", padx=(0, 18))
        tk.Label(
            wrap,
            text="限制模式",
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=TEXT_MED,
        ).pack(anchor="w")
        self.var_mode = tk.StringVar()
        cb = ttk.Combobox(
            wrap,
            textvariable=self.var_mode,
            values=list(MODE_LABELS.values()),
            state="readonly",
            width=12,
            font=("Microsoft YaHei UI", 10),
        )
        cb.pack(anchor="w", pady=(2, 0))
        cb.bind("<MouseWheel>", lambda e: "break")
        cb.bind("<Button-4>", lambda e: "break")
        cb.bind("<Button-5>", lambda e: "break")
        cb.bind("<<ComboboxSelected>>", self._on_mode_change)

    def _build_action_selector(self, parent):
        wrap = tk.Frame(parent, bg=CARD_BG)
        wrap.pack(side="left", padx=(0, 18))
        tk.Label(
            wrap,
            text="达到上限后",
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=TEXT_MED,
        ).pack(anchor="w")
        self.var_action = tk.StringVar()
        cb = ttk.Combobox(
            wrap,
            textvariable=self.var_action,
            values=list(ACTION_LABELS.values()),
            state="readonly",
            width=12,
            font=("Microsoft YaHei UI", 10),
        )
        cb.pack(anchor="w", pady=(2, 0))
        cb.bind("<MouseWheel>", lambda e: "break")
        cb.bind("<Button-4>", lambda e: "break")
        cb.bind("<Button-5>", lambda e: "break")
        cb.bind("<<ComboboxSelected>>", self._on_action_change)

    def _build_time_settings(self, parent):
        card = Card(parent, "⏱ 时长设置")
        card.frame.pack(fill="x", pady=(0, 12))
        self._steppers = {}
        self._build_stepper(card.body, "每日使用上限", "daily_limit_minutes",
                            1, 1440, "分钟")
        self._build_stepper(card.body, "单次连续使用", "session_limit_minutes",
                            1, 480, "分钟")
        self._build_stepper(card.body, "强制休息时长", "break_minutes",
                            0, 240, "分钟")
        self._build_stepper(card.body, "倒计时警告", "warning_seconds",
                            0, 300, "秒")

    def _build_stepper(self, parent, label, key, lo, hi, unit):
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill="x", pady=3)
        tk.Label(
            row,
            text=label,
            font=("Microsoft YaHei UI", 11),
            bg=CARD_BG,
            fg=TEXT_DARK,
            width=14,
            anchor="w",
        ).pack(side="left")
        self._steppers[key] = tk.IntVar()
        tk.Button(
            row,
            text="－",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#eef0f2",
            fg=TEXT_DARK,
            relief="flat",
            width=3,
            command=lambda k=key, l=lo: self._step(k, -1, l),
        ).pack(side="left", padx=(0, 4))
        ent = tk.Entry(
            row,
            textvariable=self._steppers[key],
            width=6,
            font=("Consolas", 12),
            justify="center",
        )
        ent.pack(side="left")
        tk.Button(
            row,
            text="＋",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#eef0f2",
            fg=TEXT_DARK,
            relief="flat",
            width=3,
            command=lambda k=key, h=hi: self._step(k, 1, h),
        ).pack(side="left", padx=(4, 0))
        tk.Label(
            row,
            text=unit,
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=TEXT_LIGHT,
        ).pack(side="left", padx=(6, 0))

    def _step(self, key, delta, limit):
        cur = self._steppers[key].get()
        new = cur + delta
        if delta < 0:
            new = max(limit, new)
        else:
            new = min(limit, new)
        self._steppers[key].set(new)
        self.controller.apply_quick_change(key, new)

    def _on_mode_change(self, event):
        idx = MODE_LABELS.values()
        labels = list(MODE_LABELS.values())
        sel = self.var_mode.get()
        for k, v in MODE_LABELS.items():
            if v == sel:
                self.controller.apply_quick_change("mode", k)
                return

    def _on_action_change(self, event):
        sel = self.var_action.get()
        for k, v in ACTION_LABELS.items():
            if v == sel:
                self.controller.apply_quick_change("primary_action", k)
                return

    def _schedule_refresh(self):
        try:
            self._refresh(None)
            self._refresh_job = self.win.after(1500, self._schedule_refresh)
        except tk.TclError:
            self._refresh_job = None
        except Exception as exc:
            log.exception("dashboard refresh schedule failed: %s", exc)
            self._refresh_job = None

    def _refresh(self, event):
        try:
            st = self.controller.get_dashboard_state()
        except Exception as exc:
            log.exception("dashboard refresh failed: %s", exc)
            return
        self._toggle_states = st.get("toggles", {})
        now = datetime.datetime.now()
        self.lbl_clock.config(text=now.strftime("%H:%M:%S"))
        self.lbl_date.config(text=now.strftime("%Y-%m-%d ") + [
            "周一", "周二", "周三", "周四", "周五", "周六", "周日"
        ][now.weekday()])
        if st.get("paused"):
            self.lbl_status_line.config(
                text=f"⏸ 限制已暂停 · {st.get('reason', '')}",
                fg=ORANGE,
            )
        elif st.get("safe_mode"):
            self.lbl_status_line.config(
                text="🛡 安全模式 · 限制未启用", fg=ORANGE
            )
        elif not st.get("enabled"):
            self.lbl_status_line.config(
                text="限制已关闭 · 可在右侧开启", fg=TEXT_LIGHT
            )
        elif st.get("allowed"):
            self.lbl_status_line.config(
                text=f"✅ {st.get('reason', '允许使用')}", fg=GREEN
            )
        else:
            self.lbl_status_line.config(
                text=f"⛔ {st.get('reason', '使用受限')}", fg=RED
            )
        daily_used = st["daily_used_sec"]
        daily_max = st["daily_limit_sec"]
        self.lbl_daily_value.config(
            text=f"{daily_used // 60} / {daily_max // 60} 分钟"
        )
        self.pb_daily.set(daily_used, daily_max,
                          label=f"{daily_used // 60}/{daily_max // 60} 分钟")
        remaining = max(0, daily_max - daily_used)
        self.lbl_daily_hint.config(
            text=f"剩余 {remaining // 60} 分钟"
            + (f" · 紧急放行 {st.get('grant_min', 0)} 分钟"
               if st.get("grant_min", 0) > 0 else "")
        )
        sess = st["session_sec"]
        sess_max = st["session_limit_sec"]
        self.lbl_session_value.config(
            text=f"{sess // 60} / {sess_max // 60} 分钟"
        )
        self.pb_session.set(sess, sess_max,
                            label=f"{sess // 60}/{sess_max // 60} 分钟")
        self.lbl_session_hint.config(
            text=("休息中…" if st.get("in_break") else
                  f"剩余 {max(0, sess_max - sess) // 60} 分钟")
        )
        for k, (btn, lbl) in self._toggles.items():
            on = self._toggle_states.get(k, False)
            btn.config(fg=GREEN if on else "#cccccc",
                       text="●" if on else "○")
            lbl.config(text="开启" if on else "关闭",
                       fg=GREEN if on else TEXT_MED)
        if self.var_mode.get() not in MODE_LABELS.values():
            self.var_mode.set(MODE_LABELS.get(st.get("mode", "duration"), "按时长"))
        if self.var_action.get() not in ACTION_LABELS.values():
            self.var_action.set(
                ACTION_LABELS.get(st.get("primary_action", "screensaver"),
                                  "强制屏保")
            )
        for key, var in self._steppers.items():
            if key in st.get("steppers", {}):
                cur = var.get()
                new = st["steppers"][key]
                if cur != new:
                    var.set(new)

    def update_state(self):
        self._refresh(None)
