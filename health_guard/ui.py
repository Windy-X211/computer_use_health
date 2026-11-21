import datetime
import logging
import queue
import threading
import tkinter as tk

from health_guard import winapi
from health_guard.config import normalize_music_mode
from health_guard.ui_session_overlay import SessionOverlayWindow
from health_guard.ui_settings import PasswordResetDialog, SettingsWindow
from health_guard.ui_setup import SetupWizard

log = logging.getLogger("health_guard.ui")


class UIApp:
    def __init__(self, controller):
        self.controller = controller
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry("1x1+0+0")
        self.root.attributes("-alpha", 0.0)
        self.root.title("电脑使用健康管家")
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.overlay = None
        self.toast = None
        self.break_screensaver = None
        self.emergency = None
        self.main = None
        self.setup = None
        self.prompt = None
        self.session_overlay = None
        self._cmdq = queue.Queue()
        self._pending_screensaver_after = None  # 追踪延迟的屏保创建回调
        self._init_session_overlay()
        self._poll()

    def _init_session_overlay(self):
        try:
            cfg = self.controller.get_cfg()
            self.session_overlay = SessionOverlayWindow(
                self.root, self.controller, cfg
            )
        except Exception as exc:
            log.exception("failed to create session overlay: %s", exc)

    def _update_session_overlay(self, cfg):
        def _do():
            if self.session_overlay is None:
                self._init_session_overlay()
                return
            try:
                self.session_overlay.update_config(cfg)
            except Exception as exc:
                log.exception("session overlay update failed: %s", exc)
        self._call(_do)

    def _poll(self):
        try:
            while True:
                fn = self._cmdq.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    log.debug("UI command target destroyed")
                except Exception as exc:
                    log.exception("UI command failed: %s", exc)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _call(self, fn):
        self._cmdq.put(fn)

    def run(self):
        self.root.mainloop()

    def destroy(self):
        self._call(lambda: self.root.quit())

    def show_overlay(self, reason, warning_seconds, grant_remaining=0):
        self._call(
            lambda: self._show_overlay(reason, warning_seconds, grant_remaining)
        )

    def _show_overlay(self, reason, warning_seconds, grant_remaining):
        if self.overlay is None:
            self.overlay = OverlayWindow(
                self.root, self.controller.open_emergency
            )
        self.overlay.set_content(reason, warning_seconds, grant_remaining)
        self.overlay.show()

    def update_overlay(self, reason, remaining, grant_remaining=0):
        self._call(
            lambda: self._update_overlay(reason, remaining, grant_remaining)
        )

    def _update_overlay(self, reason, remaining, grant_remaining):
        if self.overlay is None:
            return
        self.overlay.set_content(reason, remaining, grant_remaining)
        if self.emergency is not None:
            try:
                if self.emergency.win.winfo_exists():
                    return
            except tk.TclError:
                self.emergency = None
        self.overlay.win.lift()

    def hide_overlay(self):
        self._call(self._hide_overlay)

    def _hide_overlay(self):
        if self.overlay is not None:
            self.overlay.hide()
            self.overlay.destroy()
            self.overlay = None

    # ---------- 角落提醒 Toast ----------

    def show_toast(self, reason, warning_seconds, grant_remaining=0):
        self._call(
            lambda: self._show_toast(reason, warning_seconds, grant_remaining)
        )

    def _show_toast(self, reason, warning_seconds, grant_remaining):
        if self.toast is None:
            self.toast = ToastCornerWindow(
                self.root, self.controller.open_emergency
            )
        self.toast.set_content(reason, warning_seconds, grant_remaining)
        self.toast.show()

    def update_toast(self, reason, remaining, grant_remaining=0):
        self._call(
            lambda: self._update_toast(reason, remaining, grant_remaining)
        )

    def _update_toast(self, reason, remaining, grant_remaining):
        if self.toast is None:
            return
        self.toast.set_content(reason, remaining, grant_remaining)

    def hide_toast(self):
        self._call(self._hide_toast)

    def _hide_toast(self):
        if self.toast is not None:
            self.toast.hide()
            self.toast.destroy()
            self.toast = None

    # ---------- 休息屏保 ----------

    def show_break_screensaver(self, break_minutes, next_allowed_dt=None):
        self._call(
            lambda: self._show_break_screensaver(break_minutes, next_allowed_dt)
        )

    def _show_break_screensaver(self, break_minutes, next_allowed_dt=None):
        # 如果有之前的延迟回调还在等待,先取消它避免重复
        self._cancel_pending_screensaver()
        # 如果紧急解锁面板开着,等它关闭后再弹出
        if self.emergency is not None:
            try:
                if self.emergency.win.winfo_exists():
                    self._pending_screensaver_after = self.root.after(
                        500,
                        lambda: self._show_break_screensaver(
                            break_minutes, next_allowed_dt
                        ),
                    )
                    return
            except tk.TclError:
                self.emergency = None
        self._pending_screensaver_after = None
        # 模式不一致(倒计时 ↔ 下次可用时间)时重建窗口
        if (
            self.break_screensaver is None
            or bool(self.break_screensaver.next_allowed_dt)
            != bool(next_allowed_dt)
        ):
            self.break_screensaver = BreakScreensaverWindow(
                self.root, self.controller, break_minutes, next_allowed_dt
            )
        self.break_screensaver.show()

    def _cancel_pending_screensaver(self):
        """取消任何等待中的屏保创建回调。"""
        if self._pending_screensaver_after is not None:
            try:
                self.root.after_cancel(self._pending_screensaver_after)
            except tk.TclError:
                pass
            self._pending_screensaver_after = None

    def hide_break_screensaver(self):
        self._call(self._hide_break_screensaver)

    def _hide_break_screensaver(self):
        # 先取消任何等待中的屏保创建回调,防止它之后又创建新窗口
        self._cancel_pending_screensaver()
        if self.break_screensaver is not None:
            self.break_screensaver.hide()
            self.break_screensaver.destroy()
            self.break_screensaver = None

    def show_emergency(self, context=""):
        self._call(lambda: self._show_emergency(context))

    def _show_emergency(self, context):
        if self.emergency is not None:
            try:
                if self.emergency.win.winfo_exists():
                    self.emergency.set_context(context)
                    self._raise_emergency()
                    return
            except tk.TclError:
                self.emergency = None
        # 只隐藏 toast(避免被全屏紧急面板遮挡),但保留休息屏保继续运行
        self._hide_toast_now()
        self.emergency = EmergencyDialog(
            self.root,
            self.controller,
            self.controller.get_cfg(),
            on_close=self._emergency_closed,
        )
        if context:
            self.emergency.set_context(context)
        self._raise_emergency()

    def _hide_toast_now(self):
        """立即隐藏 toast(供 show_emergency 使用)。"""
        if self.toast is not None:
            try:
                self.toast.hide()
            except tk.TclError:
                pass

    def _raise_emergency(self):
        if self.emergency is None:
            return
        try:
            w = self.emergency.win
            w.deiconify()
            w.lift()
            w.attributes("-topmost", True)
            w.focus_force()
            w.after(150, self._reassert_emergency_top)
        except tk.TclError:
            pass

    def _reassert_emergency_top(self):
        if self.emergency is None:
            return
        try:
            if self.emergency.win.winfo_exists():
                self.emergency.win.attributes("-topmost", True)
                self.emergency.win.lift()
        except tk.TclError:
            pass

    def _emergency_closed(self):
        self.emergency = None
        enforcer = self.controller.enforcer
        if enforcer is not None and enforcer.is_blocked:
            self._show_overlay_again()

    def _show_overlay_again(self):
        if self.overlay is not None:
            try:
                if self.overlay.win.winfo_exists():
                    self.overlay.show()
                    return
            except tk.TclError:
                self.overlay = None
        enforcer = self.controller.enforcer
        if enforcer is not None:
            enforcer.refresh_overlay()

    def open_dashboard(self):
        self._call(lambda: self._open_main("dashboard"))

    def open_settings(self):
        self._call(lambda: self._open_main("settings"))

    def _open_main(self, tab):
        if self.main is not None:
            try:
                if self.main.win.winfo_exists():
                    self.main.win.deiconify()
                    self.main.win.lift()
                    self.main.select_tab(tab)
                    return
            except tk.TclError:
                self.main = None
        self.main = SettingsWindow(
            self.root, self.controller, self.controller.get_cfg()
        )
        self.main.select_tab(tab)

    def open_setup(self, cancellable=False):
        self._call(lambda: self._open_setup(cancellable))

    def _open_setup(self, cancellable=False):
        if self.setup is not None:
            try:
                if self.setup.win.winfo_exists():
                    self.setup.win.deiconify()
                    self.setup.win.lift()
                    return
            except tk.TclError:
                self.setup = None
        self.setup = SetupWizard(
            self.root,
            self.controller,
            cancellable=cancellable,
            on_close=self._setup_closed,
        )

    def _setup_closed(self):
        self.setup = None

    def open_password_reset(self):
        self._call(self._open_password_reset)

    def _open_password_reset(self):
        PasswordResetDialog(self.root, self.controller)

    def prompt_password(self, title, message, callback):
        self._call(
            lambda: PasswordPrompt(self.root, self.controller, title, message, callback)
        )

    def show_tray_message(self, title, message):
        try:
            self.controller.notify_tray(title, message)
        except Exception:
            pass


