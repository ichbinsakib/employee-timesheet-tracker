"""Password hashing, sessions, login throttling and client classification.

* Passwords: scrypt (Python standard library), random salt, constant-time compare.
* Sessions: random 256-bit token in an HttpOnly, SameSite=Strict cookie; only a
  SHA-256 of the token is stored server-side, so a leaked database cannot be
  used to hijack sessions.
* Login throttling: 5 failures per IP per 15 minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import AuthSession, User, now

COOKIE_NAME = "ts_session"
ROLES = ("viewer", "manager", "admin")  # increasing privilege

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def validate_new_password(password: str) -> str | None:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Use upper- and lower-case letters and at least one number."
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        token_hash=_token_hash(token), user_id=user.id,
        expires_at=now() + timedelta(hours=settings.session_hours),
        ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300],
    ))
    user.last_login = now()
    # housekeeping
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    db.commit()
    return token


def session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if sess is None or sess.expires_at < now():
        return None
    user = db.get(User, sess.user_id)
    return user if user and user.active else None


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        db.commit()


def end_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def cookie_secure(request: Request) -> bool:
    mode = settings.cookie_secure
    if mode in ("1", "true", "yes"):
        return True
    if mode in ("0", "false", "no"):
        return False
    return is_https(request)


def is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    # Trust X-Forwarded-Proto only from a proxy on this machine (Tailscale Serve)
    direct = request.client.host if request.client else None
    return _is_loopback(direct) and request.headers.get("x-forwarded-proto", "").lower() == "https"


def has_role(user: User, minimum: str) -> bool:
    return ROLES.index(user.role if user.role in ROLES else "viewer") >= ROLES.index(minimum)


# --------------------------------------------------------------------------- client identification
def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _host_name(request: Request) -> str:
    host = (request.headers.get("host") or "").lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def is_proxied(request: Request) -> bool:
    """True when the request came through a local reverse proxy such as Tailscale Serve.

    A browser on the desktop itself addresses the app as localhost/127.0.0.1;
    Tailscale Serve forwards requests addressed to the machine's *.ts.net name
    and adds X-Forwarded-For / Tailscale-User-* headers.
    """
    h = request.headers
    if h.get("x-forwarded-for") or h.get("tailscale-user-login") or h.get("x-forwarded-host"):
        return True
    return _host_name(request) not in LOCAL_HOSTNAMES


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else None
    # Only trust X-Forwarded-For when the direct peer is this machine (i.e. our own proxy)
    if _is_loopback(direct) and request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return direct or "unknown"


def is_local_request(request: Request) -> bool:
    """A browser running on the desktop itself (not via Tailscale Serve)."""
    direct = request.client.host if request.client else None
    return _is_loopback(direct) and not is_proxied(request)


def access_channel(request: Request) -> str:
    if is_local_request(request):
        return "local"
    ip = client_ip(request)
    try:
        addr = ipaddress.ip_address(ip)
        if addr in ipaddress.ip_network("100.64.0.0/10") or (addr.version == 6 and ip.lower().startswith("fd7a:115c:a1e0")):
            return "tailscale"
    except ValueError:
        pass
    return "tailscale" if request.headers.get("tailscale-user-login") else "lan"


# --------------------------------------------------------------------------- throttling
class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_seconds: int = 900):
        self.max_failures, self.window = max_failures, window_seconds
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str) -> deque:
        q = self._fails[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key)) >= self.max_failures

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


throttle = LoginThrottle()
