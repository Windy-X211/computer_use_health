import os
import subprocess
import sys
import time

from health_guard.constants import HEARTBEAT_PATH, ROOT_DIR
from health_guard.logging_setup import setup_logging
from health_guard.util import read_json

log = setup_logging()

HEARTBEAT_TIMEOUT_SECONDS = 20
CHECK_INTERVAL_SECONDS = 3


def _is_alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def heartbeat_is_fresh(timeout: int = HEARTBEAT_TIMEOUT_SECONDS) -> bool:
    heartbeat = read_json(HEARTBEAT_PATH)
    if not isinstance(heartbeat, dict) or not heartbeat.get("ts"):
        return False
    age = time.time() - float(heartbeat.get("ts", 0))
    return 0 <= age <= timeout


def recover(pid: int) -> None:
    from health_guard import winapi

    try:
        winapi.abort_shutdown()
    except Exception as exc:
        log.warning("abort_shutdown during recovery failed: %s", exc)

    try:
        if pid and _is_alive(pid):
            os.kill(pid, 9)
            log.warning("terminated stale main process pid=%s", pid)
        else:
            log.info("main process already gone (pid=%s)", pid)
    except OSError as exc:
        log.info("could not terminate stale main pid=%s: %s", pid, exc)

    time.sleep(1)

    try:
        cmd = [sys.executable, "-m", "health_guard", "--no-watchdog"]
        subprocess.Popen(cmd, cwd=str(ROOT_DIR), creationflags=0x08000000)
        log.info("attempted to restart main process")
    except Exception as exc:
        log.error("restart failed: %s", exc)


def wait_for_stale_heartbeat(timeout: int = HEARTBEAT_TIMEOUT_SECONDS) -> None:
    log.info("watchdog wait loop entered")
    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)
        if not heartbeat_is_fresh(timeout):
            return


def run(pid: int) -> None:
    log.info("watchdog started, watching main pid=%s", pid)
    wait_for_stale_heartbeat()
    log.error(
        "main process heartbeat stale (pid=%s) -> running fail-open recovery",
        pid,
    )
    recover(pid)
    log.warning("watchdog finished recovery, exiting")


def main():
    pid = None
    if "--pid" in sys.argv:
        idx = sys.argv.index("--pid")
        try:
            pid = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            log.error("invalid --pid argument")
            return 1

    if pid is None:
        log.error("watchdog requires --pid")
        return 1

    try:
        run(pid)
    except Exception as exc:
        log.exception("watchdog fatal error: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
