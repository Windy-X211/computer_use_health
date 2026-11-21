"""休息音乐播放器模块

仅支持洛雪音乐 Desktop 的 Open API 控制,以及本地 subprocess 方式启动洛雪进程。
Open API 文档: https://github.com/lyswhut/lx-music-desktop (Open API 章节)

休息音乐模式(仅这三种):
  - disabled: 不播放(不启动洛雪音乐,屏保不显示播放器)
  - manual:   手动播放(启动洛雪音乐,由用户在屏保中点击播放)
  - auto:     自动播放(启动洛雪音乐并自动开始播放)

启动前先检测 Open API 端口(默认 23330):端口已监听或进程已拉起则不重复启动。
"""

import json
import logging
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from health_guard.config import normalize_music_mode

log = logging.getLogger("health_guard.music")

DEFAULT_API_BASE = "http://127.0.0.1:23330"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class PlayerStatus:
    """播放器当前状态"""

    playing: bool = False
    name: str = ""
    singer: str = ""
    album: str = ""
    progress: float = 0.0  # 当前进度秒
    duration: float = 0.0  # 总时长秒
    current_lyric: str = ""  # 当前歌词
    next_lyric: str = ""  # 下一行歌词（即将播放）
    lyrics_lines: list[str] = field(default_factory=list)  # 从当前行开始的连续歌词行（用于滚动显示）


@dataclass
class LyricLine:
    """单行歌词"""

    time: float  # 秒
    text: str


# ---------------------------------------------------------------------------
# LRC 歌词解析
# ---------------------------------------------------------------------------


def parse_lrc(lrc_text: str) -> list[LyricLine]:
    """将 LRC 格式歌词文本解析为 LyricLine 列表（去重后按时间升序）。"""
    lines_dict = {}  # 用字典去重：{时间戳(text): (时间, 文本)}
    if not lrc_text:
        return []
    for raw in lrc_text.splitlines():
        if not raw.strip():
            continue
        # 匹配所有时间戳 [mm:ss.xxx] 一行可能多个时间戳(同一句多时间点)
        import re

        pattern = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?\]")
        matches = list(pattern.finditer(raw))
        if not matches:
            continue
        # 取最后一个时间戳后面的文本作为歌词
        text = raw[matches[-1].end():].strip()
        if not text:
            continue
        for m in matches:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            millis = int(m.group(3) or 0)
            t = minutes * 60 + seconds + millis / 1000.0
            time_key = f"{int(t):06d}.{int((t % 1) * 1000):03d}"  # 统一时间戳格式作为去重键
            # 如果同一时间戳出现多次，只保留第一次的文本
            if time_key not in lines_dict:
                lines_dict[time_key] = (t, text)
    # 按时间升序排序
    lines = sorted(lines_dict.values(), key=lambda x: x[0])
    return [LyricLine(time=t, text=text) for t, text in lines]


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------


