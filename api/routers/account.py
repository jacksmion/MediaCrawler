# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException

from api.schemas.account import AccountCreateRequest, AccountListResponse, AccountResponse
from api.schemas.crawler import CrawlerStartRequest, CrawlerTypeEnum, LoginTypeEnum, SaveDataOptionEnum, PlatformEnum
from api.services.account_service import create_account, delete_account, get_account, list_accounts
from api.services.crawler_manager import crawler_manager

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/list", response_model=AccountListResponse)
async def get_accounts(platform: str = ""):
    """List all accounts, optionally filtered by platform."""
    accounts = list_accounts(platform or None)
    return AccountListResponse(accounts=accounts)


@router.post("/", response_model=AccountResponse)
async def add_account(req: AccountCreateRequest):
    """Create a new account entry."""
    valid_platforms = [p.value for p in PlatformEnum]
    if req.platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {req.platform}")
    return create_account(req)


@router.delete("/{account_id}")
async def remove_account(account_id: str):
    """Delete an account and its browser profile."""
    # Check if account has a running task
    if crawler_manager.is_running():
        for rt in crawler_manager._tasks.values():
            if rt.account_id == account_id and rt.status == "running":
                raise HTTPException(status_code=400, detail=f"Account has a running task ({rt.task_id}). Stop it first.")

    success = delete_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok", "message": f"Account {account_id} deleted"}


@router.post("/{account_id}/login")
async def login_account(account_id: str):
    """Launch browser for QR-code login for a specific account."""
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    platform_enum = None
    for p in PlatformEnum:
        if p.value == account.platform:
            platform_enum = p
            break
    if not platform_enum:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {account.platform}")

    request = CrawlerStartRequest(
        platform=platform_enum,
        login_type=LoginTypeEnum.QRCODE,
        crawler_type=CrawlerTypeEnum.LOGIN,
        save_option=SaveDataOptionEnum.JSONL,
        headless=False,
        account_id=account_id,
    )

    task_id = await crawler_manager.start(request)
    if not task_id:
        raise HTTPException(status_code=400, detail="Failed to start login. Concurrent limit reached or same-account task already running.")
    return {"success": True, "message": f"Login started for {account.name}. Check the browser window to scan QR code.", "task_id": task_id}


@router.get("/{account_id}/status", response_model=AccountResponse)
async def get_account_status(account_id: str):
    """Get login status for a specific account."""
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account
