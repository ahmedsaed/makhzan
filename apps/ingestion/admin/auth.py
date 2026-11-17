"""The admin dashboard's login: one password, a signed session cookie, CSRF, a login limit.

- **The password** is stored only as an scrypt hash, in `ADMIN_PASSWORD_HASH`
  (`./makhzan admin password` writes it into .env.prod). The format is
  `scrypt:N:r:p:<salt hex>:<hash hex>`: colons and hex only, so it survives
  .env files and Compose interpolation, which treat `$` specially. scrypt is
  in the standard library, so there is no dependency to keep up to date.
- **The session** is a cookie (`mk_admin`, HttpOnly, SameSite=Strict, Secure
  only when `ADMIN_COOKIE_SECURE` says the page is served over TLS: the
  tailnet link is WireGuard-encrypted but plain HTTP) holding an expiry, a
  CSRF token and a fingerprint of the password hash, signed with HMAC-SHA256
  under `ADMIN_SECRET`. Changing the password, or the secret, ends every
  session.
- **CSRF**: every POST carries the session's token in a `csrf` field, compared
  in constant time. The login form, before there is a session, carries a
  token from a short-lived signed cookie of its own (double submit).
- **The login limit**: `LoginLimiter`, per client address and in total, in the
  process (there is one).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import deque
from dataclasses import dataclass

#: scrypt cost: 2**17 * 8 * 128 bytes = 128 MiB of memory a check, about half a
#: second. The login limit (LoginLimiter) bounds how often anyone can make us pay it.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
#: The most memory a stored hash may ask a check for: a hash asking more is refused
#: with `HashUnusable`, not taken for a wrong password.
MAX_SCRYPT_MEMORY = 1024 * 1024 * 1024

SESSION_COOKIE = "mk_admin"
PRE_COOKIE = "mk_admin_pre"


class HashUnusable(ValueError):
    """The stored hash cannot be checked here (malformed, or costs more than allowed)."""


def _maxmem(n: int, r: int, p: int) -> int:
    """What OpenSSL needs for these parameters (128*r*(n+p) bytes), with room to spare."""
    return 128 * r * (n + p) + 16 * 1024 * 1024


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    """`scrypt:N:r:p:salt:hash` for `password`, with a fresh random salt."""
    if not password:
        raise ValueError("an empty password is not a password")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_maxmem(n, r, p), dklen=32
    )
    return f"scrypt:{n}:{r}:{p}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Whether `password` matches `stored`.

    False for an empty password or no hash. A hash that is malformed, or whose
    parameters cost more than `MAX_SCRYPT_MEMORY`, raises `HashUnusable`: that
    is a configuration problem to say so, never "wrong password". The memory
    limit is derived from the stored parameters, so raising SCRYPT_N later does
    not break hashes made with it.
    """
    if not stored or not password:
        return False
    try:
        scheme, n_text, r_text, p_text, salt, digest = stored.strip().split(":")
        n, r, p = int(n_text), int(r_text), int(p_text)
        salt_bytes, digest_bytes = bytes.fromhex(salt), bytes.fromhex(digest)
    except ValueError as exc:
        raise HashUnusable("ADMIN_PASSWORD_HASH is not an scrypt:N:r:p:salt:hash value") from exc
    if scheme != "scrypt":
        raise HashUnusable(f"ADMIN_PASSWORD_HASH uses {scheme!r}, not scrypt")
    if _maxmem(n, r, p) > MAX_SCRYPT_MEMORY:
        raise HashUnusable(f"ADMIN_PASSWORD_HASH asks for more memory than allowed (N={n}, r={r})")
    try:
        computed = hashlib.scrypt(
            password.encode(),
            salt=salt_bytes,
            n=n,
            r=r,
            p=p,
            maxmem=_maxmem(n, r, p),
            dklen=len(digest_bytes),
        )
    except ValueError as exc:
        raise HashUnusable(f"ADMIN_PASSWORD_HASH cannot be checked: {exc}") from exc
    return hmac.compare_digest(computed, digest_bytes)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def unsign(value: str | None, secret: str) -> dict | None:
    """The payload of a value `sign` made with `secret`, or None if it is not one."""
    if not value or "." not in value or not secret:
        return None
    body, mac = value.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def fingerprint(password_hash: str) -> str:
    """A short digest of the stored hash: a session made under another password is refused."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


@dataclass
class Session:
    csrf: str
    expires: int


def new_session(password_hash: str, secret: str, hours: float) -> tuple[str, Session]:
    session = Session(csrf=secrets.token_hex(16), expires=int(time.time() + hours * 3600))
    payload = {"exp": session.expires, "csrf": session.csrf, "pw": fingerprint(password_hash)}
    return sign(payload, secret), session


def read_session(
    value: str | None, password_hash: str | None, secret: str | None
) -> Session | None:
    """The session a cookie holds, if it is signed, unexpired and under the current password."""
    if not password_hash or not secret:
        return None
    payload = unsign(value, secret)
    if payload is None:
        return None
    if payload.get("pw") != fingerprint(password_hash):
        return None
    expires = payload.get("exp")
    if not isinstance(expires, int) or expires < time.time() or not payload.get("csrf"):
        return None
    return Session(csrf=str(payload["csrf"]), expires=expires)


def new_pre_token(secret: str) -> tuple[str, str]:
    """A login form's CSRF token and the signed cookie that vouches for it (10 minutes)."""
    token = secrets.token_hex(16)
    return token, sign({"pre": token, "exp": int(time.time()) + 600}, secret)


def read_pre_token(value: str | None, secret: str | None) -> str | None:
    payload = unsign(value, secret or "")
    if payload is None or not isinstance(payload.get("exp"), int) or payload["exp"] < time.time():
        return None
    return str(payload.get("pre") or "") or None


def tokens_match(given: str | None, expected: str | None) -> bool:
    return bool(given) and bool(expected) and hmac.compare_digest(str(given), str(expected))


class LoginLimiter:
    """Failed logins in a sliding window, per client address and over all of them.

    `PER_CLIENT` failures from one address, or `TOTAL` from everyone, within
    `WINDOW` seconds refuse further attempts until the oldest falls out of the
    window. A successful login clears that address's failures. In memory: the
    service is one process, and a restart forgetting failures is acceptable
    behind Tailscale.
    """

    PER_CLIENT = 5
    TOTAL = 20
    WINDOW = 15 * 60

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._by_client: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    def _trim(self, times: deque[float]) -> None:
        cutoff = self._clock() - self.WINDOW
        while times and times[0] < cutoff:
            times.popleft()

    def retry_after(self, client: str) -> int:
        """Seconds until `client` may try again; 0 if it may now."""
        mine = self._by_client.setdefault(client, deque())
        self._trim(mine)
        self._trim(self._all)
        waits = []
        if len(mine) >= self.PER_CLIENT:
            waits.append(mine[0] + self.WINDOW - self._clock())
        if len(self._all) >= self.TOTAL:
            waits.append(self._all[0] + self.WINDOW - self._clock())
        return max(1, int(max(waits)) + 1) if waits else 0

    def failed(self, client: str) -> None:
        now = self._clock()
        self._by_client.setdefault(client, deque()).append(now)
        self._all.append(now)

    def succeeded(self, client: str) -> None:
        self._by_client.pop(client, None)
