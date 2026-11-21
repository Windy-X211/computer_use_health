import logging
import threading
import time

from health_guard import winapi
from health_guard.app_blocker import AppBlocker

log = logging.getLogger("health_guard.enforcer")


class Enforcer:
    def __init__(self, cfg_provider, ui, music_player=None):
        self._cfg_provider = cfg_provider
        self._ui = ui
        self._music_player = music_player
        self._lock = threading.RLock()
        self._blocked = False
        self._warning_start = None
        self._warning_seconds = 30
        self._action_applied = False
        self._toast_shown = False
        self._screensaver_shown = False
        self._overlay_shown = False
        self._blocker = AppBlocker(cfg_provider)
        self._last_reason = ""
        self._last_action = "none"
        self._last_break_minutes = 0
        self._manual_break_until = None
        self._last_in_break = False
        self._last_next_allowed_dt = None  # 时段限制时屏保展示的"下次可用时间"

    def update(self, decision) -> None:
        with self._lock:
            if decision.block_apps:
                self._blocker.set_enabled(True)
            else:
                self._blocker.set_enabled(False)

            if self._manual_break_until is not None:
                if time.time() >= self._manual_break_until:
                    self._manual_break_until = None
                    self._release()
                    log.info("manual break completed, restrictions released")
                return

            if decision.allowed:
                self._release()
                return

            # ---- 检测 break 刚结束但其他阻塞仍存在的情况 ----
            # 只在 in_break 从 True → False 的转变瞬间触发,避免无限循环
            # 释放屏保并让阻塞流程重新开始(警告倒计时 → 执行动作)
            if (
                self._screensaver_shown
                and not decision.in_break
                and self._last_in_break
            ):
                log.info(
                    "session break ended but block persists "
                    "(daily/schedule), releasing screensaver and restarting block flow"
                )
                self._screensaver_shown = False
                self._ui.hide_break_screensaver()
                # 重置阻塞流程,让 daily/schedule 阻塞重新弹出警告
                self._blocked = False
                self._action_applied = False
                self._warning_start = None
                self._toast_shown = False

            cfg = self._cfg_provider()
            self._warning_seconds = int(
                cfg.get("strategy", {}).get("warning_seconds", 30)
            )
            self._last_reason = decision.reason
            self._last_action = decision.action
            self._last_break_minutes = int(
                cfg.get("duration", {}).get("break_minutes", 10)
            )

            if not self._blocked:
                self._blocked = True
                self._warning_start = time.monotonic()
                self._action_applied = False
                self._toast_shown = True
                self._ui.show_toast(
                    self._last_reason,
                    self._warning_seconds,
                    grant_remaining=0,
                )
                log.warning(
                    "restriction activated: %s (action=%s)",
                    self._last_reason,
                    decision.action,
                )
            else:
                elapsed = time.monotonic() - self._warning_start
                remaining = max(0, int(self._warning_seconds - elapsed))
                if self._toast_shown:
                    self._ui.update_toast(
                        self._last_reason,
                        remaining,
                        grant_remaining=0,
                    )
                if elapsed >= self._warning_seconds and not self._action_applied:
                    self._hide_toast_if_shown()
                    self._apply_primary_action(decision)

            # 记录本轮 in_break 状态,供下一轮检测 True→False 转变
            self._last_in_break = decision.in_break

    def force_break(self, break_minutes, reason="主动休息") -> None:
        """主动休息:跳过警告倒计时,立即进入休息屏保。"""
        with self._lock:
            self._last_break_minutes = max(0, int(break_minutes))
            self._last_reason = reason
            self._last_action = "screensaver"
            self._last_next_allowed_dt = None  # 主动休息回到倒计时模式
            self._blocked = True
            self._warning_start = None
            self._action_applied = True
            self._hide_toast_if_shown()
            if self._last_break_minutes > 0:
                self._manual_break_until = (
                    time.time() + self._last_break_minutes * 60
                )
                self._screensaver_shown = True
                self._ui.show_break_screensaver(self._last_break_minutes)
                # 触发休息音乐
                if self._music_player is not None:
                    try:
                        self._music_player.start_break_music()
                    except Exception as exc:
                        log.warning("start break music failed: %s", exc)
            log.warning(
                "manual break started: %s minutes (%s)",
                self._last_break_minutes,
                reason,
            )

    def _hide_toast_if_shown(self) -> None:
        if self._toast_shown:
            self._toast_shown = False
            self._ui.hide_toast()

    def _apply_primary_action(self, decision) -> None:
        cfg = self._cfg_provider()
        strat = cfg.get("strategy", {})
        safety = cfg.get("safety", {})
        action = strat.get("primary_action", "screensaver")
        log.info("applying primary action: %s", action)
        self._action_applied = True

        if action == "none":
            return
        if action == "overlay":
            self._overlay_shown = True
            self._ui.show_overlay(
                self._last_reason,
                0,
                grant_remaining=0,
            )
            return
        if action == "screensaver":
            # 屏保的倒计时来自 state.break_elapsed_seconds()。
            if not decision.in_break:
                # 非 session 休息阻塞:
                if decision.next_allowed_dt is not None:
                    # 时段限制 → 屏保显示"下次可用时间",不显示倒计时
                    self._last_next_allowed_dt = decision.next_allowed_dt
                    self._screensaver_shown = True
                    self._ui.show_break_screensaver(
                        self._last_break_minutes,
                        next_allowed_dt=self._last_next_allowed_dt,
                    )
                else:
                    # 其他阻塞(如每日上限)→ 倒计时无意义,改用遮罩
                    self._last_action = "overlay"
                    self._last_next_allowed_dt = None
                    self._overlay_shown = True
                    self._ui.show_overlay(
                        self._last_reason,
                        0,
                        grant_remaining=0,
                    )
                return
            # 正常休息:弹出自定义休息屏保,显示休息倒计时(而不是真的系统屏保)
            self._last_next_allowed_dt = None
            self._screensaver_shown = True
            self._ui.show_break_screensaver(self._last_break_minutes)
            # 触发休息音乐
            if self._music_player is not None:
                try:
                    self._music_player.start_break_music()
                except Exception as exc:
                    log.warning("start break music failed: %s", exc)
            return
        if action == "lock":
            try:
                winapi.lock_workstation()
            except Exception as exc:
                log.error("lock failed: %s", exc)
            return
        if action == "logoff":
            if safety.get("shutdown_requires_ack", True) and not strat.get(
                "shutdown_ack", False
            ):
                log.error("logoff skipped: no user acknowledgement")
                return
            try:
                winapi.logoff_computer()
            except Exception as exc:
                log.error("logoff failed: %s", exc)
            return
        if action == "shutdown":
            if safety.get("shutdown_requires_ack", True) and not strat.get(
                "shutdown_ack", False
            ):
                log.error("shutdown skipped: no user acknowledgement")
                return
            try:
                winapi.shutdown_computer(
                    "HealthGuard 使用时间限制,即将关机。可用快捷键取消。"
                )
            except Exception as exc:
                log.error("shutdown failed: %s", exc)
            return

    def panic(self) -> None:
        with self._lock:
            winapi.abort_shutdown()
            self._release()
            self._ui.show_emergency()
            log.info("panic: all restrictions released")

    def _release(self) -> None:
        self._blocked = False
        self._warning_start = None
        self._action_applied = False
        self._manual_break_until = None
        if self._toast_shown:
            self._toast_shown = False
            self._ui.hide_toast()
        if self._screensaver_shown:
            self._screensaver_shown = False
            self._ui.hide_break_screensaver()
            # 屏保释放时停止音乐
            if self._music_player is not None:
                try:
                    self._music_player.stop_break_music()
                except Exception as exc:
                    log.warning("stop break music failed: %s", exc)
        if self._overlay_shown:
            self._overlay_shown = False
            self._ui.hide_overlay()

    def refresh_overlay(self) -> None:
        """紧急解锁面板关闭后重新显示对应界面。"""
        with self._lock:
            if not self._blocked:
                return
            if self._action_applied:
                # 已执行动作 → 按动作类型恢复
                action = self._last_action
                if action == "screensaver" and not self._screensaver_shown:
                    self._screensaver_shown = True
                    self._ui.show_break_screensaver(
                        self._last_break_minutes,
                        next_allowed_dt=self._last_next_allowed_dt,
                    )
                elif action == "overlay" and not self._overlay_shown:
                    self._overlay_shown = True
                    self._ui.show_overlay(
                        self._last_reason, 0, grant_remaining=0
                    )
            else:
                # 还在倒计时阶段 → 恢复 Toast
                if not self._toast_shown:
                    self._toast_shown = True
                    self._ui.show_toast(
                        self._last_reason,
                        self._warning_seconds,
                        grant_remaining=0,
                    )

    def release(self) -> None:
        with self._lock:
            self._release()

    @property
    def is_blocked(self) -> bool:
        with self._lock:
            return self._blocked
