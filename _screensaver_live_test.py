"""
验证 BreakScreensaverWindow 的 3 个关键行为:
1. 倒计时数字每秒变化(真的在刷新)
2. 有紧急解锁按钮
3. 紧急面板弹出后屏保仍存在(不隐藏)
"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="hg_saver_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datetime
from health_guard.config import load_config, save_config
from health_guard.controller import Controller
from health_guard.state import UsageState

errors = []
refreshes = []
saver = None

cfg = load_config()
cfg["setup_complete"] = True
cfg["enabled"] = True
cfg["strategy"]["primary_action"] = "screensaver"
cfg["duration"]["break_minutes"] = 1
save_config(cfg)

ctrl = Controller(cfg, safe_mode=True, no_watchdog=True)

# 模拟 break 已开始,这样倒计时数字会真实变化
ctrl.state.break_started_at = (datetime.datetime.now() - datetime.timedelta(seconds=30)).isoformat()

root = ctrl.ui.root
root.report_callback_exception = lambda *a: errors.append(a)


def capture_saver():
    global saver
    # 触发 enforcer 的 screensaver 路径 — 直接调用 ui.show_break_screensaver
    ctrl.ui.show_break_screensaver(1)
    root.after(200, _poll_saver)


def _poll_saver():
    global saver, t1
    saver = ctrl.ui.break_screensaver
    assert saver is not None and saver.win.winfo_exists(), "screensaver window missing"

    # 立即读一次倒计时
    t1 = saver.label_countdown.cget("text")
    refreshes.append(t1)
    print(f"  t=0 text: {t1}")

    # 按钮存在
    assert saver.btn_unlock is not None, "btn_unlock missing"
    print("  btn_unlock: OK")

    root.after(1200, _check_tick)


def _check_tick():
    global saver
    assert saver.win.winfo_exists(), "screensaver closed unexpectedly"
    t2 = saver.label_countdown.cget("text")
    refreshes.append(t2)
    print(f"  t=1.2s text: {t2}")
    assert t1 != t2, f"倒计时没变! t1={t1}, t2={t2}"
    print("[PASS] 倒计时数字确实在变化")

    # 点击紧急解锁按钮 → 紧急面板弹出,屏保不消失
    saver._open_emergency()
    root.after(500, _check_emergency_preserves_saver)


def _check_emergency_preserves_saver():
    global saver
    assert ctrl.ui.emergency is not None and ctrl.ui.emergency.win.winfo_exists(), \
        "紧急面板没出来"
    print("  emergency dialog: OK")

    # 屏保窗口仍存在
    assert saver.win.winfo_exists(), "屏保窗口被意外关闭!"
    print("[PASS] 紧急面板弹出后,屏保窗口仍然存在")

    # 销毁
    ctrl.ui.emergency.win.destroy()
    ctrl.ui.hide_break_screensaver()
    root.after(300, root.quit)


root.after(100, capture_saver)
root.after(30000, root.quit)  # 兜底:任何回调断言失败都不会让测试永久挂起
root.mainloop()

if errors:
    print("ERRORS:", errors[:2])
    sys.exit(1)
print(f"\n刷新观测: {refreshes}")
print("\nBREAK SCREENSAVER LIVE TEST PASSED")
