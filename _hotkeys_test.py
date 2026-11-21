import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="hg_hk_")
os.environ["HEALTHGUARD_HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_guard.hotkeys import HotkeyManager

FAILS = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILS.append(name)
    print(f"[{status}] {name} {extra}")


# regression: stop() before start() must not crash
# (previously raised AttributeError: 'NoneType' object has no attribute 'ident',
# which killed the setup wizard's completion callback)
hk = HotkeyManager()
hk.stop()
check("stop() before start() does not crash", True)

hk.stop()
check("stop() twice does not crash", True)

# register returns a bool, never raises
cb = lambda: None
r = hk.register(["ctrl", "alt", "shift", "u"], cb)
check("register returns bool", isinstance(r, bool))

# stop after registering but without starting the pump
hk.stop()
check("stop() after register, no pump", True)

# register -> start -> stop full cycle must not raise
hk2 = HotkeyManager()
hk2.register(["ctrl", "alt", "shift", "x"], cb)
hk2.start()
hk2.stop()
check("start then stop cycle", True)
hk2.stop()
check("stop after stop", True)

# regression: RegisterHotKey must run on the pump thread, not the caller's
# thread. With NULL hwnd the WM_HOTKEY is posted to the queue of the thread
# that called RegisterHotKey; if registration happens on the main thread the
# pump thread's GetMessageW never sees the message and the hotkey silently
# fails to fire (the bug that made Ctrl+Alt+Shift+U unable to open the
# emergency unlock dialog).
import threading as _threading
import time as _time
from health_guard import winapi as _winapi

_reg_event = _threading.Event()
_reg_info = {}
_orig_reg = _winapi.register_hotkey


def _spy_reg(hwnd, hid, mods, vk):
    _reg_info["tid"] = _threading.get_ident()
    _reg_info["hid"] = hid
    _reg_event.set()
    return True


_winapi.register_hotkey = _spy_reg
try:
    hk3 = HotkeyManager()
    main_tid = _threading.get_ident()
    hk3.register(["ctrl", "alt", "shift", "u"], cb)
    hk3.start()
    fired = _reg_event.wait(2.0)
    _time.sleep(0.1)
    hk3.stop()
finally:
    _winapi.register_hotkey = _orig_reg

check(
    "hotkey registered on pump thread",
    fired and _reg_info.get("tid") is not None and _reg_info["tid"] != main_tid,
    f"main={main_tid} reg={_reg_info.get('tid')}",
)

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("HOTKEYS TEST PASSED")
