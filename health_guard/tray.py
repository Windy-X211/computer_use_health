import logging
import threading
from pathlib import Path

log = logging.getLogger("health_guard.tray")

try:
    import pystray
    from PIL import Image, ImageDraw

    _HAS_TRAY = True
except Exception as exc:  # pragma: no cover
    log.warning("pystray/Pillow unavailable: %s", exc)
    _HAS_TRAY = False


ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "app.ico"


def _fallback_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=(46, 109, 244, 255))
    draw.ellipse([16, 16, 48, 48], fill=(16, 20, 24, 255))
    draw.polygon(
        [(32, 22), (40, 34), (36, 42), (28, 42), (24, 34)],
        fill=(240, 192, 64, 255),
    )
    return img


def _make_icon_image() -> Image.Image:
    try:
        with Image.open(ICON_PATH) as im:
            img = im.convert("RGBA")
        return img.resize((64, 64), Image.LANCZOS)
    except Exception as exc:
        log.warning(
            "failed to load tray icon %s: %s; using fallback", ICON_PATH, exc
        )
        return _fallback_icon()


class TrayController:
    def __init__(self, controller, cfg_provider):
        self.controller = controller
        self._cfg_provider = cfg_provider
        self._icon = None
        self._thread = None

    def start(self) -> None:
        if not _HAS_TRAY:
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="tray"
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            self._icon = pystray.Icon(
                "health_guard",
                _make_icon_image(),
                "电脑使用健康管家",
                menu=self._build_menu(),
            )
            self._icon.run()
        except Exception as exc:
            log.error("tray failed: %s", exc)

    def _build_menu(self):
        from pystray import Menu, MenuItem

        def on_dashboard(icon, item):
            self.controller.open_dashboard()

        def on_settings(icon, item):
            self.controller.open_settings()

        def on_pause(icon, item):
            self.controller.toggle_pause()

        def on_resume(icon, item):
            self.controller.toggle_pause()

        def on_break_now(icon, item):
            self.controller.start_break_now()

        def on_setup(icon, item):
            self.controller.open_setup()

        def on_quit(icon, item):
            self.controller.quit_requested()

        return Menu(
            MenuItem("控制面板", on_dashboard, default=True),
            MenuItem("设置", on_settings),
            MenuItem("暂停限制", on_pause),
            MenuItem("恢复限制", on_resume),
            MenuItem("💤 开始休息", on_break_now),
            MenuItem("重新设置", on_setup),
            MenuItem("退出", on_quit),
        )

    def update_menu(self) -> None:
        if self._icon is not None:
            try:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
            except Exception:
                pass

    def notify(self, title: str, message: str) -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
