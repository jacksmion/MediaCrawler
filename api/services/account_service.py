from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from api.schemas.account import AccountCreateRequest, AccountResponse

BROWSER_DATA_DIR = Path(__file__).parent.parent.parent / "browser_data"
ACCOUNTS_FILE = BROWSER_DATA_DIR / "accounts.json"
_file_lock = threading.Lock()


def _load_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.exists():
        return []
    with _file_lock:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)


def _save_accounts(accounts: list[dict]) -> None:
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _file_lock:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)


def _generate_account_id(platform: str) -> str:
    short = uuid.uuid4().hex[:8]
    return f"{platform}_{short}"


def _enrich_status(account: dict) -> dict:
    """Add runtime status fields by checking profile directory."""
    account_id = account["account_id"]
    standard_dir = BROWSER_DATA_DIR / account_id
    cdp_dir = BROWSER_DATA_DIR / f"cdp_{account_id}"

    login_type = "none"
    last_active = None

    if standard_dir.exists():
        login_type = "standard"
        last_active = standard_dir.stat().st_mtime
    elif cdp_dir.exists():
        login_type = "cdp"
        last_active = cdp_dir.stat().st_mtime

    account["login_type"] = login_type
    account["last_active"] = last_active
    account["status"] = "active" if login_type != "none" else "unknown"
    return account


def list_accounts(platform: Optional[str] = None) -> list[AccountResponse]:
    accounts = _load_accounts()
    if platform:
        accounts = [a for a in accounts if a["platform"] == platform]
    result = []
    for a in accounts:
        enriched = _enrich_status(a.copy())
        result.append(AccountResponse(**enriched))
    return result


def create_account(req: AccountCreateRequest) -> AccountResponse:
    accounts = _load_accounts()
    account_id = _generate_account_id(req.platform)
    now = datetime.now(timezone.utc).isoformat()
    account = {
        "account_id": account_id,
        "name": req.name or account_id,
        "platform": req.platform,
        "remark": req.remark,
        "status": "unknown",
        "last_login_at": None,
        "created_at": now,
    }
    accounts.append(account)
    _save_accounts(accounts)
    enriched = _enrich_status(account.copy())
    return AccountResponse(**enriched)


def delete_account(account_id: str) -> bool:
    accounts = _load_accounts()
    target = next((a for a in accounts if a["account_id"] == account_id), None)
    if target is None:
        return False

    # Remove profile directories
    for d in [BROWSER_DATA_DIR / account_id, BROWSER_DATA_DIR / f"cdp_{account_id}"]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    accounts = [a for a in accounts if a["account_id"] != account_id]
    _save_accounts(accounts)
    return True


def get_account(account_id: str) -> Optional[AccountResponse]:
    accounts = _load_accounts()
    target = next((a for a in accounts if a["account_id"] == account_id), None)
    if target is None:
        return None
    enriched = _enrich_status(target.copy())
    return AccountResponse(**enriched)