class OverlayWindow:
    def __init__(self, root, on_unlock):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#101418")
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)
        rect = winapi.virtual_screen_rect()
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        self.win.geometry(f"{w}x{h}+{rect.left}+{rect.top}")
        self.win.update_idletasks()
        self.win.lift()

        self.label_icon = tk.Label(
            self.win,
            text="💻",
            font=("Segoe UI Emoji", 64),
            bg="#101418",
            fg="#f0c040",
        )
        self.label_icon.pack(pady=(60, 0))

        self.label_title = tk.Label(
            self.win,
            text="使用时间已到,请休息一下",
            font=("Microsoft YaHei UI", 26, "bold"),
            bg="#101418",
            fg="#ffffff",
        )
        self.label_title.pack(pady=10)

        self.label_reason = tk.Label(
            self.win,
            text="",
            font=("Microsoft YaHei UI", 14),
            bg="#101418",
            fg="#cccccc",
            wraplength=w - 200,
        )
        self.label_reason.pack(pady=10)

        self.label_countdown = tk.Label(
            self.win,
            text="",
            font=("Microsoft YaHei UI", 18),
            bg="#101418",
            fg="#f0c040",
        )
        self.label_countdown.pack(pady=10)

        self.btn = tk.Button(
            self.win,
            text="紧急使用 🔓",
            font=("Microsoft YaHei UI", 16, "bold"),
            bg="#2a6df4",
            fg="#ffffff",
            activebackground="#1e55c4",
            activeforeground="#ffffff",
            relief="flat",
            padx=30,
            pady=10,
            cursor="hand2",
            command=on_unlock,
        )
        self.btn.pack(pady=24)

        self.label_hint = tk.Label(
            self.win,
            text="紧急快捷键可随时调出解锁面板",
            font=("Microsoft YaHei UI", 11),
            bg="#101418",
            fg="#888888",
        )
        self.label_hint.pack(pady=6)

    def set_content(self, reason, remaining, grant_remaining):
        self.label_reason.config(text=reason)
        if grant_remaining > 0:
            self.label_countdown.config(
                text=f"紧急放行中,剩余 {grant_remaining} 分钟"
            )
            self.label_icon.config(text="⏳")
            self.btn.config(state="disabled")
        else:
            if remaining > 0:
                self.label_countdown.config(
                    text=f"{remaining} 秒后将执行限制措施"
                )
            else:
                self.label_countdown.config(text="正在执行限制措施…")
            self.label_icon.config(text="💻")
            self.btn.config(state="normal")

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)

    def hide(self):
        self.win.withdraw()

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class EmergencyDialog:
    def __init__(self, root, controller, cfg, on_close=None):
        self.controller = controller
        self.cfg = cfg
        self.on_close = on_close
        self.win = tk.Toplevel(root)
        self.win.title("紧急使用")
        self.win.geometry("480x560")
        self.win.configure(bg="#f5f6f8")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()

    def _on_close(self):
        self.win.destroy()
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:
                log.exception("emergency on_close handler failed")

    def _build(self):
        root = self.win
        tk.Label(
            root,
            text="🔓 紧急使用解锁",
            font=("Microsoft YaHei UI", 18, "bold"),
            bg="#f5f6f8",
            fg="#1c1c1c",
        ).pack(pady=(16, 4))
        self.lbl_context = tk.Label(
            root,
            text="",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#666666",
            wraplength=440,
            justify="center",
        )
        self.lbl_context.pack(pady=(0, 8))
        self.lbl_result = tk.Label(
            root,
            text="",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#1a7f37",
            wraplength=440,
            justify="center",
        )
        self.lbl_result.pack(pady=4)

        notebook_frames = {"password": None, "ai": None, "recovery": None}
        tk.Frame(root, bg="#f5f6f8").pack(fill="x", padx=20)
        btn_row = tk.Frame(root, bg="#f5f6f8")
        btn_row.pack(fill="x", padx=20, pady=6)
        self._tab_buttons = {}

        def make_tab(key, text):
            btn = tk.Button(
                btn_row,
                text=text,
                font=("Microsoft YaHei UI", 11),
                bg="#ffffff",
                fg="#1c1c1c",
                relief="flat",
                padx=12,
                pady=6,
            )
            btn.pack(side="left", padx=4)
            self._tab_buttons[key] = btn
            return btn

        password_tab = tk.Frame(root, bg="#ffffff", padx=20, pady=16)
        ai_tab = tk.Frame(root, bg="#ffffff", padx=20, pady=16)
        recovery_tab = tk.Frame(root, bg="#ffffff", padx=20, pady=16)
        notebook_frames["password"] = password_tab
        notebook_frames["ai"] = ai_tab
        notebook_frames["recovery"] = recovery_tab

        make_tab("password", "密码解锁").config(
            command=lambda: self._switch_tab("password", notebook_frames)
        )
        make_tab("ai", "AI 门卫").config(
            command=lambda: self._switch_tab("ai", notebook_frames)
        )
        make_tab("recovery", "恢复码").config(
            command=lambda: self._switch_tab("recovery", notebook_frames)
        )

        self._build_password_tab(password_tab)
        self._build_ai_tab(ai_tab)
        self._build_recovery_tab(recovery_tab)

        for f in notebook_frames.values():
            f.pack_forget()
        self._switch_tab("password", notebook_frames)

        tk.Label(
            root,
            text="解锁后将在设定时长内暂时放行,请勿滥用",
            font=("Microsoft YaHei UI", 9),
            bg="#f5f6f8",
            fg="#999999",
        ).pack(pady=(8, 4))
        tk.Button(
            root,
            text="关闭窗口",
            font=("Microsoft YaHei UI", 11),
            bg="#e5e7eb",
            fg="#333333",
            relief="flat",
            padx=20,
            pady=6,
            command=self._on_close,
        ).pack(pady=(0, 12))

    def _build_password_tab(self, frame):
        tk.Label(
            frame,
            text="输入已设置的紧急密码",
            font=("Microsoft YaHei UI", 11),
            bg="#ffffff",
            fg="#333333",
        ).pack(anchor="w")
        self.entry_pw = tk.Entry(frame, show="●", font=("Consolas", 13))
        self.entry_pw.pack(fill="x", pady=(6, 4))
        self.entry_pw.bind("<Return>", lambda e: self._submit_password())
        self.lbl_pw_hint = tk.Label(
            frame,
            text="",
            font=("Microsoft YaHei UI", 10),
            bg="#ffffff",
            fg="#999999",
        )
        self.lbl_pw_hint.pack(anchor="w")
        tk.Button(
            frame,
            text="确认解锁",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#2a6df4",
            fg="#ffffff",
            relief="flat",
            padx=16,
            pady=8,
            command=self._submit_password,
        ).pack(pady=(10, 0))

    def _build_ai_tab(self, frame):
        enabled = self.cfg.get("gatekeeper", {}).get("enabled", False)
        if not enabled:
            tk.Label(
                frame,
                text="AI 门卫未启用,可在设置中开启并配置 API",
                font=("Microsoft YaHei UI", 11),
                bg="#ffffff",
                fg="#cc7a00",
            ).pack(anchor="w")
        tk.Label(
            frame,
            text="描述你此时需要使用电脑的原因",
            font=("Microsoft YaHei UI", 11),
            bg="#ffffff",
            fg="#333333",
        ).pack(anchor="w", pady=(6, 2))
        self.txt_reason = tk.Text(
            frame, height=4, font=("Microsoft YaHei UI", 11), wrap="word"
        )
        self.txt_reason.pack(fill="x")
        self.txt_reason.bind("<Control-Return>", lambda e: self._submit_ai())
        self.lbl_ai_hint = tk.Label(
            frame,
            text="",
            font=("Microsoft YaHei UI", 10),
            bg="#ffffff",
            fg="#999999",
        )
        self.lbl_ai_hint.pack(anchor="w")
        self.btn_ai = tk.Button(
            frame,
            text="提交给 AI 门卫",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#7d3cbd",
            fg="#ffffff",
            relief="flat",
            padx=16,
            pady=8,
            command=self._submit_ai,
        )
        self.btn_ai.pack(pady=(10, 0))

    def _build_recovery_tab(self, frame):
        tk.Label(
            frame,
            text="输入设置时保存的紧急恢复码",
            font=("Microsoft YaHei UI", 11),
            bg="#ffffff",
            fg="#333333",
        ).pack(anchor="w")
        self.entry_rec = tk.Entry(frame, font=("Consolas", 12))
        self.entry_rec.pack(fill="x", pady=(6, 4))
        self.entry_rec.bind("<Return>", lambda e: self._submit_recovery())
        self.lbl_rec_hint = tk.Label(
            frame,
            text="忘记恢复码将无法解锁,请妥善保管",
            font=("Microsoft YaHei UI", 10),
            bg="#ffffff",
            fg="#999999",
        )
        self.lbl_rec_hint.pack(anchor="w")
        tk.Button(
            frame,
            text="使用恢复码解锁",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#d4552a",
            fg="#ffffff",
            relief="flat",
            padx=16,
            pady=8,
            command=self._submit_recovery,
        ).pack(pady=(10, 0))

    def _switch_tab(self, key, frames):
        for k, f in frames.items():
            f.pack_forget()
            self._tab_buttons[k].config(bg="#ffffff", fg="#1c1c1c")
        frames[key].pack(fill="both", expand=True, padx=20)
        self._tab_buttons[key].config(bg="#e6efff", fg="#1e55c4")

    def _set_result(self, text, ok=True, busy=False):
        color = "#1a7f37" if ok else ("#cc7a00" if busy else "#c0392b")
        self.lbl_result.config(text=text, fg=color)

    def set_context(self, text):
        self.lbl_context.config(text=text)

    def _submit_password(self):
        pw = self.entry_pw.get()
        if not pw:
            self._set_result("请输入密码", ok=False)
            return
        ok = self.controller.try_password(pw)
        if ok:
            self._set_result("✅ 密码验证成功,已放行")
        else:
            self._set_result("❌ 密码错误", ok=False)

    def _submit_recovery(self):
        code = self.entry_rec.get().strip()
        if not code:
            self._set_result("请输入恢复码", ok=False)
            return
        ok = self.controller.try_recovery_code(code)
        if ok:
            self._set_result("✅ 恢复码验证成功,已放行")
        else:
            self._set_result("❌ 恢复码错误", ok=False)

    def _submit_ai(self):
        reason = self.txt_reason.get("1.0", "end").strip()
        if not reason:
            self._set_result("请先描述使用原因", ok=False)
            return
        self._set_result("⏳ 正在询问 AI 门卫,请稍候…", busy=True)
        self.btn_ai.config(state="disabled")
        self.txt_reason.config(state="disabled")

        def worker():
            result = self.controller.request_gatekeeper(reason)
            self.win.after(
                0, lambda: self._ai_done(result, self.cfg, self.controller)
            )

        threading.Thread(target=worker, daemon=True).start()

    def _ai_done(self, result, cfg, controller):
        self.btn_ai.config(state="normal")
        self.txt_reason.config(state="normal")
        if result.get("ok") is False:
            self._set_result(f"❌ {result.get('error', 'AI 门卫请求失败')}", ok=False)
            return
        if result.get("allow"):
            minutes = result.get("minutes", 15)
            controller.finish_gatekeeper_grant(minutes, result.get("reason", ""))
            self._set_result(
                f"✅ AI 门卫判定:可以放行 {minutes} 分钟\n"
                f"理由:{result.get('reason', '')}",
            )
        else:
            self._set_result(
                f"❌ AI 门卫判定:不建议放行\n理由:{result.get('reason', '')}",
                ok=False,
            )


