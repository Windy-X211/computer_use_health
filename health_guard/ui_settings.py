import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from health_guard import winapi
from health_guard.ui_dashboard import (
    BG as DASH_BG,
    GREEN,
    ORANGE,
    RED,
    TEXT_DARK,
    TEXT_LIGHT,
    DashboardWindow,
)

log = logging.getLogger("health_guard.ui_settings")


def _row(parent, label_text):
    frame = tk.Frame(parent, bg="#ffffff")
    frame.pack(fill="x", padx=12, pady=3)
    tk.Label(
        frame,
        text=label_text,
        font=("Microsoft YaHei UI", 11),
        bg="#ffffff",
        fg="#333333",
        width=18,
        anchor="w",
    ).pack(side="left")
    return frame


class ScheduleWindowDialog:
    def __init__(self, parent, on_ok):
        self.win = tk.Toplevel(parent)
        self.win.title("新增使用时段")
        self.win.geometry("360x320")
        self.win.configure(bg="#f5f6f8")
        self.win.resizable(False, False)
        self.on_ok = on_ok
        self.win.transient(parent)
        self.win.grab_set()

        tk.Label(
            self.win,
            text="选择适用的星期",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack(anchor="w", padx=16, pady=(12, 2))
        days_row = tk.Frame(self.win, bg="#f5f6f8")
        days_row.pack(fill="x", padx=16)
        self.day_vars = {}
        for i, name in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            var = tk.BooleanVar(value=True)
            self.day_vars[i] = var
            tk.Checkbutton(
                days_row, text=name, variable=var, bg="#f5f6f8"
            ).pack(side="left", padx=3)

        tk.Label(
            self.win,
            text="开始时间(如 08:00)",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack(anchor="w", padx=16, pady=(8, 2))
        self.entry_start = tk.Entry(self.win, font=("Consolas", 12))
        self.entry_start.insert(0, "08:00")
        self.entry_start.pack(fill="x", padx=16)

        tk.Label(
            self.win,
            text="结束时间(如 22:00,可跨天)",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack(anchor="w", padx=16, pady=(8, 2))
        self.entry_end = tk.Entry(self.win, font=("Consolas", 12))
        self.entry_end.insert(0, "22:00")
        self.entry_end.pack(fill="x", padx=16)

        tk.Button(
            self.win,
            text="确定",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#2a6df4",
            fg="#ffffff",
            relief="flat",
            padx=20,
            pady=6,
            command=self._ok,
        ).pack(pady=14)

    def _ok(self):
        try:
            start = self.entry_start.get().strip()
            end = self.entry_end.get().strip()
            hh, mm = start.split(":")
            int(hh)
            int(mm)
            hh2, mm2 = end.split(":")
            int(hh2)
            int(mm2)
        except Exception:
            messagebox.showerror("错误", "时间格式应为 HH:MM", parent=self.win)
            return
        days = [i for i, v in self.day_vars.items() if v.get()]
        if not days:
            messagebox.showerror("错误", "请至少选择一个星期", parent=self.win)
            return
        self.on_ok({"days": days, "start": start, "end": end})
        self.win.destroy()


class SettingsWindow:
    """Merged control-panel + settings window.

    The first notebook tab hosts the realtime control panel (status cards,
    quick toggles, time steppers) while the remaining tabs hold the detailed
    settings that are applied with the "保存设置" button.
    """

    def __init__(self, root, controller, cfg):
        self.controller = controller
        self.cfg = cfg
        self.win = tk.Toplevel(root)
        self.win.title("电脑使用健康管家 · 控制与设置")
        self.win.configure(bg="#f5f6f8")
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._save_job = None
        self._build()
        self._fit_window()

    def _fit_window(self):
        try:
            self.win.update_idletasks()
            want_w = self.win.winfo_reqwidth()
            want_h = self.win.winfo_reqheight()
        except tk.TclError:
            want_w, want_h = 820, 900
        rect = winapi.virtual_screen_rect()
        avail_w = max(400, rect.right - rect.left)
        avail_h = max(400, rect.bottom - rect.top)
        w = max(760, min(want_w, avail_w - 60))
        h = max(680, min(want_h, avail_h - 60))
        x = rect.left + (avail_w - w) // 2
        y = rect.top + max(0, (avail_h - h) // 2)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.minsize(min(720, w), min(640, h))

    def select_tab(self, tab):
        try:
            if tab == "dashboard":
                self.nb.select(0)
            else:
                self.nb.select(1)
        except tk.TclError:
            pass

    def _build(self):
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        style = ttk.Style()
        style.configure(
            "TNotebook.Tab", font=("Microsoft YaHei UI", 11), padding=(14, 6)
        )
        self.nb = nb

        f0 = tk.Frame(nb, bg=DASH_BG)
        self.dashboard_view = DashboardWindow(f0, self.controller)
        nb.add(f0, text=" 控制面板 ")

        f1 = self._tab_general(nb)
        f2 = self._tab_duration(nb)
        f3 = self._tab_schedule(nb)
        f4 = self._tab_strategy(nb)
        f5 = self._tab_emergency(nb)
        f6 = self._tab_gatekeeper(nb)
        f7 = self._tab_safety(nb)
        f8 = self._tab_music(nb)

        nb.add(f1, text=" 基本 ")
        nb.add(f2, text=" 时长 ")
        nb.add(f3, text=" 时段 ")
        nb.add(f4, text=" 策略 ")
        nb.add(f5, text=" 紧急 ")
        nb.add(f6, text=" AI 门卫 ")
        nb.add(f7, text=" 安全 ")
        nb.add(f8, text=" 休息音乐 ")

        btn_row = tk.Frame(self.win, bg="#f5f6f8")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        tk.Button(
            btn_row,
            text="⏸ 暂停限制",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#eef0f2",
            fg=TEXT_DARK,
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            command=self.controller.toggle_pause,
        ).pack(side="left")
        self.lbl_save_status = tk.Label(
            btn_row,
            text="设置修改后会自动保存",
            font=("Microsoft YaHei UI", 10),
            bg="#f5f6f8",
            fg=TEXT_LIGHT,
        )
        self.lbl_save_status.pack(side="left", padx=12)
        tk.Button(
            btn_row,
            text="💤 开始休息",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#1a7f37",
            fg="#ffffff",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            command=self.controller.start_break_now,
        ).pack(side="right")
        self._bind_auto_save()

    def _tab_general(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        self.var_enabled = tk.BooleanVar(value=bool(self.cfg.get("enabled")))
        r = _row(tab, "启用健康限制")
        tk.Checkbutton(
            r, text="", variable=self.var_enabled, bg="#ffffff"
        ).pack(side="left")
        r2 = _row(tab, "限制模式")
        self.var_mode = tk.StringVar(value=self.cfg.get("mode", "duration"))
        cb = ttk.Combobox(
            r2,
            textvariable=self.var_mode,
            values=["duration", "schedule", "both"],
            state="readonly",
            width=16,
        )
        cb.pack(side="left")
        cb.bind("<MouseWheel>", lambda e: "break")
        cb.bind("<Button-4>", lambda e: "break")
        cb.bind("<Button-5>", lambda e: "break")
        tk.Label(
            tab,
            text="duration=按时长限制  schedule=按时段限制  both=两者结合",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14, pady=(0, 4))
        self.var_autostart = tk.BooleanVar(
            value=bool(self.cfg.get("auto_start", False))
        )
        r3 = _row(tab, "开机自启动")
        tk.Checkbutton(
            r3, text="", variable=self.var_autostart, bg="#ffffff"
        ).pack(side="left")
        tk.Label(
            tab,
            text="开启后登录 Windows 时自动启动本程序(写入当前用户启动项)",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14, pady=(0, 4))

        so = self.cfg.get("session_overlay", {})
        self.var_overlay_enabled = tk.BooleanVar(
            value=bool(so.get("enabled", True))
        )
        r4 = _row(tab, "连续使用浮层")
        tk.Checkbutton(
            r4, text="", variable=self.var_overlay_enabled, bg="#ffffff"
        ).pack(side="left")
        tk.Label(
            tab,
            text="在屏幕角落显示连续使用时间(可拖动调整位置)",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14, pady=(0, 4))

        self.var_overlay_opacity = tk.IntVar(
            value=int(so.get("opacity", 85))
        )
        r5 = _row(tab, "浮层可见度")
        tk.Scale(
            r5,
            from_=0,
            to=100,
            resolution=1,
            orient="horizontal",
            variable=self.var_overlay_opacity,
            length=140,
            bg="#ffffff",
            highlightthickness=0,
        ).pack(side="left")
        tk.Label(
            r5,
            textvariable=self.var_overlay_opacity,
            font=("Consolas", 10),
            bg="#ffffff",
            fg="#666666",
            width=4,
        ).pack(side="left", padx=(4, 0))

        self.var_overlay_scale = tk.IntVar(value=int(so.get("scale", 100)))
        r6 = _row(tab, "浮层缩放")
        tk.Scale(
            r6,
            from_=20,
            to=200,
            resolution=5,
            orient="horizontal",
            variable=self.var_overlay_scale,
            length=140,
            bg="#ffffff",
            highlightthickness=0,
        ).pack(side="left")
        tk.Label(
            r6,
            textvariable=self.var_overlay_scale,
            font=("Consolas", 10),
            bg="#ffffff",
            fg="#666666",
            width=4,
        ).pack(side="left", padx=(4, 0))
        tk.Label(
            r6,
            text="%",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(side="left")

        self.var_overlay_pos = tk.StringVar(
            value=so.get("position", "top-right")
        )
        r8 = _row(tab, "浮层位置")
        pos_frame = tk.Frame(r8, bg="#ffffff")
        pos_frame.pack(side="left")
        from health_guard.ui_session_overlay import POSITIONS
        for key, label in POSITIONS.items():
            tk.Radiobutton(
                pos_frame,
                text=label,
                value=key,
                variable=self.var_overlay_pos,
                bg="#ffffff",
                font=("Microsoft YaHei UI", 10),
            ).pack(side="left", padx=4)
        tk.Label(
            tab,
            text="选择预设位置后自动定位;也可在浮层上按住鼠标拖动到任意位置",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14, pady=(0, 4))
        return tab

    def _tab_duration(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        dur = self.cfg.get("duration", {})
        self.var_daily = tk.IntVar(value=int(dur.get("daily_limit_minutes", 240)))
        self.var_session = tk.IntVar(
            value=int(dur.get("session_limit_minutes", 60))
        )
        self.var_break = tk.IntVar(value=int(dur.get("break_minutes", 10)))
        for label, var, lo, hi in [
            ("每日使用上限(分钟)", self.var_daily, 1, 1440),
            ("单次连续使用(分钟)", self.var_session, 1, 1440),
            ("强制休息(分钟)", self.var_break, 0, 480),
        ]:
            r = _row(tab, label)
            tk.Spinbox(
                r, from_=lo, to=hi, textvariable=var, width=8,
                font=("Consolas", 11),
            ).pack(side="left")
        return tab

    def _tab_schedule(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        self.sched = self.cfg.get("schedule", {})
        self.allowed_windows = list(self.sched.get("allowed_windows", []))
        self.blocked_windows = list(self.sched.get("blocked_windows", []))

        def sub_frame(title, var_list, windows_list):
            frame = tk.LabelFrame(
                tab, text=title, font=("Microsoft YaHei UI", 11),
                bg="#ffffff", fg="#333333", padx=8, pady=6
            )
            frame.pack(fill="x", padx=12, pady=6)
            lb = tk.Listbox(
                frame, height=4, font=("Consolas", 10), selectmode="single"
            )
            lb.pack(fill="x")
            bar = tk.Frame(frame, bg="#ffffff")
            bar.pack(fill="x", pady=(4, 0))

            def refresh():
                lb.delete(0, "end")
                for w in windows_list:
                    days = ",".join(
                        "一二三四五六日"[d] for d in w.get("days", [])
                    )
                    lb.insert(
                        "end",
                        f"[{days}] {w.get('start')} - {w.get('end')}",
                    )

            def add():
                def ok(win):
                    windows_list.append(win)
                    refresh()
                    self._on_change()

                ScheduleWindowDialog(self.win, ok)

            def remove():
                sel = lb.curselection()
                if sel:
                    del windows_list[sel[0]]
                    refresh()
                    self._on_change()

            tk.Button(
                bar, text="新增", bg="#2a6df4", fg="#ffffff", relief="flat",
                command=add,
            ).pack(side="left", padx=2)
            tk.Button(
                bar, text="删除", bg="#d4552a", fg="#ffffff", relief="flat",
                command=remove,
            ).pack(side="left", padx=2)
            refresh()
            return lb

        sub_frame("允许使用时段(留空则不限制)", self.allowed_windows, self.allowed_windows)
        sub_frame("禁止使用时段", self.blocked_windows, self.blocked_windows)
        tk.Label(
            tab,
            text="注意:若配置了允许时段,则仅在允许时段内可用;禁止时段优先。",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14)
        return tab

    def _tab_strategy(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        strat = self.cfg.get("strategy", {})
        self.var_action = tk.StringVar(
            value=strat.get("primary_action", "screensaver")
        )
        self.var_warning = tk.IntVar(
            value=int(strat.get("warning_seconds", 30))
        )
        self.var_block_apps = tk.BooleanVar(
            value=bool(strat.get("block_apps", False))
        )
        self.var_shutdown_ack = tk.BooleanVar(
            value=bool(strat.get("shutdown_ack", False))
        )
        self.var_blocked_apps = tk.StringVar(
            value=", ".join(strat.get("blocked_apps", []))
        )

        r = _row(tab, "达到上限后执行")
        actions = [
            ("none", "仅提示(不限制)"),
            ("overlay", "全屏拦截界面"),
            ("screensaver", "强制屏保"),
            ("lock", "锁定屏幕"),
            ("logoff", "注销(危险)"),
            ("shutdown", "关机(危险)"),
        ]
        for value, text in actions:
            tk.Radiobutton(
                r, text=text, value=value, variable=self.var_action,
                bg="#ffffff", font=("Microsoft YaHei UI", 10),
            ).pack(side="left")

        r2 = _row(tab, "倒计时警告(秒)")
        tk.Spinbox(
            r2, from_=0, to=300, textvariable=self.var_warning, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        r3 = _row(tab, "拦截指定应用")
        tk.Checkbutton(
            r3, text="", variable=self.var_block_apps, bg="#ffffff"
        ).pack(side="left")

        r4 = _row(tab, "被拦截应用(逗号分隔)")
        tk.Entry(
            r4, textvariable=self.var_blocked_apps, width=34,
            font=("Consolas", 10),
        ).pack(side="left")

        r5 = _row(tab, "已确认注销/关机风险")
        tk.Checkbutton(
            r5, text="我已了解并接受风险", variable=self.var_shutdown_ack,
            bg="#ffffff",
        ).pack(side="left")
        tk.Label(
            tab,
            text="⚠ 注销/关机必须勾选确认才会执行,防止误操作锁死电脑",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#c0392b",
        ).pack(anchor="w", padx=14)
        return tab

    def _tab_emergency(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        em = self.cfg.get("emergency", {})
        has_pw = bool(em.get("password_hash"))
        self.var_new_pw = tk.StringVar()
        self.var_new_pw2 = tk.StringVar()
        self.var_grant_min = tk.IntVar(
            value=int(em.get("password_grant_minutes", 15))
        )
        self.var_cooldown = tk.IntVar(
            value=int(em.get("grant_cooldown_minutes", 15))
        )
        self.var_hotkey_unlock = tk.StringVar(
            value="+".join(em.get("hotkey_unlock", ["ctrl", "alt", "shift", "u"]))
        )
        self.var_hotkey_panic = tk.StringVar(
            value="+".join(em.get("hotkey_panic", ["ctrl", "alt", "shift", "x"]))
        )

        r = _row(tab, "紧急密码状态")
        tk.Label(
            r,
            text=("✅ 已设置" if has_pw else "❌ 未设置(无法紧急解锁)"),
            font=("Microsoft YaHei UI", 11),
            bg="#ffffff",
            fg=("#1a7f37" if has_pw else "#c0392b"),
        ).pack(side="left")
        if has_pw:
            tk.Button(
                r, text="重置密码", bg="#7d3cbd", fg="#ffffff", relief="flat",
                command=self._reset_password,
            ).pack(side="left", padx=10)

        r2 = _row(tab, "密码解锁时长(分钟)")
        tk.Spinbox(
            r2, from_=1, to=120, textvariable=self.var_grant_min, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        r3 = _row(tab, "解锁冷却(分钟)")
        tk.Spinbox(
            r3, from_=0, to=480, textvariable=self.var_cooldown, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        r4 = _row(tab, "解锁快捷键")
        tk.Entry(
            r4, textvariable=self.var_hotkey_unlock, width=20,
            font=("Consolas", 10),
        ).pack(side="left")

        r5 = _row(tab, "紧急中止快捷键")
        tk.Entry(
            r5, textvariable=self.var_hotkey_panic, width=20,
            font=("Consolas", 10),
        ).pack(side="left")
        tk.Label(
            tab,
            text="快捷键格式: ctrl+alt+shift+u (用加号连接)",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14)
        return tab

    def _reset_password(self):
        self._teardown()
        self.win.destroy()
        self.controller.open_password_reset()

    def _tab_gatekeeper(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        gk = self.cfg.get("gatekeeper", {})
        self.var_gk_enabled = tk.BooleanVar(value=bool(gk.get("enabled")))
        self.var_base_url = tk.StringVar(
            value=gk.get("base_url", "https://api.openai.com/v1")
        )
        self.var_api_key = tk.StringVar(value=gk.get("api_key", ""))
        self.var_model = tk.StringVar(value=gk.get("model", "gpt-4o-mini"))
        self.var_timeout = tk.IntVar(value=int(gk.get("timeout_seconds", 20)))
        self.var_gk_default = tk.IntVar(
            value=int(gk.get("default_grant_minutes", 15))
        )
        self.var_gk_max = tk.IntVar(value=int(gk.get("max_grant_minutes", 60)))

        r = _row(tab, "启用 AI 门卫")
        tk.Checkbutton(
            r, text="", variable=self.var_gk_enabled, bg="#ffffff"
        ).pack(side="left")

        r2 = _row(tab, "API 地址(base_url)")
        tk.Entry(
            r2, textvariable=self.var_base_url, width=40,
            font=("Consolas", 10),
        ).pack(side="left")

        r3 = _row(tab, "API Key")
        tk.Entry(
            r3, textvariable=self.var_api_key, show="●", width=40,
            font=("Consolas", 10),
        ).pack(side="left")

        r4 = _row(tab, "模型名称")
        tk.Entry(
            r4, textvariable=self.var_model, width=24,
            font=("Consolas", 10),
        ).pack(side="left")

        r5 = _row(tab, "超时(秒)")
        tk.Spinbox(
            r5, from_=5, to=120, textvariable=self.var_timeout, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        r6 = _row(tab, "默认放行(分钟)")
        tk.Spinbox(
            r6, from_=1, to=120, textvariable=self.var_gk_default, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        r7 = _row(tab, "最大放行(分钟)")
        tk.Spinbox(
            r7, from_=1, to=240, textvariable=self.var_gk_max, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        tk.Button(
            tab,
            text="测试连接",
            font=("Microsoft YaHei UI", 11),
            bg="#2a6df4",
            fg="#ffffff",
            relief="flat",
            padx=14,
            pady=6,
            command=self._test_gatekeeper,
        ).pack(anchor="w", padx=14, pady=(8, 0))
        self.lbl_gk_test = tk.Label(
            tab, text="", font=("Microsoft YaHei UI", 10), bg="#ffffff",
        )
        self.lbl_gk_test.pack(anchor="w", padx=14)
        tk.Label(
            tab,
            text="支持任何 OpenAI 兼容接口(OpenAI/DeepSeek/Moonshot/千问/Ollama 等)",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14)
        return tab

    def _test_gatekeeper(self):
        cfg = self._collect_cfg()
        self.lbl_gk_test.config(text="⏳ 正在测试连接…", fg="#cc7a00")
        self.win.update_idletasks()

        def worker():
            try:
                from health_guard import gatekeeper

                result = gatekeeper.evaluate_request(
                    cfg, self.controller.get_state(), "连接测试"
                )
                msg = (
                    f"✅ 连接成功,AI 响应:放行={result['allow']},"
                    f"时长={result['minutes']}分钟"
                )
                self.win.after(
                    0, lambda: self.lbl_gk_test.config(text=msg, fg="#1a7f37")
                )
            except Exception as exc:
                self.win.after(
                    0,
                    lambda e=exc: self.lbl_gk_test.config(
                        text=f"❌ {e}", fg="#c0392b"
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _tab_safety(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        safety = self.cfg.get("safety", {})
        self.var_fail_open = tk.BooleanVar(
            value=bool(safety.get("fail_open", True))
        )
        self.var_idle = tk.IntVar(
            value=int(safety.get("idle_threshold_seconds", 120))
        )
        self.var_ack = tk.BooleanVar(
            value=bool(safety.get("shutdown_requires_ack", True))
        )

        r = _row(tab, "安全兜底(fail-open)")
        tk.Checkbutton(
            r,
            text="配置异常时自动关闭限制,绝不锁死电脑",
            variable=self.var_fail_open,
            bg="#ffffff",
        ).pack(side="left")

        r2 = _row(tab, "闲置判定(秒)")
        tk.Spinbox(
            r2, from_=10, to=3600, textvariable=self.var_idle, width=8,
            font=("Consolas", 11),
        ).pack(side="left")

        r3 = _row(tab, "关机/注销需确认")
        tk.Checkbutton(
            r3, text="", variable=self.var_ack, bg="#ffffff"
        ).pack(side="left")
        return tab

    def _tab_music(self, nb):
        tab = tk.Frame(nb, bg="#ffffff")
        music = self.cfg.get("music", {})
        from health_guard.config import normalize_music_mode

        self.var_music_mode = tk.StringVar(
            value=normalize_music_mode(music.get("mode", "auto"))
        )
        self.var_player_path = tk.StringVar(
            value=music.get("player_path", r"F:\lx-music\lx-music-desktop\lx-music-desktop.exe")
        )
        self.var_api_base = tk.StringVar(
            value=music.get("api_base", "http://127.0.0.1:23330")
        )
        self.var_stop_on_end = tk.BooleanVar(
            value=bool(music.get("stop_on_break_end", True))
        )

        r = _row(tab, "休息音乐模式")
        modes = [
            ("disabled", "🔇 不播放"),
            ("manual", "🖐 手动播放"),
            ("auto", "▶ 自动播放"),
        ]
        for value, text in modes:
            tk.Radiobutton(
                r, text=text, value=value, variable=self.var_music_mode,
                bg="#ffffff", font=("Microsoft YaHei UI", 10),
            ).pack(side="left", padx=4)

        tk.Label(
            tab,
            text="不播放:不启动洛雪音乐,屏保不显示播放器 | "
            "手动播放:启动洛雪音乐,由你在屏保中点击播放 | "
            "自动播放:启动并自动播放",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 4))

        tk.Label(
            tab,
            text="洛雪音乐需先在 设置 → 实验室/Open API 中开启服务(默认端口 23330)",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14, pady=(0, 4))

        r2 = _row(tab, "播放器程序路径")
        tk.Entry(
            r2, textvariable=self.var_player_path, width=46,
            font=("Consolas", 10),
        ).pack(side="left")

        def browse_player():
            from tkinter import filedialog

            path = filedialog.askopenfilename(
                title="选择音乐播放器程序",
                filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
            )
            if path:
                self.var_player_path.set(path)

        tk.Button(
            r2, text="浏览…", bg="#2a6df4", fg="#ffffff", relief="flat",
            command=browse_player,
        ).pack(side="left", padx=6)

        r3 = _row(tab, "Open API 地址")
        tk.Entry(
            r3, textvariable=self.var_api_base, width=30,
            font=("Consolas", 10),
        ).pack(side="left")
        tk.Label(
            r3,
            text="(如 http://127.0.0.1:23330)",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(side="left", padx=6)

        r4 = _row(tab, "休息结束时自动停止")
        tk.Checkbutton(
            r4, text="", variable=self.var_stop_on_end, bg="#ffffff"
        ).pack(side="left")

        tk.Label(
            tab,
            text="手动/自动播放时,休息屏保会显示当前歌曲名和歌词,"
            "并提供「播放/停止 / 下一首 / 上一首」按钮",
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#888888",
        ).pack(anchor="w", padx=14)

        # 测试连接
        self.lbl_music_test = tk.Label(
            tab, text="", font=("Microsoft YaHei UI", 10), bg="#ffffff",
        )
        self.lbl_music_test.pack(anchor="w", padx=14, pady=(4, 0))
        tk.Button(
            tab,
            text="测试洛雪音乐连接",
            font=("Microsoft YaHei UI", 11),
            bg="#2a6df4",
            fg="#ffffff",
            relief="flat",
            padx=14,
            pady=4,
            command=self._test_lx_music,
        ).pack(anchor="w", padx=14, pady=(6, 0))
        return tab

    def _test_lx_music(self):
        import threading
        from health_guard.music import LxMusicClient, is_port_open

        api_base = self.var_api_base.get().strip()
        self.lbl_music_test.config(text="⏳ 正在测试连接…", fg="#cc7a00")
        self.win.update_idletasks()

        def worker():
            try:
                if not is_port_open(api_base):
                    self.win.after(
                        0,
                        lambda: self.lbl_music_test.config(
                            text="❌ 端口未监听:洛雪音乐未运行或未开启 Open API",
                            fg="#c0392b",
                        ),
                    )
                    return
                client = LxMusicClient(api_base=api_base)
                if not client.is_available():
                    self.win.after(
                        0,
                        lambda: self.lbl_music_test.config(
                            text="❌ 端口已监听但 Open API 无响应", fg="#c0392b"
                        ),
                    )
                    return
                st = client.get_status()
                msg = (
                    f"✅ 连接成功 | 状态={'播放中' if st.playing else '已暂停'} "
                    f"| 歌曲={st.singer} - {st.name}"
                )
                self.win.after(
                    0, lambda: self.lbl_music_test.config(text=msg, fg="#1a7f37")
                )
            except Exception as exc:
                self.win.after(
                    0,
                    lambda e=exc: self.lbl_music_test.config(
                        text=f"❌ {e}", fg="#c0392b"
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _collect_cfg(self):
        cfg = {
            "enabled": self.var_enabled.get(),
            "auto_start": self.var_autostart.get(),
            "mode": self.var_mode.get(),
            "duration": {
                "daily_limit_minutes": max(1, self.var_daily.get()),
                "session_limit_minutes": max(1, self.var_session.get()),
                "break_minutes": max(0, self.var_break.get()),
            },
            "schedule": {
                "allowed_windows": self.allowed_windows,
                "blocked_windows": self.blocked_windows,
            },
            "strategy": {
                "primary_action": self.var_action.get(),
                "warning_seconds": max(
                    0, min(300, self.var_warning.get())
                ),
                "block_apps": self.var_block_apps.get(),
                "blocked_apps": [
                    a.strip()
                    for a in self.var_blocked_apps.get().split(",")
                    if a.strip()
                ],
                "shutdown_ack": self.var_shutdown_ack.get(),
            },
            "emergency": {
                "password_grant_minutes": max(1, self.var_grant_min.get()),
                "grant_cooldown_minutes": max(0, self.var_cooldown.get()),
                "hotkey_unlock": [
                    k.strip().lower()
                    for k in self.var_hotkey_unlock.get().split("+")
                    if k.strip()
                ],
                "hotkey_panic": [
                    k.strip().lower()
                    for k in self.var_hotkey_panic.get().split("+")
                    if k.strip()
                ],
            },
            "gatekeeper": {
                "enabled": self.var_gk_enabled.get(),
                "base_url": self.var_base_url.get().strip().rstrip("/"),
                "api_key": self.var_api_key.get().strip(),
                "model": self.var_model.get().strip(),
                "timeout_seconds": max(5, self.var_timeout.get()),
                "default_grant_minutes": max(1, self.var_gk_default.get()),
                "max_grant_minutes": max(1, self.var_gk_max.get()),
            },
            "safety": {
                "fail_open": self.var_fail_open.get(),
                "idle_threshold_seconds": max(10, self.var_idle.get()),
                "shutdown_requires_ack": self.var_ack.get(),
            },
            "music": {
                "mode": self.var_music_mode.get(),
                "player_path": self.var_player_path.get().strip(),
                "api_base": self.var_api_base.get().strip().rstrip("/"),
                "stop_on_break_end": self.var_stop_on_end.get(),
            },
            "session_overlay": {
                "enabled": self.var_overlay_enabled.get(),
                "opacity": max(0, min(100, self.var_overlay_opacity.get())),
                "scale": max(20, min(200, self.var_overlay_scale.get())),
                "position": self.var_overlay_pos.get(),
                "pos_x": self.cfg.get("session_overlay", {}).get("pos_x"),
                "pos_y": self.cfg.get("session_overlay", {}).get("pos_y"),
            },
        }
        return cfg

    def _teardown(self):
        if self._save_job is not None:
            try:
                self.win.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None
        if self.dashboard_view is not None:
            try:
                self.dashboard_view.stop_refresh()
            except Exception:
                pass

    def _bind_auto_save(self):
        vars_to_trace = [
            self.var_enabled,
            self.var_autostart,
            self.var_mode,
            self.var_overlay_enabled,
            self.var_overlay_opacity,
            self.var_overlay_scale,
            self.var_overlay_pos,
            self.var_daily,
            self.var_session,
            self.var_break,
            self.var_action,
            self.var_warning,
            self.var_block_apps,
            self.var_blocked_apps,
            self.var_shutdown_ack,
            self.var_grant_min,
            self.var_cooldown,
            self.var_hotkey_unlock,
            self.var_hotkey_panic,
            self.var_gk_enabled,
            self.var_base_url,
            self.var_api_key,
            self.var_model,
            self.var_timeout,
            self.var_gk_default,
            self.var_gk_max,
            self.var_fail_open,
            self.var_idle,
            self.var_ack,
            self.var_music_mode,
            self.var_player_path,
            self.var_api_base,
            self.var_stop_on_end,
        ]
        for var in vars_to_trace:
            try:
                var.trace_add("write", lambda *_: self._on_change())
            except Exception:
                pass

    def _on_change(self):
        if self._save_job is not None:
            try:
                self.win.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.win.after(600, self._auto_save)

    def _auto_save(self):
        self._save_job = None
        try:
            cfg = self._collect_cfg()
        except Exception:
            # 输入框可能处于中间态(如为空),跳过本次保存
            return
        try:
            saved = self.controller.save_settings(cfg)
        except Exception:
            log.exception("auto save failed")
            self._set_save_status("⚠ 保存失败", RED)
            return
        if saved:
            self._set_save_status("✅ 设置已自动保存", GREEN)
        else:
            if cfg.get("enabled"):
                self.var_enabled.set(False)
                self._set_save_status(
                    "⚠ 需先在「紧急」页设置密码才能启用限制", ORANGE
                )
            else:
                self._set_save_status("⚠ 部分设置未保存", ORANGE)

    def _set_save_status(self, text, color):
        try:
            self.lbl_save_status.config(text=text, fg=color)
        except tk.TclError:
            pass

    def _on_close(self):
        self._teardown()
        self.win.destroy()


class PasswordResetDialog:
    def __init__(self, root, controller):
        self.controller = controller
        self.win = tk.Toplevel(root)
        self.win.title("重置紧急密码")
        self.win.geometry("420x260")
        self.win.configure(bg="#f5f6f8")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()

        tk.Label(
            self.win,
            text="需要验证旧密码或恢复码后才能重置",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#666666",
        ).pack(pady=(14, 6))

        tk.Label(
            self.win, text="旧密码或恢复码", font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack()
        self.entry_old = tk.Entry(
            self.win, show="●", font=("Consolas", 12), width=30
        )
        self.entry_old.pack(pady=4)

        tk.Label(
            self.win, text="新密码", font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack()
        self.entry_new = tk.Entry(
            self.win, show="●", font=("Consolas", 12), width=30
        )
        self.entry_new.pack(pady=4)

        self.lbl_err = tk.Label(
            self.win, text="", font=("Microsoft YaHei UI", 10),
            bg="#f5f6f8", fg="#c0392b",
        )
        self.lbl_err.pack()
        tk.Button(
            self.win,
            text="重置",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#7d3cbd",
            fg="#ffffff",
            relief="flat",
            padx=20,
            pady=6,
            command=self._submit,
        ).pack(pady=10)

    def _submit(self):
        old = self.entry_old.get()
        new = self.entry_new.get()
        if len(new) < 4:
            self.lbl_err.config(text="新密码至少 4 位")
            return
        err = self.controller.reset_password(old, new)
        if err:
            self.lbl_err.config(text=err)
        else:
            self.lbl_err.config(text="✅ 密码已重置", fg="#1a7f37")
            self.win.after(600, self.win.destroy)
