import datetime
import logging
import os
import subprocess
import sys
import threading
import time

from health_guard import autostart, emergency, gatekeeper, rules, winapi
from health_guard.app_blocker import AppBlocker
from health_guard.config import (
    config_has_password,
    load_config,
    save_config,
)
from health_guard.music import MusicPlayer
from health_guard.constants import (
    APP_DISPLAY_NAME,
    BASE_DIR,
    HEARTBEAT_PATH,
    ROOT_DIR,
    STATE_PATH,
)
from health_guard.hotkeys import HotkeyManager
from health_guard.logging_setup import get_logger, setup_logging
from health_guard.state import UsageState
from health_guard.ui import UIApp
from health_guard.util import atomic_write_json

log = get_logger()

HEARTBEAT_EVERY_TICKS = 5


class Controller:
    def __init__(self, cfg, safe_mode=False, no_watchdog=False):
        self.cfg = cfg
        self.safe_mode = safe_mode
        self.no_watchdog = no_watchdog
        self._cfg_lock = threading.RLock()
        self.state = UsageState()
        self.state.reset_if_new_day()
        self.state.reset_session()
        self.ui = UIApp(self)
        self.tray = None
        self.hotkeys = HotkeyManager()
        self.enforcer = None
        self._stop = threading.Event()
        self._engine_thread = None
        self._watchdog_proc = None
        self._heartbeat_ts = time.time()
        self._quitting = False
        self._last_tick_mono = None
        self._last_screen_on = None
        self._screen_off_mono = None
        self.music_player = MusicPlayer(self.get_cfg)

    # ---- config access ----
    def get_cfg(self):
        with self._cfg_lock:
            return dict(self.cfg)

    def get_state(self):
        return self.state

    # ---- setup ----
    def generate_recovery_code(self):
        return emergency.generate_recovery_code()

    def finish_setup(self, password, code, code_hash, code_salt):
        with self._cfg_lock:
            pw_hash, pw_salt = emergency.set_password(password)
            self.cfg["emergency"]["password_hash"] = pw_hash
            self.cfg["emergency"]["password_salt"] = pw_salt
            self.cfg["emergency"]["recovery_code_hash"] = code_hash
            self.cfg["emergency"]["recovery_code_salt"] = code_salt
            self.cfg["setup_complete"] = True
            self._save_cfg()
        self._refresh_hotkeys()
        log.info("setup finished")

    def reset_password(self, old, new):
        if not emergency.check_password(self.cfg, old) and not (
            emergency.check_recovery_code(self.cfg, old)
        ):
            return "旧密码或恢复码错误"
        if len(new) < 4:
            return "新密码至少 4 位"
        with self._cfg_lock:
            pw_hash, pw_salt = emergency.set_password(new)
            self.cfg["emergency"]["password_hash"] = pw_hash
            self.cfg["emergency"]["password_salt"] = pw_salt
            self._save_cfg()
        return None

    def _save_cfg(self):
        try:
            save_config(self.cfg)
        except Exception as exc:
            log.exception("failed to save config: %s", exc)

    # ---- emergency ----
    def open_emergency(self):
        cooldown = emergency.cooldown_remaining_seconds(
            self.cfg, self.state
        )
        ctx = ""
        if cooldown > 0:
            ctx = f"⏳ 解锁冷却中,剩余约 {cooldown // 60} 分钟"
        elif self.enforcer and self.enforcer.is_blocked:
            ctx = "当前使用受限,请选择一种方式解锁"
        self.ui.show_emergency(ctx)

    def open_dashboard(self):
        self.ui.open_dashboard()

    def open_settings(self):
        self.ui.open_settings()

    def open_setup(self, cancellable=True):
        self.ui.open_setup(cancellable=cancellable)

    def open_password_reset(self):
        self.ui.open_password_reset()

    def try_password(self, pw):
        if emergency.check_password(self.cfg, pw):
            self._do_grant(
                int(self.cfg.get("emergency", {}).get("password_grant_minutes", 15)),
                "password",
                "紧急密码解锁",
            )
            return True
        return False

    def try_recovery_code(self, code):
        if emergency.check_recovery_code(self.cfg, code):
            self._do_grant(
                int(self.cfg.get("emergency", {}).get("password_grant_minutes", 15)),
                "recovery",
                "恢复码解锁",
            )
            return True
        return False

    def _do_grant(self, minutes, source, reason):
        emergency.grant(self.cfg, self.state, minutes, source, reason)
        if self.enforcer:
            self.enforcer.release()
        self.ui.show_tray_message(
            APP_DISPLAY_NAME,
            f"已通过{source}放行 {minutes} 分钟",
        )

    def request_gatekeeper(self, reason):
        try:
            result = gatekeeper.evaluate_request(self.cfg, self.state, reason)
            return {"ok": True, **result}
        except gatekeeper.GatekeeperError as exc:
            log.warning("gatekeeper error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def finish_gatekeeper_grant(self, minutes, reason):
        self._do_grant(minutes, "ai", reason)

    # ---- settings ----
    def save_settings(self, new_cfg):
        new_em = new_cfg.get("emergency", {})
        has_new_password = bool(
            new_em.get("password_hash") and new_em.get("password_salt")
        )
        if (
            new_cfg.get("enabled")
            and not has_new_password
            and not config_has_password(self.cfg)
        ):
            log.warning(
                "refusing to save enabled settings: no emergency password set"
            )
            self.ui.show_tray_message(
                APP_DISPLAY_NAME,
                "请先在「紧急」页设置密码,再启用限制",
            )
            return False
        old_hotkeys = list(
            self.cfg.get("emergency", {}).get("hotkey_unlock", [])
        )
        import copy
        with self._cfg_lock:
            old = copy.deepcopy(self.cfg)
            old_em = old.get("emergency", {})
            old_gk = old.get("gatekeeper", {})
            for key in (
                "enabled",
                "auto_start",
                "mode",
                "duration",
                "schedule",
                "strategy",
                "safety",
                "music",
                "session_overlay",
            ):
                if key in new_cfg:
                    self.cfg[key] = new_cfg[key]
            for key in (
                "password_grant_minutes",
                "grant_cooldown_minutes",
                "hotkey_unlock",
                "hotkey_panic",
            ):
                if key in new_em:
                    self.cfg["emergency"][key] = new_em[key]
            gk_new = new_cfg.get("gatekeeper", {})
            if set(gk_new.get("api_key", "")) == {"*"}:
                gk_new = dict(gk_new)
                gk_new["api_key"] = old_gk.get("api_key", "")
            self.cfg["gatekeeper"] = gk_new
            self.cfg["emergency"].setdefault(
                "password_hash", old_em.get("password_hash", "")
            )
            self.cfg["emergency"].setdefault(
                "password_salt", old_em.get("password_salt", "")
            )
            self.cfg["emergency"].setdefault(
                "recovery_code_hash", old_em.get("recovery_code_hash", "")
            )
            self.cfg["emergency"].setdefault(
                "recovery_code_salt", old_em.get("recovery_code_salt", "")
            )
            self._save_cfg()
            new_hotkeys = self.cfg.get("emergency", {}).get(
                "hotkey_unlock", []
            )
        if old_hotkeys != new_hotkeys:
            self._refresh_hotkeys()
        old_overlay = old.get("session_overlay", {})
        new_overlay = self.cfg.get("session_overlay", {})
        if old_overlay != new_overlay:
            self.ui._update_session_overlay(self.cfg)
        self._apply_autostart()
        log.info(
            "settings saved (enabled=%s, auto_start=%s)",
            self.cfg.get("enabled"),
            self.cfg.get("auto_start"),
        )
        return True

    def _apply_autostart(self):
        try:
            autostart.set_enabled(bool(self.cfg.get("auto_start", False)))
        except Exception as exc:
            log.error("failed to apply auto-start setting: %s", exc)
            self.ui.show_tray_message(
                APP_DISPLAY_NAME, "开机自启动设置写入失败,请检查注册表权限"
            )

    def _sync_autostart(self):
        try:
            autostart.set_enabled(bool(self.cfg.get("auto_start", False)))
        except Exception as exc:
            log.error("failed to sync auto-start on startup: %s", exc)

    # ---- manual break ----
    def start_break_now(self):
        """主动休息:清空连续使用时长并立即进入休息屏保倒计时。"""
        now = datetime.datetime.now()
        break_minutes = int(
            self.cfg.get("duration", {}).get("break_minutes", 10)
        )
        self.state.reset_session()
        if break_minutes <= 0:
            self.ui.show_tray_message(
                APP_DISPLAY_NAME, "已重置连续使用时长(未设置休息时长)"
            )
            return
        self.state.start_break(now)
        if self.enforcer:
            self.enforcer.force_break(break_minutes, "主动休息")
        self.ui.show_tray_message(
            APP_DISPLAY_NAME, f"开始休息 {break_minutes} 分钟"
        )

    # ---- pause ----
    def toggle_pause(self):
        if self.state.paused:
            self.state.paused = False
            self._save_state_safe()
            self.ui.show_tray_message(APP_DISPLAY_NAME, "限制已恢复")
            self.tray.update_menu()
            return
        if not config_has_password(self.cfg):
            self.ui.show_tray_message(
                APP_DISPLAY_NAME, "请先设置紧急密码后再暂停"
            )
            return

        def on_result(ok, pw):
            if not ok:
                return
            if emergency.check_password(self.cfg, pw):
                self.state.paused = True
                self._save_state_safe()
                if self.enforcer:
                    self.enforcer.release()
                self.ui.show_tray_message(
                    APP_DISPLAY_NAME, "限制已暂停,直到手动恢复"
                )
                self.tray.update_menu()
            else:
                self.ui.show_tray_message(APP_DISPLAY_NAME, "密码错误")

        self.ui.prompt_password(
            "暂停限制",
            "输入紧急密码以暂停限制",
            on_result,
        )

    def _save_state_safe(self):
        try:
            self.state._save()
        except Exception as exc:
            log.error("failed saving state: %s", exc)

    # ---- dashboard ----
    def get_dashboard_state(self):
        now = datetime.datetime.now()
        dur = self.cfg.get("duration", {})
        strat = self.cfg.get("strategy", {})
        gk = self.cfg.get("gatekeeper", {})
        decision = rules.evaluate(self.cfg, self.state, now)
        return {
            "enabled": bool(self.cfg.get("enabled")),
            "safe_mode": self.safe_mode,
            "paused": bool(self.state.paused),
            "allowed": bool(decision.allowed),
            "reason": decision.reason,
            "in_break": bool(decision.in_break),
            "grant_min": int(self.state.active_grant_minutes(now)),
            "daily_used_sec": int(self.state.daily_used_seconds),
            "daily_limit_sec": int(dur.get("daily_limit_minutes", 240)) * 60,
            "session_sec": int(self.state.session_seconds(now)),
            "session_limit_sec": int(
                dur.get("session_limit_minutes", 60)
            ) * 60,
            "mode": self.cfg.get("mode", "duration"),
            "primary_action": strat.get("primary_action", "screensaver"),
            "toggles": {
                "enabled": bool(self.cfg.get("enabled")),
                "block_apps": bool(strat.get("block_apps", False)),
                "gatekeeper_enabled": bool(gk.get("enabled", False)),
            },
            "steppers": {
                "daily_limit_minutes": int(
                    dur.get("daily_limit_minutes", 240)
                ),
                "session_limit_minutes": int(
                    dur.get("session_limit_minutes", 60)
                ),
                "break_minutes": int(dur.get("break_minutes", 10)),
                "warning_seconds": int(strat.get("warning_seconds", 30)),
            },
        }

    def apply_quick_change(self, key, value):
        mapping = {
            "enabled": ("enabled", value, bool),
            "mode": ("mode", value, str),
            "primary_action": ("strategy.primary_action", value, str),
            "block_apps": ("strategy.block_apps", value, bool),
            "gatekeeper_enabled": ("gatekeeper.enabled", value, bool),
            "daily_limit_minutes": ("duration.daily_limit_minutes", value, int),
            "session_limit_minutes": (
                "duration.session_limit_minutes",
                value,
                int,
            ),
            "break_minutes": ("duration.break_minutes", value, int),
            "warning_seconds": ("strategy.warning_seconds", value, int),
        }
        if key not in mapping:
            log.warning("unknown quick-change key: %s", key)
            return False
        if key == "enabled" and value is True:
            if not config_has_password(self.cfg):
                log.warning(
                    "refusing to enable restrictions: no emergency password set"
                )
                self.ui.show_tray_message(
                    APP_DISPLAY_NAME,
                    "请先设置紧急密码,再启用限制",
                )
                return False
            if not self.cfg.get("enabled"):
                self.state.reset_session()
                log.info("restrictions enabled: session timer reset")
        path, value, cast = mapping[key]
        try:
            value = cast(value)
        except (TypeError, ValueError):
            log.warning("quick-change value cast failed for %s: %r", key, value)
            return False
        with self._cfg_lock:
            try:
                if "." in path:
                    parent_key, _, leaf = path.rpartition(".")
                    self.cfg[parent_key][leaf] = value
                else:
                    self.cfg[path] = value
                save_config(self.cfg)
            except Exception as exc:
                log.error("quick-change %s rejected: %s", key, exc)
                return False
        log.info("quick-change %s -> %s", key, value)
        return True

    # ---- quit ----
    def quit_requested(self):
        if not self.state.paused and config_has_password(self.cfg):

            def on_result(ok, pw):
                if not ok:
                    return
                if emergency.check_password(self.cfg, pw):
                    self._quit()
                else:
                    self.ui.show_tray_message(APP_DISPLAY_NAME, "密码错误")

            self.ui.prompt_password(
                "退出程序",
                "输入紧急密码以退出(防止误关绕过限制)",
                on_result,
            )
        else:
            self._quit()

    def _quit(self):
        if self._quitting:
            return
        self._quitting = True
        log.info("shutting down")
        try:
            self.music_player.stop_break_music()
        except Exception as exc:
            log.error("failed to stop break music on quit: %s", exc)
        if self.enforcer:
            self.enforcer.panic()
        self._stop.set()
        try:
            self.state._save()
        except Exception as exc:
            log.error("failed to save state on quit: %s", exc)
        if self.tray:
            self.tray.stop()
        self.hotkeys.stop()
        try:
            if self._watchdog_proc and self._watchdog_proc.poll() is None:
                self._watchdog_proc.terminate()
        except Exception:
            pass
        self.ui.destroy()

    # ---- threads ----
    def run(self):
        self._sync_autostart()
        self.tray = self._make_tray()
        self.enforcer = self._make_enforcer()
        self.tray.start()
        if not self.no_watchdog:
            self._spawn_watchdog()
        self._register_hotkeys()
        self._stop.clear()
        self._engine_thread = threading.Thread(
            target=self._engine_loop,
            daemon=True,
            name="engine",
        )
        self._engine_thread.start()
        self.ui.run()

    def _make_tray(self):
        from health_guard.tray import TrayController

        return TrayController(self, self.get_cfg)

    def _make_enforcer(self):
        from health_guard.enforcer import Enforcer

        return Enforcer(self.get_cfg, self.ui, music_player=self.music_player)

    def _spawn_watchdog(self):
        try:
            cmd = [
                sys.executable,
                "-m",
                "health_guard.watchdog",
                "--pid",
                str(os.getpid()),
            ]
            self._watchdog_proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT_DIR),
                creationflags=0x08000000,
            )
            log.info("watchdog spawned pid=%s", self._watchdog_proc.pid)
        except Exception as exc:
            log.error("failed to spawn watchdog: %s", exc)

    def _register_hotkeys(self):
        em = self.cfg.get("emergency", {})
        unlock = em.get("hotkey_unlock", ["ctrl", "alt", "shift", "u"])
        panic = em.get("hotkey_panic", ["ctrl", "alt", "shift", "x"])
        self.hotkeys.register(unlock, self.open_emergency)
        self.hotkeys.register(panic, self.enforcer.panic if self.enforcer else self.open_emergency)
        self.hotkeys.start()

    def _refresh_hotkeys(self):
        self.hotkeys.stop()
        self.hotkeys = HotkeyManager()
        self._register_hotkeys()

    def notify_tray(self, title, message):
        if self.tray:
            self.tray.notify(title, message)

    # ---- engine ----
    def _engine_loop(self):
        log.info("engine started")
        heartbeat_every = 0
        while not self._stop.is_set():
            try:
                if (
                    not self.safe_mode
                    and not self.state.paused
                    and self.cfg.get("enabled")
                ):
                    self._tick()
            except Exception as exc:
                log.exception("engine tick error: %s", exc)
            heartbeat_every += 1
            if heartbeat_every >= HEARTBEAT_EVERY_TICKS:
                heartbeat_every = 0
                self._write_heartbeat()
                self._check_watchdog()
            self._stop.wait(1)
        log.info("engine stopped")

    def _tick(self):
        now = datetime.datetime.now()
        mono = time.monotonic()
        if self._last_tick_mono is not None:
            gap = mono - self._last_tick_mono
            reset_gap = max(
                int(
                    self.cfg.get("safety", {}).get(
                        "idle_threshold_seconds", 120
                    )
                ),
                600,
            )
            if gap > reset_gap:
                log.info(
                    "long gap in monitoring (%.0fs), session timer reset",
                    gap,
                )
                self.state.reset_session()
        self._last_tick_mono = mono
        self.state.reset_if_new_day()
        idle = winapi.get_idle_seconds()
        idle_threshold = int(
            self.cfg.get("safety", {}).get("idle_threshold_seconds", 120)
        )
        active = idle < idle_threshold
        screen_on = winapi.is_display_on()
        self._update_screen_state(screen_on, mono)
        decision = rules.evaluate(self.cfg, self.state, now)
        if decision.allowed and active and screen_on:
            self.state.add_usage(1)
        self.enforcer.update(decision)

    def _update_screen_state(self, screen_on: bool, mono: float) -> None:
        """Pause the session clock while the display is off."""
        if self._last_screen_on == screen_on:
            return
        self._last_screen_on = screen_on
        if not screen_on:
            self._screen_off_mono = mono
            log.info("display off: usage counting paused")
            return
        off_seconds = mono - (
            self._screen_off_mono if self._screen_off_mono else mono
        )
        self._screen_off_mono = None
        if off_seconds > 1:
            self.state.advance_session_start(off_seconds)
            log.info(
                "display on: session clock advanced by %.0fs",
                off_seconds,
            )

    def _write_heartbeat(self):
        self._heartbeat_ts = time.time()
        try:
            atomic_write_json(
                HEARTBEAT_PATH,
                {"pid": os.getpid(), "ts": self._heartbeat_ts},
            )
        except Exception as exc:
            log.error("heartbeat write failed: %s", exc)

    def _check_watchdog(self):
        if self.no_watchdog:
            return
        if self._watchdog_proc is None or self._watchdog_proc.poll() is not None:
            self._spawn_watchdog()


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    setup_logging()

    if "--reset" in argv or "--disable-all" in argv:
        return reset_all()
    if "--status" in argv:
        return print_status()

    log.info("launching %s", APP_DISPLAY_NAME)

    safe_mode = "--safe-mode" in argv or "--disable" in argv
    no_watchdog = "--no-watchdog" in argv or safe_mode

    if "--safe-mode" in argv:
        log.warning("SAFE MODE: restrictions disabled on this run")

    if _single_instance_running() and "--allow-multiple" not in argv:
        log.error("another instance is already running")
        print(
            "已有一个健康管家实例在运行。若程序卡死,请先结束后台进程,"
            "或用 --safe-mode / --allow-multiple 启动。"
        )
        return 2

    cfg = load_config()
    if safe_mode:
        cfg = dict(cfg)
        cfg["enabled"] = False

    try:
        controller = Controller(cfg, safe_mode=safe_mode, no_watchdog=no_watchdog)

        if not cfg.get("setup_complete"):
            log.info("first run: opening setup wizard")
            controller.ui.open_setup()
        elif safe_mode:
            controller.ui.show_tray_message(
                APP_DISPLAY_NAME, "已以安全模式启动,限制未启用"
            )
        elif not cfg.get("enabled"):
            log.info("restrictions currently disabled")
        elif not config_has_password(cfg):
            log.warning("restrictions enabled but no emergency password set")
            controller.ui.show_tray_message(
                APP_DISPLAY_NAME,
                "未设置紧急密码,无法使用紧急解锁,建议尽快设置!",
            )

        controller.run()
    except Exception as exc:
        log.exception("fatal: %s", exc)
        raise
    finally:
        pass
    return 0


