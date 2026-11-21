import datetime
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="hg_emerg_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.config import load_config, save_config
from health_guard.constants import DEFAULT_CONFIG
from health_guard.controller import Controller
from health_guard.emergency import set_password as _set_pw
from health_guard.rules import Decision
from health_guard.util import deep_merge

errors = []
FAILS = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILS.append(name)
    print(f"[{status}] {name} {extra}")


cfg = deep_merge(DEFAULT_CONFIG, {})
cfg["enabled"] = True
cfg["mode"] = "duration"
cfg["duration"] = {
    "daily_limit_minutes": 10,
    "session_limit_minutes": 10,
    "break_minutes": 0,
}
cfg["strategy"] = {
    "primary_action": "overlay",
    "warning_seconds": 300,
    "block_apps": False,
    "blocked_apps": [],
    "shutdown_ack": False,
}
cfg["setup_complete"] = True
h, s = _set_pw("test1234")
cfg["emergency"]["password_hash"] = h
cfg["emergency"]["password_salt"] = s
save_config(cfg)

ctrl = Controller(cfg, safe_mode=False, no_watchdog=True)
ui = ctrl.ui

from health_guard.enforcer import Enforcer

ctrl.enforcer = Enforcer(lambda: ctrl.cfg, ui)

root = ui.root
root.report_callback_exception = lambda *a: errors.append(a)


def pump(ms):
    end = datetime.datetime.now() + datetime.timedelta(milliseconds=ms)
    while datetime.datetime.now() < end:
        root.update()


pump(300)

# 1. drive a blocking decision -> overlay should appear
blocked = Decision(
    allowed=False,
    reason="测试限制",
    block_apps=False,
    action="overlay",
    warning_seconds=300,
)
ctrl.enforcer.update(blocked)
pump(300)

check("overlay window created", ui.overlay is not None)
check("overlay visible",
      ui.overlay is not None and ui.overlay.win.state() == "normal")
check("enforcer blocked", ctrl.enforcer.is_blocked is True)
check("emergency dialog not yet open", ui.emergency is None)

# 2. open emergency -> overlay MUST stay visible (restriction held), dialog on top
ctrl.open_emergency()
pump(500)

check("emergency dialog created", ui.emergency is not None)
check("overlay stays VISIBLE while dialog open (restriction not exited)",
      ui.overlay is not None and ui.overlay.win.state() == "normal")
check("overlay still mapped while dialog open",
      ui.overlay is not None and ui.overlay.win.winfo_viewable())
check("dialog exists",
      ui.emergency is not None and ui.emergency.win.winfo_exists())
check("dialog state normal",
      ui.emergency.win.state() == "normal")
check("dialog is topmost",
      ui.emergency.win.attributes("-topmost") == 1)
check("dialog visible on screen",
      ui.emergency.win.winfo_ismapped() and ui.emergency.win.winfo_viewable())
check("dialog geometry non-empty",
      ui.emergency.win.winfo_width() > 0 and ui.emergency.win.winfo_height() > 0)

# 2b. engine ticks update_overlay while the dialog is open.
#     The dialog must NOT be re-lifted (that would cover the IME candidate
#     window). It should stay visible & topmost above the overlay.
ctrl.enforcer.update(blocked)
pump(400)

check("dialog still visible after update_overlay tick",
      ui.emergency is not None
      and ui.emergency.win.winfo_ismapped()
      and ui.emergency.win.winfo_viewable())
check("dialog still topmost after update_overlay tick",
      ui.emergency.win.attributes("-topmost") == 1)
check("overlay still visible after update_overlay tick",
      ui.overlay is not None and ui.overlay.win.state() == "normal")

# 3. close the dialog -> overlay still visible (it was never hidden)
closed_flag = {"n": 0}
real_on_close = ui.emergency.on_close


def spy_on_close():
    closed_flag["n"] += 1
    real_on_close()


ui.emergency.on_close = spy_on_close
ui.emergency._on_close()
pump(400)

check("on_close callback fired", closed_flag["n"] == 1)
check("emergency reference cleared", ui.emergency is None)
check("overlay STILL VISIBLE after dialog close (never hidden)",
      ui.overlay is not None and ui.overlay.win.state() == "normal")
check("overlay mapped again",
      ui.overlay is not None and ui.overlay.win.winfo_viewable())
check("enforcer still blocked", ctrl.enforcer.is_blocked is True)

# 4. grant releases -> overlay gone for good, no reshow
ctrl.state.add_grant(15, "password", "test")
ctrl.enforcer.update(
    Decision(allowed=True, reason="紧急放行中", block_apps=False, action="none")
)
pump(300)
check("enforcer released after grant", ctrl.enforcer.is_blocked is False)
check("overlay destroyed after grant",
      ui.overlay is None or not ui.overlay.win.winfo_exists())

if errors:
    print("TK ERRORS:", errors[:2])
    sys.exit(1)

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("EMERGENCY Z-ORDER LIVE TEST PASSED")