def _http_get(url: str, timeout: float = 2.0) -> Optional[str]:
    """简单的 HTTP GET,返回响应文本;失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HealthGuard/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        log.debug("http GET %s failed: %s", url, exc)
        return None


def _http_post(url: str, timeout: float = 2.0) -> bool:
    """简单的 HTTP POST(空 body),成功返回 True。"""
    try:
        req = urllib.request.Request(url, method="POST", headers={"User-Agent": "HealthGuard/1.0"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        log.debug("http POST %s failed: %s", url, exc)
        return False


# ---------------------------------------------------------------------------
# 端口检测
# ---------------------------------------------------------------------------


def parse_api_endpoint(api_base: str, default_port: int = 23330) -> tuple[str, int]:
    """从 Open API 地址解析 (host, port),解析失败时回退 127.0.0.1:23330。"""
    try:
        parsed = urllib.parse.urlparse(api_base or DEFAULT_API_BASE)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or default_port
        return host, port
    except Exception:
        return "127.0.0.1", default_port


def is_port_open(api_base: str, timeout: float = 0.5) -> bool:
    """检测洛雪音乐 Open API 端口是否已监听。"""
    host, port = parse_api_endpoint(api_base)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 洛雪音乐 API 客户端
# ---------------------------------------------------------------------------


class LxMusicClient:
    """洛雪音乐 Desktop Open API 客户端。"""

    def __init__(self, api_base: str = DEFAULT_API_BASE, timeout: float = 2.0):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str, query: Optional[dict] = None) -> str:
        url = f"{self.api_base}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    # ---- 状态 ----
    def get_status(self) -> PlayerStatus:
        """获取当前播放状态。"""
        data = _http_get(self._url("/status"), timeout=self.timeout)
        if data is None:
            return PlayerStatus()
        try:
            j = json.loads(data)
        except json.JSONDecodeError:
            return PlayerStatus()
        status_str = str(j.get("status", "")).lower()
        return PlayerStatus(
            playing=status_str in ("playing",),
            name=str(j.get("name", "") or ""),
            singer=str(j.get("singer", "") or ""),
            album=str(j.get("albumName", "") or ""),
            progress=float(j.get("progress", 0) or 0),
            duration=float(j.get("duration", 0) or 0),
            current_lyric=str(j.get("lyricLineText", "") or ""),
            next_lyric="",  # LRC 轮询时会填充
        )

    def get_lyric(self) -> str:
        """获取原始 LRC 歌词文本。"""
        text = _http_get(self._url("/lyric"), timeout=self.timeout)
        return text or ""

    def get_all_lyrics(self) -> dict:
        """获取所有格式歌词(lrc/tlrc/rlrc/lxlrc)。"""
        data = _http_get(self._url("/lyric-all"), timeout=self.timeout)
        if data is None:
            return {}
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}

    # ---- 控制 ----
    def play(self) -> bool:
        return _http_post(self._url("/play"), timeout=self.timeout)

    def pause(self) -> bool:
        return _http_post(self._url("/pause"), timeout=self.timeout)

    def toggle(self) -> bool:
        st = self.get_status()
        if st.playing:
            return self.pause()
        return self.play()

    def next(self) -> bool:
        return _http_post(self._url("/skip-next"), timeout=self.timeout)

    def prev(self) -> bool:
        return _http_post(self._url("/skip-prev"), timeout=self.timeout)

    def set_volume(self, volume: int) -> bool:
        volume = max(0, min(100, int(volume)))
        return _http_post(self._url("/volume", {"volume": volume}), timeout=self.timeout)

    def set_mute(self, mute: bool) -> bool:
        return _http_post(self._url("/mute", {"mute": "true" if mute else "false"}), timeout=self.timeout)

    def is_available(self) -> bool:
        """测试 API 是否可达(端口已监听且 /status 有响应)。"""
        data = _http_get(self._url("/status"), timeout=self.timeout)
        return data is not None


# ---------------------------------------------------------------------------
# 音乐播放器 - 高层封装
# ---------------------------------------------------------------------------


class MusicPlayer:
    """统一的休息音乐播放器(仅支持洛雪音乐)。

    - mode == "disabled": 不启动洛雪,不播放
    - mode == "manual":   先检测端口,必要时启动洛雪,但不自动播放(由用户在屏保点击)
    - mode == "auto":     先检测端口,必要时启动洛雪并自动播放
    """

    def __init__(self, cfg_provider: Callable[[], dict]):
        self._cfg_provider = cfg_provider
        self._lx_client: Optional[LxMusicClient] = None
        self._player_proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._lyric_lines: list[LyricLine] = []
        self._current_lyric_idx: int = -1
        self._status_poll_thread: Optional[threading.Thread] = None
        self._stop_poll = threading.Event()
        self._on_status_change: Optional[Callable[[PlayerStatus], None]] = None
        self._last_status: Optional[PlayerStatus] = None

    # ---- 对外生命周期 ----
    def start_break_music(self) -> bool:
        """休息开始时调用:按模式启动洛雪音乐。返回是否成功触发。"""
        cfg = self._cfg_provider()
        music_cfg = cfg.get("music", {})
        mode = normalize_music_mode(music_cfg.get("mode"))
        if mode == "disabled":
            log.info("music mode=disabled, skip start_break_music")
            return False

        with self._lock:
            self._ensure_client()
            if self._lx_client is None:
                log.warning("music client unavailable, cannot start")
                return False

            # 启动前先检测端口:已监听说明洛雪在运行,不重复启动
            if is_port_open(self._lx_client.api_base):
                log.info("lx-music port already listening, skip launch")
            elif not self._ensure_player_running():
                log.warning("lx-music unavailable, cannot start music")
                return False

            # 自动播放才调用 play;手动播放留给用户在屏保中点击
            if mode == "auto":
                self._lx_client.play()

            self._start_polling()
            return True

    def stop_break_music(self) -> None:
        """休息结束时调用:暂停播放并停止轮询。"""
        with self._lock:
            self._stop_polling()
            cfg = self._cfg_provider()
            music_cfg = cfg.get("music", {})
            if not music_cfg.get("stop_on_break_end", True):
                return
            if self._lx_client is not None:
                try:
                    self._lx_client.pause()
                except Exception as exc:
                    log.debug("pause on break end failed: %s", exc)

    # ---- 外部控制按钮 ----
    def user_stop(self) -> bool:
         """用户点击「停止」按钮。"""
         with self._lock:
             if self._lx_client is None:
                 return False
             ok = self._lx_client.pause()
             # 强制刷新一次状态，确保 UI 立即更新
             if ok:
                 try:
                     # 获取最新状态以确保UI同步
                     fresh_status = self._lx_client.get_status()
                     self._on_status_change(fresh_status)
                 except Exception as exc:
                     log.debug("force status callback after user_stop: %s", exc)
             return ok

    def user_next(self) -> bool:
        """用户点击「下一首」按钮。"""""
        with self._lock:
            if self._lx_client is None:
                return False
            ok = self._lx_client.next()
            # 强制刷新一次状态，确保 UI 立即更新
            if ok:
                try:
                    # 获取最新状态以确保UI同步
                    fresh_status = self._lx_client.get_status()
                    self._on_status_change(fresh_status)
                except Exception as exc:
                    log.debug("force status callback after user_next: %s", exc)
            return ok

    def user_prev(self) -> bool:
        with self._lock:
            if self._lx_client is None:
                return False
            ok = self._lx_client.prev()
            # 强制刷新一次状态，确保 UI 立即更新
            if ok:
                try:
                    # 获取最新状态以确保UI同步
                    fresh_status = self._lx_client.get_status()
                    self._on_status_change(fresh_status)
                except Exception as exc:
                    log.debug("force status callback after user_prev: %s", exc)
            return ok

    def user_play(self) -> bool:
        """用户点击「播放」按钮。"""
        with self._lock:
            if self._lx_client is None:
                return False
            ok = self._lx_client.play()
            # 强制刷新一次状态，确保 UI 立即更新
            if ok:
                try:
                    # 获取最新状态以确保UI同步
                    fresh_status = self._lx_client.get_status()
                    self._on_status_change(fresh_status)
                except Exception as exc:
                    log.debug("force status callback after user_play: %s", exc)
            return ok

    # ---- 状态回调 ----
    def set_status_callback(self, cb: Optional[Callable[[PlayerStatus], None]]) -> None:
        self._on_status_change = cb

    def get_current_status(self) -> Optional[PlayerStatus]:
        return self._last_status

    # ---- 内部 ----
    def _ensure_client(self) -> None:
        cfg = self._cfg_provider()
        music_cfg = cfg.get("music", {})
        api_base = music_cfg.get("api_base") or DEFAULT_API_BASE
        if self._lx_client is None or self._lx_client.api_base != api_base:
            self._lx_client = LxMusicClient(api_base=api_base)

    def _ensure_player_running(self) -> bool:
        """确保洛雪音乐在运行并可被 API 控制(避免重复启动)。"""
        api_base = self._lx_client.api_base if self._lx_client else DEFAULT_API_BASE
        if is_port_open(api_base):
            return True
        # 本程序之前拉起的进程还活着 → 只等端口,不再启动第二个实例
        if self._player_proc is not None and self._player_proc.poll() is None:
            log.info(
                "lx-music already launched (pid=%s), waiting for port",
                self._player_proc.pid,
            )
            return self._wait_port_open(api_base)
        if not self._try_launch_player():
            return False
        return self._wait_port_open(api_base)

    def _wait_port_open(self, api_base: str, timeout: float = 15.0) -> bool:
        """等待洛雪 Open API 端口就绪。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_port_open(api_base):
                return True
            if self._player_proc is not None and self._player_proc.poll() is not None:
                log.warning(
                    "lx-music exited early (rc=%s)", self._player_proc.returncode
                )
                return False
            time.sleep(0.3)
        log.warning("lx-music port not open after %.0fs: %s", timeout, api_base)
        return False

    def _try_launch_player(self) -> bool:
        """启动洛雪音乐进程(已有存活进程时不重复启动)。"""
        if self._player_proc is not None and self._player_proc.poll() is None:
            log.info("music player already running (pid=%s)", self._player_proc.pid)
            return True
        cfg = self._cfg_provider()
        music_cfg = cfg.get("music", {})
        player_path = music_cfg.get("player_path", "")
        if not player_path:
            log.info("no player_path configured, skip launch")
            return False
        import os

        if not os.path.isfile(player_path):
            log.warning("player_path not found: %s", player_path)
            return False
        try:
            self._player_proc = subprocess.Popen(
                [player_path],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            log.info("launched music player: %s (pid=%s)", player_path, self._player_proc.pid)
            return True
        except Exception as exc:
            log.error("failed to launch player %s: %s", player_path, exc)
            return False

    # ---- 轮询 ----
    def _start_polling(self) -> None:
        if self._status_poll_thread and self._status_poll_thread.is_alive():
            return
        self._stop_poll.clear()
        self._status_poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="music-poll"
        )
        self._status_poll_thread.start()

    def _stop_polling(self) -> None:
        self._stop_poll.set()
        t = self._status_poll_thread
        if t is not None:
            t.join(timeout=2.0)
        self._status_poll_thread = None

    def _poll_loop(self) -> None:
        """定期拉取播放器状态,变化时通知回调。"""
        last_name = ""
        while not self._stop_poll.is_set():
            try:
                if self._lx_client is None:
                    break
                st = self._lx_client.get_status()

                # 歌曲变化时重新拉歌词
                if st.name != last_name:
                    last_name = st.name
                    raw = self._lx_client.get_lyric()
                    self._lyric_lines = parse_lrc(raw)
                    self._current_lyric_idx = -1

                # 根据 progress 找到当前行歌词
                if self._lyric_lines:
                    idx = -1
                    for i, line in enumerate(self._lyric_lines):
                        if line.time <= st.progress:
                            idx = i
                        else:
                            break
                    if idx != self._current_lyric_idx:
                        self._current_lyric_idx = idx
                        st.current_lyric = self._lyric_lines[idx].text if idx >= 0 else ""
                        # 下一行歌词是当前行索引 + 1
                        if idx + 1 < len(self._lyric_lines):
                            st.next_lyric = self._lyric_lines[idx + 1].text
                        else:
                            st.next_lyric = ""
                        # 填充 lyrics_lines：从当前行开始的连续 3 行（包括当前行）
                        start_idx = max(0, idx)
                        st.lyrics_lines = [
                            line.text for line in self._lyric_lines[start_idx : start_idx + 3]
                        ]
                    else:
                        # 即使行序没变，也要检查 whether 下一行更新
                        if idx + 1 < len(self._lyric_lines):
                            st.next_lyric = self._lyric_lines[idx + 1].text
                        else:
                            st.next_lyric = ""
                        # 更新 lyrics_lines（如果当前行变化了）
                        start_idx = max(0, idx)
                        st.lyrics_lines = [
                            line.text for line in self._lyric_lines[start_idx : start_idx + 3]
                        ]

                changed = (
                    self._last_status is None
                    or st.playing != self._last_status.playing
                    or st.name != self._last_status.name
                    or st.current_lyric != self._last_status.current_lyric
                    or abs(st.progress - self._last_status.progress) > 1.0
                )
                self._last_status = st
                if changed and self._on_status_change is not None:
                    try:
                        self._on_status_change(st)
                    except Exception:
                        log.exception("music status callback error")
            except Exception as exc:
                log.debug("music poll error: %s", exc)
            # 每 800ms 拉一次
            for _ in range(8):
                if self._stop_poll.is_set():
                    break
                time.sleep(0.1)
