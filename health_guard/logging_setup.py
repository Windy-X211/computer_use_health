import logging
import sys
from logging.handlers import RotatingFileHandler

from health_guard.constants import LOG_DIR, LOG_PATH
from health_guard.util import ensure_dir

_configured = False


def setup_logging() -> logging.Logger:
    global _configured
    logger = logging.getLogger("health_guard")
    if _configured:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    )
    try:
        ensure_dir(LOG_DIR)
        fh = RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    _configured = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("health_guard")
