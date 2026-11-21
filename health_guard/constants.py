import os
from pathlib import Path

APP_NAME = "HealthGuard"
APP_DISPLAY_NAME = "电脑使用健康管家"
APP_VERSION = "1.0.0"

ROOT_DIR = Path(__file__).resolve().parent.parent


def base_dir() -> Path:
    env = os.environ.get("HEALTHGUARD_HOME")
    if env:
        return Path(env).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / ("." + APP_NAME.lower())


BASE_DIR = base_dir()
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
HEARTBEAT_PATH = BASE_DIR / "heartbeat.json"
WATCHDOG_PATH = BASE_DIR / "watchdog.json"
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "healthguard.log"
BACKUP_DIR = BASE_DIR / "backups"
MUTEX_NAME = "Global\\HealthGuard.SingleInstance"

BACKUP_KEEP = 10

DEFAULT_CONFIG = {
    "version": 1,
    "enabled": False,
    "setup_complete": False,
    "auto_start": False,
    "mode": "duration",
    "duration": {
        "daily_limit_minutes": 240,
        "session_limit_minutes": 60,
        "break_minutes": 10,
    },
    "schedule": {
        "allowed_windows": [],
        "blocked_windows": [],
    },
    "strategy": {
        "primary_action": "screensaver",
        "block_apps": False,
        "blocked_apps": [],
        "warning_seconds": 30,
        "shutdown_ack": False,
    },
    "emergency": {
        "password_hash": "",
        "password_salt": "",
        "recovery_code_hash": "",
        "recovery_code_salt": "",
        "password_grant_minutes": 15,
        "grant_cooldown_minutes": 15,
        "hotkey_unlock": ["ctrl", "alt", "shift", "u"],
        "hotkey_panic": ["ctrl", "alt", "shift", "x"],
    },
    "gatekeeper": {
        "enabled": False,
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "timeout_seconds": 20,
        "default_grant_minutes": 15,
        "max_grant_minutes": 60,
        "temperature": 0.2,
    },
    "safety": {
        "fail_open": True,
        "idle_threshold_seconds": 120,
        "shutdown_requires_ack": True,
        "max_warning_seconds": 300,
    },
    "music": {
        # 休息音乐模式(仅支持洛雪音乐):
        #   "disabled"  - 不播放:不启动洛雪音乐,屏保不显示播放器
        #   "manual"    - 手动播放:启动洛雪音乐,由用户在屏保中点击播放
        #   "auto"      - 自动播放:启动洛雪音乐并自动开始播放
        "mode": "auto",
        # 洛雪音乐程序路径
        "player_path": r"F:\lx-music\lx-music-desktop\lx-music-desktop.exe",
        # 洛雪音乐 Open API 地址(需在洛雪设置中开启 Open API,默认端口 23330)
        "api_base": "http://127.0.0.1:23330",
        # 休息结束时自动停止播放
        "stop_on_break_end": True,
    },
    "session_overlay": {
        # 连续使用时间浮层
        "enabled": True,           # 是否启用浮层
        "opacity": 85,             # 可见度 0-100
        "scale": 100,              # 缩放比例 20-200(%),宽高按比例缩放
        "position": "top-right",   # 预设位置: top-right/top-left/bottom-right/bottom-left
        "pos_x": None,             # 手动定位 X 坐标(None 表示使用预设位置)
        "pos_y": None,             # 手动定位 Y 坐标
    },
}