def reset_all() -> int:
    """关闭所有预设限制并清空用量计数,不启动界面。"""
    from health_guard.constants import CONFIG_PATH

    cfg = load_config()
    cfg["enabled"] = False
    cfg["schedule"]["allowed_windows"] = []
    cfg["schedule"]["blocked_windows"] = []
    cfg["strategy"]["primary_action"] = "none"
    cfg["strategy"]["block_apps"] = False
    cfg["strategy"]["blocked_apps"] = []
    try:
        save_config(cfg)
    except Exception as exc:
        log.error("reset: save config failed: %s", exc)
        print(f"写入配置失败: {exc}")
        return 1

    try:
        state = UsageState()
        state.daily_used_seconds = 0
        state.session_started_at = None
        state.break_started_at = None
        state.grants = []
        state.paused = False
        state._save()
        state_saved = True
    except Exception as exc:
        log.error("reset: save state failed: %s", exc)
        state_saved = False

    print("已关闭所有限制预设:")
    print("  enabled = False (限制总开关关闭)")
    print("  schedule  = 空 (所有时段预设已清除)")
    print("  strategy  = none (达到上限后不执行任何动作)")
    print("  block_apps = False (应用拦截关闭)")
    print(f"  用量计数  = 已清空 ({'state.json 保存成功' if state_saved else 'state.json 保存失败'})")
    print(f"  配置文件  = {CONFIG_PATH}")
    print("现在可以放心使用电脑,不会再被限制。")
    return 0


