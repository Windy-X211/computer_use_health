import datetime
import logging
from dataclasses import dataclass
from typing import Optional

from health_guard.state import UsageState

log = logging.getLogger("health_guard.rules")


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    block_apps: bool = False
    action: str = "none"
    warning_seconds: int = 30
    next_change_ts: Optional[float] = None
    grant_remaining_minutes: int = 0
    in_break: bool = False
    # 时段限制时,下一次允许使用的时刻(datetime);非时段阻塞时为 None
    next_allowed_dt: Optional[datetime.datetime] = None


def _parse_time(hhmm: str, base: datetime.datetime) -> datetime.datetime:
    hh, mm = hhmm.split(":")
    return base.replace(
        hour=int(hh), minute=int(mm), second=0, microsecond=0
    )


def _in_window(now: datetime.datetime, window: dict) -> bool:
    try:
        days = window.get("days", list(range(7)))
        if now.weekday() not in days:
            return False
        start = _parse_time(window["start"], now)
        end = _parse_time(window["end"], now)
        if end <= start:
            end = end + datetime.timedelta(days=1)
            if start.time() == datetime.time(0, 0):
                start = start - datetime.timedelta(days=1)
        if start <= now <= end:
            return True
        return False
    except (KeyError, ValueError):
        log.warning("invalid schedule window: %s", window)
        return False


def _window_bounds(window: dict, base: datetime.datetime):
    """计算 window 以 base 所在日期为基准的一次 (start, end) 出现区间。"""
    start = _parse_time(window["start"], base)
    end = _parse_time(window["end"], base)
    if end <= start:
        end = end + datetime.timedelta(days=1)
        if start.time() == datetime.time(0, 0):
            start = start - datetime.timedelta(days=1)
    return start, end


def _next_allowed_time(sched: dict, now: datetime.datetime):
    """返回时段规则下的下一次允许使用时刻;无可用时段时返回 None。

    - 若配置了 allowed_windows,允许只在允许时段内使用,
      下一次允许 = 下一个允许窗口的开始时刻。
    - 若只在 blocked_windows 内,下一次允许 = 当前所在禁止窗口的结束时刻。
    两种情况取更早者,避免窗口交叉时漏算。
    """
    blocked = sched.get("blocked_windows", [])
    allowed = sched.get("allowed_windows", [])
    candidates: list[datetime.datetime] = []

    # 1) 当前正处于某个禁止窗口内 → 该窗口结束时刻
    for w in blocked:
        try:
            days = w.get("days", list(range(7)))
            if now.weekday() not in days:
                continue
            start, end = _window_bounds(w, now)
            if start <= now <= end:
                candidates.append(end)
        except (KeyError, ValueError):
            continue

    # 2) 下一个允许窗口的开始时刻(严格晚于 now)
    if allowed:
        for w in allowed:
            try:
                days = w.get("days", list(range(7)))
                for off in range(8):
                    day = now + datetime.timedelta(days=off)
                    if day.weekday() not in days:
                        continue
                    start = _parse_time(w["start"], day)
                    if start > now:
                        candidates.append(start)
                        break
            except (KeyError, ValueError):
                continue

    return min(candidates) if candidates else None


def evaluate(
    cfg: dict,
    state: UsageState,
    now: datetime.datetime | None = None,
) -> Decision:
    now = now or datetime.datetime.now()

    if not cfg.get("enabled"):
        decision = Decision(
            allowed=True,
            reason="限制未开启",
            block_apps=False,
            action="none",
            warning_seconds=int(
                cfg.get("strategy", {}).get("warning_seconds", 30)
            ),
        )
        return decision

    sched = cfg.get("schedule", {})
    dur = cfg.get("duration", {})
    strat = cfg.get("strategy", {})
    safety = cfg.get("safety", {})

    decision = Decision(
        allowed=True,
        reason="",
        block_apps=bool(strat.get("block_apps", False)),
        action=strat.get("primary_action", "none"),
        warning_seconds=int(strat.get("warning_seconds", 30)),
    )

    grant_minutes = state.active_grant_minutes(now)
    if grant_minutes > 0:
        decision.grant_remaining_minutes = grant_minutes
        decision.allowed = True
        decision.reason = f"紧急放行中（剩余 {grant_minutes} 分钟）"
        return decision

    mode = cfg.get("mode", "duration")
    blocked_by_schedule = False
    if mode in ("schedule", "both") and (
        sched.get("blocked_windows") or sched.get("allowed_windows")
    ):
        if any(
            _in_window(now, w) for w in sched.get("blocked_windows", [])
        ):
            blocked_by_schedule = True
            decision.reason = "当前处于禁止使用时段"
        elif sched.get("allowed_windows") and not any(
            _in_window(now, w) for w in sched.get("allowed_windows", [])
        ):
            blocked_by_schedule = True
            decision.reason = "当前不在允许使用时段"
        if blocked_by_schedule:
            decision.next_allowed_dt = _next_allowed_time(sched, now)

    blocked_by_duration = False
    if mode in ("duration", "both"):
        daily_limit = int(dur.get("daily_limit_minutes", 240)) * 60
        session_limit = int(dur.get("session_limit_minutes", 60)) * 60
        break_minutes = int(dur.get("break_minutes", 10))
        daily_used = state.daily_used_seconds

        # ---- Step 1: 独立管理 break 生命周期,不受 daily/schedule 阻塞影响 ----
        # 休息结束后必须清理 break_started_at,否则屏保不会关闭
        if state.break_started_at is not None:
            if break_minutes > 0:
                if state.break_elapsed_seconds(now) >= break_minutes * 60:
                    state.reset_session()
                else:
                    decision.in_break = True
            else:
                # break_minutes == 0:立即结束休息并清理
                state.reset_session()

        # ---- Step 2: 检查阻塞条件 ----
        if daily_used >= daily_limit:
            blocked_by_duration = True
            decision.reason = f"今日已达使用上限 {daily_limit // 60} 分钟"
        elif state.session_seconds(now) >= session_limit:
            blocked_by_duration = True
            decision.in_break = True
            decision.reason = (
                f"连续使用已达 {session_limit // 60} 分钟,需休息 "
                f"{break_minutes} 分钟"
            )
            if break_minutes > 0 and state.break_started_at is None:
                state.start_break(now)

    decision.allowed = not (blocked_by_schedule or blocked_by_duration)
    if decision.allowed and not decision.reason:
        decision.reason = "允许使用"
    if not decision.allowed and not decision.reason:
        decision.reason = "使用受限"
    if not decision.allowed:
        decision.action = strat.get("primary_action", "screensaver")
    if safety.get("fail_open", True) is False:
        log.debug("fail_open disabled")
    return decision