class PasswordPrompt:
    def __init__(self, root, controller, title, message, callback):
        self.controller = controller
        self.callback = callback
        self.win = tk.Toplevel(root)
        self.win.title(title)
        self.win.geometry("380x220")
        self.win.configure(bg="#f5f6f8")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", lambda: self._done(False, ""))

        tk.Label(
            self.win,
            text=message,
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#333333",
            wraplength=340,
        ).pack(pady=(18, 8))
        self.entry = tk.Entry(
            self.win, show="●", font=("Consolas", 13), width=26
        )
        self.entry.pack(pady=6)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self._done(True, self.entry.get()))
        self.lbl_err = tk.Label(
            self.win, text="", font=("Microsoft YaHei UI", 10),
            bg="#f5f6f8", fg="#c0392b",
        )
        self.lbl_err.pack()
        bar = tk.Frame(self.win, bg="#f5f6f8")
        bar.pack(pady=8)
        tk.Button(
            bar, text="确定", font=("Microsoft YaHei UI", 12, "bold"),
            bg="#2a6df4", fg="#ffffff", relief="flat", padx=20, pady=6,
            command=lambda: self._done(True, self.entry.get()),
        ).pack(side="left", padx=6)
        tk.Button(
            bar, text="取消", font=("Microsoft YaHei UI", 12),
            bg="#dddddd", fg="#333333", relief="flat", padx=20, pady=6,
            command=lambda: self._done(False, ""),
        ).pack(side="left", padx=6)

    def _done(self, ok, pw):
        self.win.destroy()
        try:
            self.callback(ok, pw)
        except Exception:
            pass