def print_status() -> int:
    """打印当前生效的限制状态,不启动界面。"""
    from health_guard.constants import CONFIG_PATH

    cfg = load_config()
    state = UsageState()
    now = datetime.datetime.now()
    decision = rules.evaluate(cfg, state, now)
    print("电脑使用健康管家 - 当前状态")
    print(f"  配置文件        = {CONFIG_PATH}")
    print(f"  限制总开关      = {'开启' if cfg.get('enabled') else '关闭'}")
    print(f"  限制模式        = {cfg.get('mode', 'duration')}")
    print(f"  上限动作        = {cfg.get('strategy', {}).get('primary_action', 'none')}")
    print(f"  应用拦截        = {cfg.get('strategy', {}).get('block_apps', False)}")
    print(f"  已设紧急密码    = {'是' if config_has_password(cfg) else '否'}")
    print(f"  今日已用        = {state.daily_used_seconds // 60} 分钟")
    print(f"  连续使用        = {state.session_seconds(now) // 60} 分钟")
    print(f"  当前判定        = {'允许使用' if decision.allowed else '受限'}")
    print(f"  原因            = {decision.reason}")
    print(f"  紧急放行        = {decision.grant_remaining_minutes} 分钟")
    return 0


def _single_instance_running() -> bool:
    import ctypes

    from health_guard.constants import MUTEX_NAME

    global _MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True
    err = kernel32.GetLastError()
    if err == 183:
        kernel32.CloseHandle(handle)
        return True
    _MUTEX_HANDLE = handle
    return False


_MUTEX_HANDLE = None


if __name__ == "__main__":
    sys.exit(main())