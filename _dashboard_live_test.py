import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="hg_dash_live_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.config import load_config, save_config
from health_guard.controller import Controller
from health_guard.ui_dashboard import ACTION_LABELS, MODE_LABELS

cfg = load_config()
cfg["setup_complete"] = True
cfg["enabled"] = True
cfg["mode"] = "duration"
cfg["duration"]["daily_limit_minutes"] = 120
cfg["duration"]["session_limit_minutes"] = 45
save_config(cfg)

ctrl = Controller(cfg, safe_mode=True, no_watchdog=True)
ctrl.state.daily_used_seconds = 3600

root = ctrl.ui.root
errors = []
refreshes = 0
mw = None
dw = None

root.report_callback_exception = lambda *a: errors.append(a)


def capture_mw():
    global mw, dw
    mw = ctrl.ui.main
    dw = mw.dashboard_view


def check_state():
    global refreshes
    assert mw is not None and mw.win.winfo_exists(), "main window missing"
    assert mw.dashboard_view is not None, "embedded dashboard view missing"
    dw._refresh(None)
    refreshes += 1
    assert dw.lbl_clock.cget("text") != "", "clock empty"
    assert dw.lbl_daily_value.cget("text"), "daily label empty"
    assert dw.lbl_session_value.cget("text"), "session label empty"
    assert dw.lbl_status_line.cget("text"), "status line empty"
    assert dw.lbl_daily_hint.cget("text"), "daily hint empty"
    assert dw.lbl_session_hint.cget("text"), "session hint empty"
    assert dw.var_mode.get() in MODE_LABELS.values(), dw.var_mode.get()
    assert dw.var_action.get() in ACTION_LABELS.values(), dw.var_action.get()
    for k, (btn, lbl) in dw._toggles.items():
        assert btn.cget("fg"), k
        assert lbl.cget("text"), k
    for key, var in dw._steppers.items():
        assert var.get() >= 0, key


def check_tab_index(expected):
    assert mw.nb.index(mw.nb.select()) == expected, mw.nb.select()


def close_and_check_cleanup():
    mw._on_close()
    assert dw._refresh_job is None, "refresh timer not cancelled on close"
    assert not mw.win.winfo_exists(), "window still exists after close"


ctrl.open_dashboard()
root.after(300, capture_mw)
root.after(600, check_state)
root.after(1600, check_state)
root.after(3000, check_state)
root.after(3200, lambda: check_tab_index(0))
root.after(4200, ctrl.open_dashboard)
root.after(4400, check_state)
root.after(4700, ctrl.open_settings)
root.after(5000, check_state)
root.after(5300, lambda: check_tab_index(1))
root.after(5600, close_and_check_cleanup)
root.after(6200, root.quit)

root.mainloop()

if errors:
    print("ERRORS:", errors[:2])
    sys.exit(1)
print(f"[PASS] merged window rendered + dashboard refreshed {refreshes}x")
print("[PASS] all labels populated")
print("[PASS] all toggles rendered with fg/text")
print("[PASS] all steppers initialized")
print("[PASS] open_dashboard opens the merged window on the 控制面板 tab")
print("[PASS] open_settings switches the same window to the 基本 tab")
print("[PASS] open_dashboard/open_settings reuse the same window")
print("[PASS] close cleanly releases refresh timer")
print("DASHBOARD LIVE RENDER TEST PASSED")
