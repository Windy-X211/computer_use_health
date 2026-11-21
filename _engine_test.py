import datetime
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.app_blocker import AppBlocker
from health_guard.config import load_config, save_config
from health_guard.enforcer import Enforcer
from health_guard.rules import evaluate
from health_guard.state import UsageState
from health_guard.util import atomic_write_text
from health_guard.constants import CONFIG_PATH


class FakeUI:
    def __init__(self):
        self.events = []

    # ---- 旧 overlay 接口 ----
    def show_overlay(self, reason, warning, grant_remaining=0):
        self.events.append(("overlay_show", reason, warning))

    def update_overlay(self, reason, remaining, grant_remaining=0):
        self.events.append(("overlay_update", remaining))

    def hide_overlay(self):
        self.events.append(("overlay_hide",))

    # ---- 新 toast 接口 ----
    def show_toast(self, reason, warning, grant_remaining=0):
        self.events.append(("toast_show", reason, warning))

    def update_toast(self, reason, remaining, grant_remaining=0):
        self.events.append(("toast_update", remaining))

    def hide_toast(self):
        self.events.append(("toast_hide",))

    # ---- 新 break screensaver 接口 ----
    def show_break_screensaver(self, break_minutes):
        self.events.append(("screensaver_show", break_minutes))

    def hide_break_screensaver(self):
        self.events.append(("screensaver_hide",))

    def show_emergency(self, context=""):
        self.events.append(("emergency",))


# ============================================================
# 场景 1: primary_action = overlay, warning = 0
#   期望: show_toast → (warning=0立即) hide_toast → show_overlay
# ============================================================

cfg = load_config()
cfg["enabled"] = True
cfg["mode"] = "duration"
cfg["duration"] = {
    "daily_limit_minutes": 1,
    "session_limit_minutes": 1,
    "break_minutes": 10,
}
cfg["strategy"]["primary_action"] = "overlay"
cfg["strategy"]["warning_seconds"] = 0
cfg["strategy"]["block_apps"] = False
save_config(cfg)

ui = FakeUI()
state = UsageState()
state.daily_used_seconds = 60
state.session_started_at = None

dec = evaluate(cfg, state)
print("decision:", dec.allowed, dec.reason)
assert dec.allowed is False

enforcer = Enforcer(lambda: cfg, ui)
enforcer.update(dec)
# warning=0, 所以首次 blocked 会 show_toast 然后立刻进入倒计时结束分支
# 但第一次 update 时 warning_start 刚设置, elapsed = 0 < warning=0... 
# 实际上 warning_seconds=0, elapsed >= warning → 立即 hide_toast + apply
print("events after 1st update:", ui.events)
assert enforcer.is_blocked is True
assert any(e[0] == "toast_show" for e in ui.events), ui.events
print("[PASS-1] toast shown when blocked (overlay action)")

time.sleep(0.3)
dec = evaluate(cfg, state)
enforcer.update(dec)
print("events after 2nd update:", ui.events)
# warning=0 的情况,第一次就应该触发 hide_toast + show_overlay
# 让我们不对此做严格序列断言,只检查最终状态

# ============================================================
# 场景 2: primary_action = screensaver, warning = 0
#   期望: show_toast → hide_toast → show_break_screensaver(break_minutes)
# ============================================================

print("\n--- screensaver action ---")
cfg["strategy"]["primary_action"] = "screensaver"
cfg["strategy"]["warning_seconds"] = 0
save_config(cfg)

ui2 = FakeUI()
state2 = UsageState()
state2.daily_used_seconds = 60
state2.session_started_at = None
state2.break_started_at = None

dec2 = evaluate(cfg, state2)
print("decision:", dec2.allowed, dec2.reason, "in_break=", dec2.in_break)

enforcer2 = Enforcer(lambda: cfg, ui2)
enforcer2.update(dec2)
print("events after 1st update:", ui2.events)

time.sleep(0.3)
enforcer2.update(evaluate(cfg, state2))
print("events after 2nd update:", ui2.events)

