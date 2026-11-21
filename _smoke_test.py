import datetime
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="hg_test_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard import emergency, gatekeeper, rules
from health_guard.config import load_config, save_config
from health_guard.constants import CONFIG_PATH, DEFAULT_CONFIG
from health_guard.state import UsageState
from health_guard.util import atomic_write_text, deep_merge, read_json

FAILS = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILS.append(name)
    print(f"[{status}] {name} {extra}")


# 1. defaults load with restrictions disabled
cfg = load_config()
check("default loaded", cfg["enabled"] is False, f"enabled={cfg['enabled']}")
check("default has password fields", cfg["emergency"]["password_hash"] == "")

# 2. save twice then load roundtrip (second save backs up first config)
cfg["enabled"] = True
cfg["duration"]["daily_limit_minutes"] = 120
save_config(cfg)
cfg["duration"]["daily_limit_minutes"] = 90
save_config(cfg)
cfg2 = load_config()
check("roundtrip daily limit", cfg2["duration"]["daily_limit_minutes"] == 90)
check("roundtrip enabled", cfg2["enabled"] is True)
check("backup created on second save", len(list(__import__("pathlib").Path(os.environ["HEALTHGUARD_HOME"]).joinpath("backups").glob("*"))) == 1)

# 3. corrupt config -> recover from backup (latest = first save with 120)
atomic_write_text(CONFIG_PATH, "{ this is not json ")
cfg3 = load_config()
check("corrupt config recovers enabled from backup", cfg3["enabled"] is True)
check("corrupt config recovers limit from backup",
      cfg3["duration"]["daily_limit_minutes"] == 120)

# 4. defaults must not be polluted by mutations (deep_merge isolation)
from health_guard.constants import DEFAULT_CONFIG as DC
check("DEFAULT_CONFIG not polluted", DC["duration"]["daily_limit_minutes"] == 240
      and DC["enabled"] is False)

# 4. totally invalid + no backup -> fail open
import health_guard.constants as C
for bak in C.BACKUP_DIR.glob("*"):
    bak.unlink()
atomic_write_text(CONFIG_PATH, "{ broken ")
cfg4 = load_config()
check("no backup -> FAIL OPEN disabled", cfg4["enabled"] is False)

# 5. password hash/verify
h, s = emergency.set_password("secret123")
check("password verify ok", emergency.verify_password("secret123", h, s))
check("password verify bad", not emergency.verify_password("wrong", h, s))

code, ch, cs = emergency.generate_recovery_code()
check("recovery code format", code.startswith("HG-"), code)
check("recovery verify", emergency.verify_password(code, ch, cs))

# 6. rules: duration block
cfg = deep_merge(DEFAULT_CONFIG, {})
cfg["enabled"] = True
cfg["mode"] = "duration"
cfg["duration"] = {
    "daily_limit_minutes": 10,
    "session_limit_minutes": 5,
    "break_minutes": 1,
}
state = UsageState()
state.daily_used_seconds = 0
state.session_started_at = None
now = datetime.datetime.now()
d = rules.evaluate(cfg, state, now)
check("fresh state allowed", d.allowed, d.reason)

state.daily_used_seconds = 10 * 60
d = rules.evaluate(cfg, state, now)
check("daily limit blocks", not d.allowed, d.reason)

# 1b. regression: disabled config must NEVER enforce (the real bug that
# locked the user out on first launch with no config.json on disk)
off = deep_merge(DEFAULT_CONFIG, {})
assert off["enabled"] is False
st_off = UsageState()
st_off.daily_used_seconds = 99 * 60 * 60
st_off.session_started_at = (now - datetime.timedelta(hours=99)).isoformat()
d = rules.evaluate(off, st_off, now)
check("REGRESSION disabled never blocks", d.allowed, d.reason)
check("REGRESSION disabled reason", d.reason == "限制未开启", d.reason)
check("REGRESSION disabled no block_apps", d.block_apps is False)

# session block + break
state.daily_used_seconds = 0
state.session_started_at = (now - datetime.timedelta(minutes=6)).isoformat()
state.break_started_at = None
d = rules.evaluate(cfg, state, now)
check("session limit blocks", not d.allowed, d.reason)
check("in break flagged", d.in_break)
check("break started recorded", state.break_started_at is not None)
# simulate break elapsed
state.break_started_at = (now - datetime.timedelta(minutes=2)).isoformat()
d = rules.evaluate(cfg, state, now)
check("break completion resets session", d.allowed, d.reason)

# 7. schedule block
cfg2 = deep_merge(DEFAULT_CONFIG, {})
cfg2["enabled"] = True
cfg2["mode"] = "schedule"
cfg2["schedule"]["blocked_windows"] = [
    {"days": list(range(7)), "start": "00:00", "end": "23:59"}
]
state2 = UsageState()
state2.session_started_at = None
d = rules.evaluate(cfg2, state2, now)
check("schedule block active", not d.allowed, d.reason)

# 8. grant overrides block
state2.add_grant(15, "password", "test")
d = rules.evaluate(cfg2, state2, now)
check("grant overrides block", d.allowed, d.reason)
check("grant remaining > 0", d.grant_remaining_minutes > 0)

# 9. gatekeeper json extraction
from health_guard.gatekeeper import _extract_json, GatekeeperError
r = _extract_json('{"allow": true, "minutes": 20, "reason": "紧急工作"}')
check("gatekeeper json parse", r["allow"] and r["minutes"] == 20)
r = _extract_json('一些文字 {"allow": false, "minutes": 0, "reason": "拒绝"} 结尾')
check("gatekeeper json embedded", r["allow"] is False)
try:
    _extract_json("no json here")
    check("gatekeeper bad json raises", False)
except GatekeeperError:
    check("gatekeeper bad json raises", True)

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("ALL TESTS PASSED")