# ======================================================================
# 角落提醒 Toast —— 倒计时阶段屏幕右下角弹出的小窗口
# ======================================================================

class ToastCornerWindow:
    def __init__(self, root, on_unlock):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.0)
        self.win.configure(bg="#1a1f2e")
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        w, h = 340, 130
        rect = winapi.virtual_screen_rect()
        margin = 24
        x = rect.right - w - margin
        y = rect.bottom - h - margin - 60  # 避开任务栏(粗略)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self._target_alpha = 0.94
        self._fade_in()

        # 边框感(用稍亮的 Frame 模拟)
        border = tk.Frame(self.win, bg="#2a6df4")
        border.pack(fill="both", expand=True, padx=1, pady=1)

        inner = tk.Frame(border, bg="#1a1f2e")
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        top = tk.Frame(inner, bg="#1a1f2e")
        top.pack(fill="x", padx=14, pady=(12, 4))

        self.label_icon = tk.Label(
            top, text="⚠️", font=("Segoe UI Emoji", 22),
            bg="#1a1f2e", fg="#f0c040",
        )
        self.label_icon.pack(side="left")

        self.label_title = tk.Label(
            top, text="使用时间已到",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#1a1f2e", fg="#ffffff",
        )
        self.label_title.pack(side="left", padx=(10, 0))

        self.label_reason = tk.Label(
            inner, text="", anchor="w",
            font=("Microsoft YaHei UI", 10),
            bg="#1a1f2e", fg="#b0b8c8", wraplength=300,
        )
        self.label_reason.pack(fill="x", padx=14)

        bottom = tk.Frame(inner, bg="#1a1f2e")
        bottom.pack(fill="x", padx=14, pady=(8, 6))

        self.label_countdown = tk.Label(
            bottom, text="", anchor="w",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#1a1f2e", fg="#f0c040",
        )
        self.label_countdown.pack(side="left")

        self.btn = tk.Button(
            bottom, text="紧急解锁 🔓",
            font=("Microsoft YaHei UI", 10),
            bg="#2a6df4", fg="#ffffff",
            activebackground="#1e55c4", activeforeground="#ffffff",
            relief="flat", padx=12, pady=2, cursor="hand2",
            command=on_unlock,
        )
        self.btn.pack(side="right")

    # ---- 淡入 ----
    def _fade_in(self, alpha=None):
        alpha = alpha if alpha is not None else 0.0
        try:
            self.win.attributes("-alpha", round(alpha, 3))
        except tk.TclError:
            return
        if alpha < self._target_alpha:
            self.win.after(18, lambda: self._fade_in(alpha + 0.08))

    # ---- 内容更新 ----
    def set_content(self, reason, remaining, grant_remaining):
        safe = reason or ""
        self.label_reason.config(text=safe)
        if grant_remaining and grant_remaining > 0:
            self.label_countdown.config(
                text=f"✅ 紧急放行中 · 剩余 {grant_remaining} 分钟",
                fg="#27ae60",
            )
            self.label_icon.config(text="⏳")
            self.btn.config(state="disabled")
        elif remaining > 0:
            self.label_countdown.config(
                text=f"⏳ {remaining} 秒后将执行限制措施",
                fg="#f0c040",
            )
            self.label_icon.config(text="⚠️")
            self.btn.config(state="normal")
        else:
            self.label_countdown.config(
                text="⏰ 即将执行限制措施…",
                fg="#e74c3c",
            )
            self.label_icon.config(text="⚠️")
            self.btn.config(state="normal")

    def show(self):
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass

    def hide(self):
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ======================================================================
# 休息屏保 —— 倒计时结束后全屏覆盖,显示休息倒计时
# ======================================================================

