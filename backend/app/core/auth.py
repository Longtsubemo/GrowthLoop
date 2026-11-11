"""Owner sessions and password verification for the single-owner app."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

SESSION_COOKIE_NAME = "growthloop_session"
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
MAX_FAILED_LOGIN_KEYS = 2048


class InvalidOwnerPassword(Exception):
    """Raised when a login attempt does not match the owner password."""


class LoginRateLimited(Exception):
    """Raised after repeated failed login attempts from one client address."""


@dataclass(frozen=True, slots=True)
class OwnerSession:
    """Server-side owner session data; the cookie contains only its random id."""

    csrf_token: str
    expires_at: float


class OwnerAuthService:
    """Verify one configured owner password and manage opaque sessions."""

    def __init__(
        self,
        owner_password: str | None,
        *,
        session_ttl_seconds: int,
        secure_cookie: bool,
        allowed_origins: list[str],
    ) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )
        self._password_hash = (
            self._hasher.hash(owner_password) if owner_password is not None else None
        )
        self.session_ttl_seconds = session_ttl_seconds
        self.secure_cookie = secure_cookie
        self.allowed_origins = frozenset(allowed_origins)
        self._sessions: dict[str, OwnerSession] = {}
        self._failed_logins: dict[str, deque[float]] = {}
        self._lock = threading.RLock()

    @property
    def is_configured(self) -> bool:
        return self._password_hash is not None

    def login(self, password: str, client_key: str) -> tuple[str, OwnerSession]:
        """Check the password with Argon2id and issue a server-side session."""
        now = time.monotonic()
        with self._lock:
            cutoff = now - LOGIN_WINDOW_SECONDS
            for stale_key, stale_attempts in list(self._failed_logins.items()):
                while stale_attempts and stale_attempts[0] <= cutoff:
                    stale_attempts.popleft()
                if not stale_attempts:
                    self._failed_logins.pop(stale_key, None)
            attempts = self._failed_logins.get(client_key)
            if attempts is None:
                if len(self._failed_logins) >= MAX_FAILED_LOGIN_KEYS:
                    raise LoginRateLimited
                attempts = deque()
                self._failed_logins[client_key] = attempts
            if len(attempts) >= LOGIN_MAX_FAILURES:
                raise LoginRateLimited

            password_hash = self._password_hash
            valid = False
            if password_hash is not None:
                try:
                    valid = self._hasher.verify(password_hash, password)
                except (VerifyMismatchError, VerificationError, InvalidHashError):
                    valid = False

            if not valid:
                attempts.append(now)
                raise InvalidOwnerPassword

            self._failed_logins.pop(client_key, None)
            self._purge_expired_locked(now)
            session_id = secrets.token_urlsafe(32)
            session = OwnerSession(
                csrf_token=secrets.token_urlsafe(32),
                expires_at=now + self.session_ttl_seconds,
            )
            self._sessions[self._session_key(session_id)] = session
            return session_id, session

    def get_session(self, session_id: str | None) -> OwnerSession | None:
        """Load a live session using the opaque id from the HttpOnly cookie."""
        if not session_id:
            return None
        key = self._session_key(session_id)
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if session.expires_at <= now:
                self._sessions.pop(key, None)
                return None
            return session

    def logout(self, session_id: str | None) -> None:
        """Revoke a session immediately."""
        if session_id:
            with self._lock:
                self._sessions.pop(self._session_key(session_id), None)

    def verify_csrf(self, session: OwnerSession, supplied_token: str | None) -> bool:
        """Compare the synchronizer token without leaking match timing."""
        return bool(
            supplied_token
            and hmac.compare_digest(session.csrf_token, supplied_token)
        )

    def set_session_cookie(self, response, session_id: str) -> None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=self.session_ttl_seconds,
            path="/",
            secure=self.secure_cookie,
            httponly=True,
            samesite="lax",
        )

    def clear_session_cookie(self, response) -> None:
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path="/",
            secure=self.secure_cookie,
            httponly=True,
            samesite="lax",
        )

    @staticmethod
    def _session_key(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def _purge_expired_locked(self, now: float) -> None:
        for key, session in list(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(key, None)
