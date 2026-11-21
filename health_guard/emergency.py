import datetime
import hashlib
import logging
import secrets

from health_guard.state import UsageState

log = logging.getLogger("health_guard.emergency")

_PBKDF2_ITERATIONS = 200_000


def _hash_password(password: str, salt_hex: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        _PBKDF2_ITERATIONS,
    )
    return dk.hex()


def set_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    return _hash_password(password, salt), salt


def verify_password(password: str, expected_hash: str, salt_hex: str) -> bool:
    if not password or not expected_hash or not salt_hex:
        return False
    candidate = _hash_password(password, salt_hex)
    return secrets.compare_digest(candidate, expected_hash)


def generate_recovery_code() -> tuple[str, str, str]:
    code = f"HG-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    salt = secrets.token_hex(16)
    return code, _hash_password(code, salt), salt


def check_password(cfg: dict, password: str) -> bool:
    em = cfg.get("emergency", {})
    return verify_password(
        password, em.get("password_hash", ""), em.get("password_salt", "")
    )


def check_recovery_code(cfg: dict, code: str) -> bool:
    em = cfg.get("emergency", {})
    return verify_password(
        code, em.get("recovery_code_hash", ""), em.get("recovery_code_salt", "")
    )


def cooldown_remaining_seconds(cfg: dict, state: UsageState, now=None) -> int:
    now = now or datetime.datetime.now()
    cooldown_minutes = int(cfg.get("emergency", {}).get("grant_cooldown_minutes", 15))
    if cooldown_minutes <= 0:
        return 0
    last = state.last_grant_ts
    if not last:
        return 0
    elapsed = now.timestamp() - last
    remaining = cooldown_minutes * 60 - elapsed
    return max(0, int(remaining))


def grant(cfg: dict, state: UsageState, minutes: int, source: str, reason: str = ""):
    until = state.add_grant(minutes, source, reason)
    log.info(
        "emergency grant: source=%s minutes=%s reason=%s until=%s",
        source,
        minutes,
        reason,
        until,
    )
    return until