class BreakScreensaverWindow:
    REFRESH_MS = 1000

    def __init__(self, root, controller, break_minutes, next_allowed_dt=None):
        self.controller = controller
        self.break_minutes = max(0, int(break_minutes))
        # 时段限制模式:不是休息倒计时,而是显示"下次可用时间"
        self.next_allowed_dt = next_allowed_dt
        self._refresh_job = None
        self._on_unlock = getattr(controller, "open_emergency", None)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#0a0e14")
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        rect = winapi.virtual_screen_rect()
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        self.win.geometry(f"{w}x{h}+{rect.left}+{rect.top}")
        self.win.update_idletasks()
        self.win.lift()

        # 中央容器
        center = tk.Frame(self.win, bg="#0a0e14")
        center.place(relx=0.5, rely=0.5, anchor="center")

        self.label_icon = tk.Label(
            center, text="💤", font=("Segoe UI Emoji", 120),
            bg="#0a0e14", fg="#5aa9ff",
        )
        self.label_icon.pack()

        self.label_title = tk.Label(
            center, text="休息一下吧",
            font=("Microsoft YaHei UI", 36, "bold"),
            bg="#0a0e14", fg="#ffffff",
        )
        self.label_title.pack(pady=(8, 4))

        self.label_subtitle = tk.Label(
            center,
            text="远眺窗外 · 活动颈肩 · 喝杯水",
            font=("Microsoft YaHei UI", 14),
            bg="#0a0e14", fg="#7a8699",
        )
        self.label_subtitle.pack()

        self.label_countdown = tk.Label(
            center, text="",
            font=("Consolas", 56, "bold"),
            bg="#0a0e14", fg="#5aa9ff",
        )
        self.label_countdown.pack(pady=(24, 4))

        # ---- 音乐区域(仅「手动播放/自动播放」显示;「不播放」整块隐藏) ----
        self._music_mode = self._resolve_music_mode(controller)
        music_visible = self._music_mode != "disabled"
        self.label_song = None
        self.lyrics_frame = None
        self.lyric_labels = []
        self.music_btns = None
        self.btn_music_prev = None
        self.btn_music_toggle = None
        self.btn_music_next = None

        if music_visible:
            self.label_song = tk.Label(
                center, text="",
                font=("Microsoft YaHei UI", 13, "bold"),
                bg="#0a0e14", fg="#9fb3c8",
            )
            self.label_song.pack(pady=(18, 0))

            # 歌词显示区域：显示当前行及后续几行（模拟歌词滚动效果）
            self.lyrics_frame = tk.Frame(center, bg="#0a0e14")
            self.lyrics_frame.pack(pady=(4, 0))

            # 创建3行歌词标签（当前行+后续2行）
            for i in range(3):
                label = tk.Label(
                    self.lyrics_frame, text="",
                    font=("Microsoft YaHei UI", 18 - i*2, "bold" if i==0 else "normal"),
                    bg="#0a0e14",
                    fg=["#ffffff", "#a0a0ff", "#6060ff"][i],  # 当前行白色，后续渐变蓝色
                    wraplength=min(720, w - 120), justify="center",
                )
                label.pack(pady=(1, 0))
                self.lyric_labels.append(label)

            # ---- 音乐控制按钮 ----
            self.music_btns = tk.Frame(center, bg="#0a0e14")
            self.music_btns.pack(pady=(18, 0))

            self.btn_music_prev = tk.Button(
                self.music_btns, text="⏮ 上一首",
                font=("Microsoft YaHei UI", 12),
                bg="#1a2332", fg="#9fb3c8",
                activebackground="#2a3442", activeforeground="#ffffff",
                relief="flat", padx=14, pady=6, cursor="hand2",
                command=self._music_prev,
            )
            self.btn_music_prev.pack(side="left", padx=6)

            # 手动播放模式:洛雪刚启动、尚未播放,初始显示「播放」
            toggle_text = "▶ 播放" if self._music_mode == "manual" else "⏸ 停止"
            self.btn_music_toggle = tk.Button(
                self.music_btns, text=toggle_text,
                font=("Microsoft YaHei UI", 12, "bold"),
                bg="#1a2332", fg="#f0c040",
                activebackground="#2a3442", activeforeground="#ffffff",
                relief="flat", padx=18, pady=6, cursor="hand2",
                command=self._music_toggle,
            )
            self.btn_music_toggle.pack(side="left", padx=6)

            self.btn_music_next = tk.Button(
                self.music_btns, text="⏭ 下一首",
                font=("Microsoft YaHei UI", 12),
                bg="#1a2332", fg="#9fb3c8",
                activebackground="#2a3442", activeforeground="#ffffff",
                relief="flat", padx=14, pady=6, cursor="hand2",
                command=self._music_next,
            )
            self.btn_music_next.pack(side="left", padx=6)

        # ---- 紧急解锁按钮 ----
        self.btn_unlock = tk.Button(
            center, text="紧急使用 🔓",
            font=("Microsoft YaHei UI", 16, "bold"),
            bg="#2a6df4", fg="#ffffff",
            activebackground="#1e55c4", activeforeground="#ffffff",
            relief="flat", padx=32, pady=10, cursor="hand2",
            command=self._open_emergency,
        )
        self.btn_unlock.pack(pady=(24, 0))

        self.label_hint = tk.Label(
            center,
            text="休息结束后将自动解锁 · 也可随时点击上方按钮",
            font=("Microsoft YaHei UI", 11),
            bg="#0a0e14", fg="#555e6e",
        )
        self.label_hint.pack(pady=(16, 0))

        # 注册音乐状态回调(不播放模式下不注册,屏保也不显示播放器)
        self._music_player = getattr(controller, "music_player", None)
        if self._music_player is not None and music_visible:
            self._music_player.set_status_callback(self._on_music_status)
            # 如果已有状态,立即刷新
            st = self._music_player.get_current_status()
            if st is not None:
                self._apply_music_status(st)
        else:
            self._music_player = None

        # 时段限制模式:改为展示"下次可用时间",而非休息倒计时
        if self.next_allowed_dt is not None:
            self._apply_schedule_mode()

    @staticmethod
    def _resolve_music_mode(controller) -> str:
        """读取配置中的休息音乐模式(仅支持 disabled/manual/auto)。"""
        try:
            get_cfg = getattr(controller, "get_cfg", None)
            cfg = get_cfg() if callable(get_cfg) else {}
            music = (cfg or {}).get("music", {}) or {}
            return normalize_music_mode(music.get("mode"))
        except Exception as exc:
            log.debug("resolve music mode failed: %s", exc)
            return "disabled"

    def _apply_schedule_mode(self):
        """把休息屏保切换为时段限制展示:显示下次可用时间,不跑倒计时。"""
        self.label_icon.config(text="⏰")
        self.label_title.config(text="当前不在使用时段")
        self.label_subtitle.config(text="请合理安排使用时间,稍后会自动解锁")
        self.label_countdown.config(text=self._format_next_time(self.next_allowed_dt))
        self.label_hint.config(
            text="可用时间到达后将自动解锁 · 也可随时点击上方按钮"
        )

    @staticmethod
    def _format_next_time(dt: datetime.datetime) -> str:
        """把下次可用时刻格式化为「今天 14:30」「明天 08:00」等形式。"""
        now = datetime.datetime.now()
        if dt.date() == now.date():
            prefix = "今天"
        elif dt.date() == (now + datetime.timedelta(days=1)).date():
            prefix = "明天"
        else:
            prefix = f"{dt.month}月{dt.day}日"
        return f"{prefix} {dt.strftime('%H:%M')}"

    def _open_emergency(self):
        try:
            if callable(self._on_unlock):
                self._on_unlock()
        except Exception as exc:
            log.exception("break screensaver unlock button failed: %s", exc)

    # ---- 音乐控制按钮回调 ----
    def _music_prev(self):
        if self._music_player:
            self._music_player.user_prev()

    def _music_next(self):
        if self._music_player:
            self._music_player.user_next()

    def _music_toggle(self):
        if self._music_player:
            status = self._music_player.get_current_status()
            if status and status.playing:
                self._music_player.user_stop()  # 暂停
            else:
                self._music_player.user_play()  # 播放

    # ---- 音乐状态更新 ----
    def _on_music_status(self, st):
        """来自 music_player 轮询线程的回调 — 需切到 UI 线程。"""
        try:
            self.win.after(0, lambda: self._apply_music_status(st))
        except tk.TclError:
            pass

    def _apply_music_status(self, st):
        if self.label_song is None or self.btn_music_toggle is None:
            return  # 不播放模式:屏保没有播放器 UI
        try:
            if st.name and st.singer:
                self.label_song.config(text=f"🎵 {st.singer} — {st.name}")
            elif st.name:
                self.label_song.config(text=f"🎵 {st.name}")
            else:
                self.label_song.config(text="")
            # 更新歌词显示：当前行及后续几行
            for i, label in enumerate(self.lyric_labels):
                if i < len(st.lyrics_lines):
                    label.config(text=st.lyrics_lines[i])
                else:
                    label.config(text="")
            # 更新音乐控制按钮状态
            if st.playing:
                self.btn_music_toggle.config(text="⏸ 停止")
            else:
                self.btn_music_toggle.config(text="▶ 播放")
        except tk.TclError:
            pass

    # ---- 刷新 ----
    def _refresh(self):
        # 时段限制模式:展示的是静态的"下次可用时间",无需每秒刷新倒计时
        if self.next_allowed_dt is not None:
            return
        try:
            state = self.controller.state
            elapsed = state.break_elapsed_seconds()
            total = self.break_minutes * 60
            remaining = max(0, total - elapsed)
            mm = remaining // 60
            ss = remaining % 60
            self.label_countdown.config(text=f"{mm:02d}:{ss:02d}")
        except tk.TclError:
            return
        except Exception as exc:
            log.warning("break screensaver refresh error: %s", exc)
        self._refresh_job = self.win.after(
            self.REFRESH_MS, self._refresh
        )

    # ---- 歌词脉冲效果 ----
    def _stop_lyric_pulse(self):
        """停止歌词脉冲效果"""
        if self._lyric_pulse_job is not None:
            try:
                self.win.after_cancel(self._lyric_pulse_job)
            except tk.TclError:
                pass
            self._lyric_pulse_job = None

    def show(self):
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        if self._refresh_job is None:
            self._refresh()

    def hide(self):
        if self._refresh_job is not None:
            try:
                self.win.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def destroy(self):
        # 注销音乐状态回调,避免屏保销毁后还收到回调
        if self._music_player is not None:
            try:
                self._music_player.set_status_callback(None)
            except Exception:
                pass
        self.hide()
        try:
            self.win.destroy()
        except tk.TclError:
            pass