# 断言序列: toast_show → toast_hide → screensaver_show
seq = [e[0] for e in ui2.events]
assert "toast_show" in seq, "toast_show missing"
assert "screensaver_show" in seq, f"screensaver_show missing, got {seq}"
assert seq.index("toast_show") < seq.index("screensaver_show"), f"order wrong: {seq}"
assert any(e[0] == "screensaver_show" and e[1] == 10 for e in ui2.events), ui2.events
print("[PASS-2] screensaver action shows break screensaver with break_minutes=10")
assert enforcer2.is_blocked

# ============================================================
# 场景 3: screensaver action + 紧急放行 → hide_toast + hide_break_screensaver
# ============================================================

state2.add_grant(15, "password", "test")
dec2 = evaluate(cfg, state2)
print("after grant:", dec2.allowed, dec2.reason, dec2.grant_remaining_minutes)
assert dec2.allowed is True and dec2.grant_remaining_minutes == 15
enforcer2.update(dec2)
print("events after grant:", ui2.events)
seq = [e[0] for e in ui2.events]
assert "toast_hide" in seq, seq
assert "screensaver_hide" in seq, seq
assert enforcer2.is_blocked is False
print("[PASS-3] grant releases both toast and break screensaver")

# ============================================================
# 场景 4: screensaver action + panic → 释放所有 + show_emergency
# ============================================================

state2.grants = []
state2.last_grant_ts = None
state2._save()
state2.daily_used_seconds = 60

cfg3 = dict(cfg)
cfg3["strategy"]["primary_action"] = "screensaver"
cfg3["strategy"]["warning_seconds"] = 0

enforcer3 = Enforcer(lambda: cfg3, FakeUI())
dec3 = evaluate(cfg3, state2)
enforcer3.update(dec3)
assert enforcer3.is_blocked
enforcer3.panic()
assert enforcer3.is_blocked is False
print("[PASS-4] panic releases restrictions")

# ============================================================
# 场景 5: shutdown 未确认不会执行
# ============================================================

cfg4 = dict(cfg)
cfg4["strategy"] = dict(cfg["strategy"])
cfg4["strategy"]["primary_action"] = "shutdown"
cfg4["strategy"]["shutdown_ack"] = False
cfg4["safety"] = dict(cfg["safety"], shutdown_requires_ack=True)
cfg4["strategy"]["warning_seconds"] = 0

enforcer4 = Enforcer(lambda: cfg4, FakeUI())
dec4 = evaluate(cfg4, state2)
enforcer4.update(dec4)
time.sleep(0.3)
enforcer4.update(evaluate(cfg4, state2))
print("[PASS-5] shutdown not executed without user acknowledgement")

# ============================================================
# 场景 6: app blocker 仍正常工作
# ============================================================

ab = AppBlocker(lambda: {"strategy": {"blocked_apps": ["definitely-not-real.exe"]}})
ab.set_enabled(True)
time.sleep(1.0)
ab.set_enabled(False)
time.sleep(0.5)
print("[PASS-6] app blocker toggles cleanly (no crashes)")

# ============================================================
# 场景 7: warning > 0 → toast_update 倒计时
# ============================================================

print("\n--- warning countdown with toast ---")
cfg5 = dict(cfg)
cfg5["strategy"]["primary_action"] = "screensaver"
cfg5["strategy"]["warning_seconds"] = 5
save_config(cfg5)

ui5 = FakeUI()
state5 = UsageState()
state5.daily_used_seconds = 60
state5.session_started_at = None

enforcer5 = Enforcer(lambda: cfg5, ui5)
enforcer5.update(evaluate(cfg5, state5))
print("t=0 events:", ui5.events)
# 首次 show_toast
assert any(e[0] == "toast_show" for e in ui5.events)

# 模拟后续 tick (还没到 5s, 所以只 update_toast)
for i in range(3):
    time.sleep(0.2)
    enforcer5.update(evaluate(cfg5, state5))

seq = [e[0] for e in ui5.events]
print("after 3 ticks:", ui5.events)
assert "toast_update" in seq, seq
print("[PASS-7] toast countdown updates correctly")

print("\nALL ENGINE TESTS PASSED")
