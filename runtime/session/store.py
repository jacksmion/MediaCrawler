from __future__ import annotations

from runtime.session.models import SessionState


class InMemorySessionStore:
    """Simple store for early-stage migration before DB-backed persistence."""

    def __init__(self) -> None:
        self._session: SessionState | None = None

    def save(self, session: SessionState) -> SessionState:
        self._session = session
        return session

    def load(self) -> SessionState | None:
        return self._session

