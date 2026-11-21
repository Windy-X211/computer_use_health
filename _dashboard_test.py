import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="hg_dash_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.config import load_config, save_config
from health_guard.constants import DEFAULT_CONFIG
from health_guard.controller import Controller
from health_guard.util import deep_merge

FAILS = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILS.append(name)
    print(f"[{status}] {name} {extra}")


cfg = load_config()
cfg["enabled"] = True
cfg["mode"] = "duration"
cfg["duration"] = {
    "daily_limit_minutes": 60,
    "session_limit_minutes": 30,
    "break_minutes": 5,
}
cfg["strategy"]["primary_action"] = "screensaver"
cfg["strategy"]["warning_seconds"] = 20
save_config(cfg)

ctrl = Controller(cfg, safe_mode=True, no_watchdog=True)

st = ctrl.get_dashboard_state()
check("dashboard state has keys", all(
    k in st for k in [
        "enabled", "safe_mode", "paused", "allowed", "reason",
        "daily_used_sec", "daily_limit_sec", "session_sec",
        "session_limit_sec", "mode", "primary_action", "toggles",
        "steppers", "grant_min", "in_break",
    ]
))
check("enabled reflects cfg", st["enabled"] is True)
check("safe_mode reflects", st["safe_mode"] is True)
check("daily_limit_sec = 3600", st["daily_limit_sec"] == 3600, str(st["daily_limit_sec"]))
check("session_limit_sec = 1800", st["session_limit_sec"] == 1800)
check("mode = duration", st["mode"] == "duration")
check("primary_action = screensaver", st["primary_action"] == "screensaver")
check("toggles has 3 keys", len(st["toggles"]) == 3, str(st["toggles"]))
check("steppers has 4 keys", len(st["steppers"]) == 4, str(st["steppers"]))
check("steppers daily = 60", st["steppers"]["daily_limit_minutes"] == 60)
check("steppers warning = 20", st["steppers"]["warning_seconds"] == 20)
check("reason is non-empty", bool(st["reason"]))

ok = ctrl.apply_quick_change("enabled", False)
check("apply_quick_change enabled=False returns True", ok)
cfg_after = load_config()
check("config saved enabled=False", cfg_after["enabled"] is False)

ok = ctrl.apply_quick_change("daily_limit_minutes", 180)
check("apply_quick_change daily=180 returns True", ok)
cfg_after = load_config()
check("config saved daily=180", cfg_after["duration"]["daily_limit_minutes"] == 180)

ok = ctrl.apply_quick_change("mode", "schedule")
check("apply_quick_change mode=schedule returns True", ok)
check("controller cfg updated mode", ctrl.cfg["mode"] == "schedule")

ok = ctrl.apply_quick_change("primary_action", "lock")
check("apply_quick_change action=lock returns True", ok)
check("controller cfg updated action", ctrl.cfg["strategy"]["primary_action"] == "lock")

ok = ctrl.apply_quick_change("block_apps", True)
check("apply_quick_change block_apps=True returns True", ok)
check("controller cfg updated block_apps", ctrl.cfg["strategy"]["block_apps"] is True)

ok = ctrl.apply_quick_change("gatekeeper_enabled", True)
check("apply_quick_change gk=True returns True", ok)
check("controller cfg updated gk enabled", ctrl.cfg["gatekeeper"]["enabled"] is True)

ok = ctrl.apply_quick_change("warning_seconds", 45)
check("apply_quick_change warning=45 returns True", ok)
check("controller cfg updated warning", ctrl.cfg["strategy"]["warning_seconds"] == 45)

ok = ctrl.apply_quick_change("bogus_key", 999)
check("apply_quick_change unknown key returns False", ok is False)

ok = ctrl.apply_quick_change("daily_limit_minutes", "not a number")
check("apply_quick_change bad cast returns False", ok is False)

ctrl2 = Controller(deep_merge(DEFAULT_CONFIG, {}), safe_mode=True, no_watchdog=True)
ok = ctrl2.apply_quick_change("daily_limit_minutes", 0)
check("out-of-range value rejected by validate", ok is False)

# regression: without an emergency password, restrictions can never be enabled
guard = Controller(deep_merge(DEFAULT_CONFIG, {}), safe_mode=True, no_watchdog=True)
guard.cfg["enabled"] = False
ok = guard.apply_quick_change("enabled", True)
check("REFUSE enable without password", ok is False)
check("REFUSE enable leaves cfg disabled", guard.cfg["enabled"] is False)

# once a password exists, enabling is allowed and the session timer resets
from health_guard.emergency import set_password as _set_pw

h, s = _set_pw("test1234")
guard.cfg["emergency"]["password_hash"] = h
guard.cfg["emergency"]["password_salt"] = s
before = guard.state.session_started_at
ok = guard.apply_quick_change("enabled", True)
check("enable allowed after password set", ok is True)
check("cfg enabled after password set", guard.cfg["enabled"] is True)
check("session reset on enable transition",
      guard.state.session_started_at != before)

# save_settings has the same guard
enable_cfg = deep_merge(DEFAULT_CONFIG, {})
enable_cfg["enabled"] = True
guard2 = Controller(deep_merge(DEFAULT_CONFIG, {}), safe_mode=True, no_watchdog=True)
refused = guard2.save_settings(enable_cfg)
check("REFUSE save_settings enabled without password", refused is False)
check("save_settings refusal leaves cfg unchanged", guard2.cfg["enabled"] is False)
guard2.cfg["emergency"]["password_hash"] = h
guard2.cfg["emergency"]["password_salt"] = s
allowed = guard2.save_settings(enable_cfg)
check("save_settings ok with password present", allowed is True)
check("save_settings applied enabled", guard2.cfg["enabled"] is True)

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("ALL DASHBOARD TESTS PASSED")
