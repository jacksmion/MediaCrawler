from __future__ import annotations

from runtime.session.models import SessionState


class InMemorySessionStore:
    """Per-account session store backed by an in-memory dict."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def save(self, session: SessionState) -> SessionState:
        key = session.account_id or session.platform_code
        self._sessions[key] = session
        return session

    def load(self, account_id: str = "", platform_code: str = "") -> SessionState | None:
        key = account_id or platform_code
        return self._sessions.get(key)

    def load_all(self) -> list[SessionState]:
        return list(self._sessions.values())
