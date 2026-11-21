import datetime
import logging
import math
import threading
import time

from health_guard.constants import STATE_PATH
from health_guard.util import atomic_write_json, read_json

log = logging.getLogger("health_guard.state")

STATE_SAVE_INTERVAL_SECONDS = 10.0


class UsageState:
    def __init__(self):
        self._lock = threading.RLock()
        self.date = datetime.date.today().isoformat()
        self.daily_used_seconds = 0
        self.session_started_at = None
        self.break_started_at = None
        self.last_activity_ts = None
        self.grants = []
        self.last_grant_ts = None
        self.last_grant_source = ""
        self.paused = False
        self._last_save_mono = time.monotonic()
        self._load()

    def _load(self) -> None:
        data = read_json(STATE_PATH, {}) or {}
        with self._lock:
            try:
                self.date = data.get("date", self.date)
                self.daily_used_seconds = int(
                    data.get("daily_used_seconds", 0)
                )
                self.session_started_at = data.get("session_started_at")
                self.break_started_at = data.get("break_started_at")
                self.last_activity_ts = data.get("last_activity_ts")
                self.grants = [
                    g
                    for g in data.get("grants", [])
                    if isinstance(g, dict) and g.get("until")
                ]
                self.last_grant_ts = data.get("last_grant_ts")
                self.last_grant_source = data.get("last_grant_source", "")
                self.paused = bool(data.get("paused", False))
            except Exception as exc:
                log.error("failed to load state: %s", exc)

    def reset_if_new_day(self) -> None:
        today = datetime.date.today().isoformat()
        with self._lock:
            if self.date != today:
                log.info("new day detected, resetting usage counters")
                self.date = today
                self.daily_used_seconds = 0
                self.session_started_at = None
                self.break_started_at = None
                self.grants = []
                self._save()

    def add_usage(self, seconds: int) -> None:
        with self._lock:
            if self.session_started_at is None:
                self.session_started_at = datetime.datetime.now().isoformat()
            self.daily_used_seconds += seconds
            if time.monotonic() - self._last_save_mono >= STATE_SAVE_INTERVAL_SECONDS:
                self._save()

    def session_seconds(self, now: datetime.datetime | None = None) -> int:
        with self._lock:
            if not self.session_started_at:
                return 0
            try:
                start = datetime.datetime.fromisoformat(
                    self.session_started_at
                )
            except ValueError:
                return 0
            now = now or datetime.datetime.now()
            return max(0, int((now - start).total_seconds()))

    def reset_session(self) -> None:
        with self._lock:
            self.session_started_at = datetime.datetime.now().isoformat()
            self.break_started_at = None
            self._save()

    def advance_session_start(self, seconds: float) -> None:
        """Shift the session clock forward so the given idle time is not
        counted as continuous usage (used while the screen is off)."""
        with self._lock:
            seconds = int(seconds)
            if not self.session_started_at or seconds <= 0:
                return
            try:
                start = datetime.datetime.fromisoformat(
                    self.session_started_at
                )
            except ValueError:
                return
            self.session_started_at = (
                start + datetime.timedelta(seconds=seconds)
            ).isoformat()
            self._save()

    def start_break(self, now: datetime.datetime | None = None) -> None:
        with self._lock:
            if self.break_started_at is None:
                now = now or datetime.datetime.now()
                self.break_started_at = now.isoformat()
                self._save()

    def break_elapsed_seconds(
        self, now: datetime.datetime | None = None
    ) -> int:
        with self._lock:
            if not self.break_started_at:
                return 0
            try:
                start = datetime.datetime.fromisoformat(
                    self.break_started_at
                )
            except ValueError:
                return 0
            now = now or datetime.datetime.now()
            return max(0, int((now - start).total_seconds()))

    def add_grant(
        self, minutes: int, source: str, reason: str = "", now=None
    ) -> datetime.datetime:
        now = now or datetime.datetime.now()
        until = now + datetime.timedelta(minutes=minutes)
        with self._lock:
            self.grants = [
                g for g in self.grants if g.get("until", 0) > now.timestamp()
            ]
            self.grants.append(
                {
                    "until": until.timestamp(),
                    "source": source,
                    "reason": reason[:200],
                    "granted_at": now.timestamp(),
                }
            )
            self.last_grant_ts = now.timestamp()
            self.last_grant_source = source
            self._save()
        return until

    def active_grant_minutes(self, now=None) -> int:
        now = now or datetime.datetime.now()
        with self._lock:
            self.grants = [
                g for g in self.grants if g.get("until", 0) > now.timestamp()
            ]
            best = 0
            for g in self.grants:
                remaining = max(0, math.ceil((g["until"] - now.timestamp()) / 60))
                best = max(best, remaining)
            return best

    def _save(self) -> None:
        with self._lock:
            self._last_save_mono = time.monotonic()
            data = {
                "date": self.date,
                "daily_used_seconds": self.daily_used_seconds,
                "session_started_at": self.session_started_at,
                "break_started_at": self.break_started_at,
                "last_activity_ts": self.last_activity_ts,
                "grants": self.grants,
                "last_grant_ts": self.last_grant_ts,
                "last_grant_source": self.last_grant_source,
                "paused": self.paused,
            }
            try:
                atomic_write_json(STATE_PATH, data)
            except OSError as exc:
                log.error("failed to persist state: %s", exc)
