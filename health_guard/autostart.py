import logging
import pathlib
import sys
import winreg

log = logging.getLogger("health_guard.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "HealthGuardApp"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = pathlib.Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    target = pythonw if pythonw.exists() else exe
    script = pathlib.Path(__file__).resolve().parent.parent / "run.py"
    return f'"{target}" "{script}"'


def current_value() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def is_enabled() -> bool:
    return current_value() is not None


def set_enabled(enabled: bool) -> None:
    wanted = launch_command() if enabled else None
    if current_value() == wanted:
        return
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, wanted)
            log.info("auto-start enabled: %s", wanted)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
            log.info("auto-start disabled")
