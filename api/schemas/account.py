from __future__ import annotations

from pydantic import BaseModel


class AccountCreateRequest(BaseModel):
    """Request to add a new account."""
    platform: str
    name: str = ""
    remark: str = ""


class AccountResponse(BaseModel):
    """Single account info."""
    account_id: str
    name: str
    platform: str
    remark: str
    status: str = "unknown"           # active / expired / unknown
    login_type: str = "none"          # standard / cdp / none
    last_login_at: str | None = None
    last_active: float | None = None  # directory mtime timestamp
    created_at: str


class AccountListResponse(BaseModel):
    """List of accounts."""
    accounts: list[AccountResponse]
