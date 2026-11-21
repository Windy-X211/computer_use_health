import datetime
import logging
import shutil

from health_guard.constants import (
    BACKUP_DIR,
    BACKUP_KEEP,
    CONFIG_PATH,
    DEFAULT_CONFIG,
)
from health_guard.util import atomic_write_json, deep_merge, read_json

log = logging.getLogger("health_guard.config")


class ConfigError(Exception):
    pass


MUSIC_MODES = ("disabled", "manual", "auto")
# 旧版本遗留的模式值 -> 新模式
_LEGACY_MUSIC_MODES = {"ask": "auto", "external": "auto"}


def normalize_music_mode(mode) -> str:
    """把音乐模式归一化为 disabled/manual/auto(兼容旧值 ask/external)。"""
    mode = str(mode or "").strip()
    mode = _LEGACY_MUSIC_MODES.get(mode, mode)
    return mode if mode in MUSIC_MODES else "auto"


def backup_paths() -> list:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("config.json.bak.*"), reverse=True)


def _rotate_backups() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        dst = BACKUP_DIR / f"config.json.bak.{ts}"
        try:
            shutil.copy2(CONFIG_PATH, dst)
        except OSError:
            pass
    for old in backup_paths()[BACKUP_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def load_raw() -> dict:
    if CONFIG_PATH.exists():
        data = read_json(CONFIG_PATH)
        if isinstance(data, dict):
            return data
        log.error("config.json is corrupt, falling back to backups")
    for bak in backup_paths():
        data = read_json(bak)
        if isinstance(data, dict):
            log.warning("recovered config from backup %s", bak)
            return data
    return None


def validate_config(cfg: dict) -> list:
    errors = []
    if not isinstance(cfg.get("enabled"), bool):
        errors.append("enabled must be a boolean")
    if not isinstance(cfg.get("auto_start"), bool):
        errors.append("auto_start must be a boolean")
    mode = cfg.get("mode")
    if mode not in ("duration", "schedule", "both"):
        errors.append("mode must be duration/schedule/both")
    dur = cfg.get("duration", {})
    if not isinstance(dur.get("daily_limit_minutes"), int) or not (
        1 <= dur["daily_limit_minutes"] <= 24 * 60
    ):
        errors.append("daily_limit_minutes out of range")
    if not isinstance(dur.get("session_limit_minutes"), int) or not (
        1 <= dur["session_limit_minutes"] <= 24 * 60
    ):
        errors.append("session_limit_minutes out of range")
    if not isinstance(dur.get("break_minutes"), int) or not (
        0 <= dur["break_minutes"] <= 24 * 60
    ):
        errors.append("break_minutes out of range")
    action = cfg.get("strategy", {}).get("primary_action")
    if action not in ("none", "overlay", "screensaver", "lock", "logoff", "shutdown"):
        errors.append("invalid primary_action")
    ws = cfg.get("strategy", {}).get("warning_seconds", 0)
    if not isinstance(ws, int) or not (0 <= ws <= cfg.get("safety", {}).get(
        "max_warning_seconds", 300
    )):
        errors.append("warning_seconds out of range")
    return errors


def _normalize_music(cfg: dict) -> None:
    music = cfg.get("music")
    if isinstance(music, dict):
        music["mode"] = normalize_music_mode(music.get("mode"))


def load_config() -> dict:
    loaded = load_raw()
    cfg = deep_merge(DEFAULT_CONFIG, loaded or {})
    _normalize_music(cfg)
    errors = validate_config(cfg)
    if errors:
        log.warning("config validation errors: %s", errors)
        if loaded is None:
            log.error("no valid config found -> FAIL OPEN (restrictions disabled)")
            cfg = deep_merge(DEFAULT_CONFIG, {})
            cfg["enabled"] = False
        elif cfg.get("safety", {}).get("fail_open", True):
            log.warning("invalid config detected -> FAIL OPEN (restrictions disabled)")
            cfg["enabled"] = False
    return cfg


def masked_config(cfg: dict) -> dict:
    import copy

    masked = copy.deepcopy(cfg)
    key = masked.get("gatekeeper", {}).get("api_key", "")
    if key:
        masked["gatekeeper"]["api_key"] = "*" * 8
    return masked


def save_config(cfg: dict) -> None:
    _normalize_music(cfg)
    errors = validate_config(cfg)
    if errors:
        raise ConfigError("; ".join(errors))
    _rotate_backups()
    atomic_write_json(CONFIG_PATH, cfg)


def config_has_password(cfg: dict) -> bool:
    return bool(cfg.get("emergency", {}).get("password_hash"))
