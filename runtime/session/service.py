from __future__ import annotations

from datetime import datetime

from runtime.session.models import SessionState
from runtime.session.store import InMemorySessionStore


def _convert_cookies(cookies) -> tuple[str, dict[str, str]]:
    """Local cookie conversion keeps the new runtime import-light."""
    if not cookies:
        return "", {}
    cookie_pairs = []
    cookie_dict: dict[str, str] = {}
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if not name:
            continue
        cookie_pairs.append(f"{name}={value}")
        cookie_dict[name] = value
    return ";".join(cookie_pairs), cookie_dict


class SessionService:
    """Loads and updates session state for connectors and signers."""

    def __init__(self, platform_code: str, store: InMemorySessionStore | None = None) -> None:
        self.platform_code = platform_code
        self.store = store or InMemorySessionStore()

    def get(self) -> SessionState:
        """Return the current session or a default empty state."""
        return self.store.load() or SessionState(platform_code=self.platform_code)

    def save(self, session: SessionState) -> SessionState:
        """Persist the latest session snapshot."""
        return self.store.save(session)

    async def refresh_from_browser(
        self,
        browser_executor,
        *,
        account_id: str | None = None,
        proxy: str | None = None,
        session_id: str | None = None,
    ) -> SessionState:
        """Refresh session state from the currently bound browser runtime."""
        browser_state = await browser_executor.snapshot()
        _, cookie_dict = _convert_cookies(browser_state.cookies)
        session = SessionState(
            platform_code=self.platform_code,
            session_id=session_id,
            account_id=account_id,
            login_status=bool(cookie_dict.get("LOGIN_STATUS") == "1" or browser_state.local_storage.get("HasUserLogin") == "1"),
            user_agent=browser_state.user_agent,
            cookies=browser_state.cookies,
            cookie_dict=cookie_dict,
            local_storage=browser_state.local_storage,
            proxy=proxy,
            updated_at=datetime.utcnow(),
            metadata=browser_state.metadata.copy(),
        )
        return self.save(session)
