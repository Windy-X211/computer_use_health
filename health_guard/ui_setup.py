import logging
import tkinter as tk

log = logging.getLogger("health_guard.ui_setup")


class SetupWizard:
    def __init__(self, root, controller, cancellable=False, on_close=None):
        self.controller = controller
        self.cancellable = cancellable
        self.on_close = on_close
        self.win = tk.Toplevel(root)
        self.win.title("重新设置 - 电脑使用健康管家" if cancellable else "首次设置 - 电脑使用健康管家")
        self.win.geometry("520x460")
        self.win.configure(bg="#f5f6f8")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.protocol(
            "WM_DELETE_WINDOW", self._cancel if cancellable else (lambda: None)
        )
        self._step = 0
        self._build_step1()

    def _cancel(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close is not None:
            self.on_close()

    def _clear(self):
        for w in self.win.winfo_children():
            w.destroy()

    def _add_cancel_button(self):
        if not self.cancellable:
            return
        tk.Button(
            self.win,
            text="取消(不修改设置)",
            font=("Microsoft YaHei UI", 11),
            bg="#e5e7eb",
            fg="#333333",
            relief="flat",
            padx=20,
            pady=6,
            command=self._cancel,
        ).pack(pady=(6, 12))

    def _build_step1(self):
        self._clear()
        tk.Label(
            self.win,
            text="👋 欢迎使用 电脑使用健康管家",
            font=("Microsoft YaHei UI", 18, "bold"),
            bg="#f5f6f8",
            fg="#1c1c1c",
        ).pack(pady=(24, 8))
        tk.Label(
            self.win,
            text=(
                "本工具将按照你设定的时长/时段,自动限制电脑使用,"
                "帮助你保持健康的使用习惯。\n\n"
                "限制手段包括:全屏拦截、强制屏保、锁定屏幕、"
                "拦截指定应用,以及可选的注销/关机。\n\n"
                "内置多重安全防护:配置自动备份、看门狗进程、"
                "紧急密码 + 恢复码 + AI 门卫,确保电脑不会被锁死。"
            ),
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#444444",
            justify="left",
            wraplength=460,
        ).pack(padx=30, pady=(0, 10))
        self.var_ack = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.win,
            text="我已了解限制机制与安全防护,同意继续使用",
            variable=self.var_ack,
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack(pady=(6, 12))
        tk.Button(
            self.win,
            text="继续",
            font=("Microsoft YaHei UI", 13, "bold"),
            bg="#2a6df4",
            fg="#ffffff",
            relief="flat",
            padx=28,
            pady=8,
            command=self._step1_next,
        ).pack()
        self._add_cancel_button()

    def _step1_next(self):
        if not self.var_ack.get():
            self._flash("请先勾选同意")
            return
        self._build_step2()

    def _flash(self, text):
        lbl = tk.Label(
            self.win,
            text=text,
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#c0392b",
        )
        lbl.pack()
        self.win.after(2000, lbl.destroy)

    def _build_step2(self):
        self._clear()
        tk.Label(
            self.win,
            text="设置紧急密码",
            font=("Microsoft YaHei UI", 17, "bold"),
            bg="#f5f6f8",
            fg="#1c1c1c",
        ).pack(pady=(24, 6))
        tk.Label(
            self.win,
            text="这是你被限制时的应急钥匙,请牢记(至少 4 位)",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#666666",
        ).pack(pady=(0, 10))
        tk.Label(
            self.win, text="密码", font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack()
        self.entry_pw = tk.Entry(
            self.win, show="●", font=("Consolas", 13), width=28
        )
        self.entry_pw.pack(pady=4)
        tk.Label(
            self.win, text="确认密码", font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack()
        self.entry_pw2 = tk.Entry(
            self.win, show="●", font=("Consolas", 13), width=28
        )
        self.entry_pw2.pack(pady=4)
        self.lbl_err = tk.Label(
            self.win, text="", font=("Microsoft YaHei UI", 10),
            bg="#f5f6f8", fg="#c0392b",
        )
        self.lbl_err.pack()
        tk.Button(
            self.win,
            text="下一步",
            font=("Microsoft YaHei UI", 13, "bold"),
            bg="#2a6df4",
            fg="#ffffff",
            relief="flat",
            padx=28,
            pady=8,
            command=self._step2_next,
        ).pack(pady=8)
        self._add_cancel_button()

    def _step2_next(self):
        pw = self.entry_pw.get()
        pw2 = self.entry_pw2.get()
        if len(pw) < 4:
            self.lbl_err.config(text="密码至少 4 位")
            return
        if pw != pw2:
            self.lbl_err.config(text="两次输入的密码不一致")
            return
        self.password = pw
        self._build_step3()

    def _build_step3(self):
        self._clear()
        code, code_hash, code_salt = self.controller.generate_recovery_code()
        self.recovery = (code, code_hash, code_salt)
        tk.Label(
            self.win,
            text="保存你的紧急恢复码",
            font=("Microsoft YaHei UI", 17, "bold"),
            bg="#f5f6f8",
            fg="#1c1c1c",
        ).pack(pady=(24, 6))
        tk.Label(
            self.win,
            text="如果忘记密码,可用恢复码解锁。请立即抄写保存,此码只显示一次:",
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
            fg="#666666",
            wraplength=460,
        ).pack(pady=(0, 10))
        box = tk.Frame(self.win, bg="#ffffff", padx=16, pady=10)
        box.pack(pady=4)
        tk.Label(
            box,
            text=code,
            font=("Consolas", 15, "bold"),
            bg="#ffffff",
            fg="#c0392b",
        ).pack()
        tk.Button(
            self.win,
            text="复制到剪贴板",
            font=("Microsoft YaHei UI", 11),
            bg="#dddddd",
            fg="#333333",
            relief="flat",
            padx=14,
            pady=5,
            command=lambda: self._copy_code(code),
        ).pack(pady=(8, 4))
        self.var_saved = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.win,
            text="我已保存恢复码",
            variable=self.var_saved,
            font=("Microsoft YaHei UI", 11),
            bg="#f5f6f8",
        ).pack(pady=(4, 10))
        tk.Button(
            self.win,
            text="完成设置",
            font=("Microsoft YaHei UI", 13, "bold"),
            bg="#1a7f37",
            fg="#ffffff",
            relief="flat",
            padx=28,
            pady=8,
            command=self._finish,
        ).pack()
        self._add_cancel_button()

    def _copy_code(self, code):
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(code)
        except Exception:
            pass

    def _finish(self):
        if not self.var_saved.get():
            return
        code, code_hash, code_salt = self.recovery
        self.controller.finish_setup(
            self.password, code, code_hash, code_salt
        )
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close is not None:
            self.on_close()
        self.controller.notify_tray(
            "设置完成",
            "健康管家已就绪,可在托盘菜单中打开设置。",
        )
