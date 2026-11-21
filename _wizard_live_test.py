import datetime
import os
import sys
import tempfile
import tkinter as tk

TMP = tempfile.mkdtemp(prefix="hg_wizard_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.config import load_config, save_config
from health_guard.constants import DEFAULT_CONFIG
from health_guard.controller import Controller
from health_guard.util import deep_merge

cfg = deep_merge(DEFAULT_CONFIG, {})
cfg["setup_complete"] = False
cfg["enabled"] = False
save_config(cfg)

errors = []
FAILS = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILS.append(name)
    print(f"[{status}] {name} {extra}")


ctrl = Controller(cfg, safe_mode=True, no_watchdog=True)
ui = ctrl.ui
root = ui.root
root.report_callback_exception = lambda *a: errors.append(a)


def pump(n=20):
    import time

    time.sleep(0.05)
    for _ in range(n):
        root.update()
        time.sleep(0.003)


def click_buttons(win, target_text):
    found = []

    def walk(w):
        for child in w.winfo_children():
            if isinstance(child, tk.Button) and target_text in child.cget("text"):
                found.append(child)
            walk(child)

    walk(win)
    if not found:
        return False
    for btn in found:
        try:
            btn.invoke()
            return True
        except Exception as exc:
            log = __import__("logging").getLogger("test")
            log.error("invoke failed: %s", exc)
            errors.append(str(exc))
    return bool(found)


ctrl.open_setup()
pump(30)

sw = ui.setup
check("setup wizard created", sw is not None)
check("wizard window exists", sw.win.winfo_exists())
check("wizard visible", sw.win.winfo_viewable() == 1)

check("step1: acknowledge", sw.var_ack.get() is False)
sw.var_ack.set(True)
pump()
check("step1 next button click", click_buttons(sw.win, "继续"))
pump(30)

check("step2 reached (password entries)", hasattr(sw, "entry_pw"))
sw.entry_pw.insert(0, "abcd1234")
sw.entry_pw2.insert(0, "abcd1234")
check("step2 next click", click_buttons(sw.win, "下一步"))
pump(30)

check("step3 reached (recovery code generated)",
      hasattr(sw, "recovery") and sw.recovery[0].startswith("HG-"))
check("recovery saved checkbox", hasattr(sw, "var_saved"))
sw.var_saved.set(True)
pump()
check("step3 finish click", click_buttons(sw.win, "完成设置"))
pump(30)

check("wizard window destroyed", not sw.win.winfo_exists())
check("ui.setup cleared after finish", ui.setup is None)

reload_cfg = load_config()
check("setup_complete saved", reload_cfg["setup_complete"] is True)
check("password hash saved", bool(reload_cfg["emergency"]["password_hash"]))
check("recovery hash saved", bool(reload_cfg["emergency"]["recovery_code_hash"]))
check("password verifiable",
      __import__("health_guard.emergency", fromlist=["verify_password"]).verify_password(
          "abcd1234",
          reload_cfg["emergency"]["password_hash"],
          reload_cfg["emergency"]["password_salt"],
      ))

ctrl.open_setup()
pump(30)
sw2 = ui.setup
check("re-setup reopens after finish", sw2 is not None and sw2.win.winfo_exists())
check("re-setup wizard is cancellable", sw2 is not None and sw2.cancellable)
click_buttons(sw2.win, "取消")
pump(10)
check("re-setup cancel destroys window", not sw2.win.winfo_exists())
check("re-setup after cancel cleared", ui.setup is None)

ctrl.open_setup()
pump(30)
sw3 = ui.setup
check("re-setup reopens after cancel", sw3 is not None and sw3.win.winfo_exists())
sw3._cancel()
pump(10)
check("X-button handler closes wizard", not sw3.win.winfo_exists())
check("X-button handler clears ui.setup", ui.setup is None)

if errors:
    print("TK ERRORS:", errors[:3])
    sys.exit(1)

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("WIZARD LIVE TEST PASSED")
