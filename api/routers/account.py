# -*- coding: utf-8 -*-
from fastapi import APIRouter
from pathlib import Path

from ..schemas.crawler import CrawlerStartRequest, PlatformEnum, CrawlerTypeEnum, SaveDataOptionEnum, LoginTypeEnum
from ..services.crawler_manager import crawler_manager

router = APIRouter(prefix="/account", tags=["account"])

BROWSER_DATA_DIR = Path(__file__).parent.parent.parent / "browser_data"
PLATFORM_CODES = [platform.value for platform in PlatformEnum]
PLATFORM_ENUM_MAP = {platform.value: platform for platform in PlatformEnum}

@router.get("/status")
async def get_account_status():
    """Get login status for all platforms by checking browser_data directory"""
    status = []

    if not BROWSER_DATA_DIR.exists():
        return {"accounts": []}

    for platform in PLATFORM_CODES:
        standard_dir = BROWSER_DATA_DIR / f"{platform}_user_data_dir"
        cdp_dir = BROWSER_DATA_DIR / f"cdp_{platform}_user_data_dir"
        
        is_logged_in = False
        login_type = "none"
        last_modified = 0

        if standard_dir.exists():
            is_logged_in = True
            login_type = "standard"
            last_modified = standard_dir.stat().st_mtime
        elif cdp_dir.exists():
            is_logged_in = True
            login_type = "cdp"
            last_modified = cdp_dir.stat().st_mtime

        status.append({
            "platform": platform,
            "is_logged_in": is_logged_in,
            "login_type": login_type,
            "last_active": last_modified if last_modified > 0 else None
        })

    return {"accounts": status}

@router.post("/login")
async def login_platform(platform: str):
    """Trigger login for a platform"""
    status = crawler_manager.get_status()
    if status["status"] != "idle":
        return {"success": False, "message": f"Another task ({status['platform']}) is already running. Please stop it first."}

    platform_enum = PLATFORM_ENUM_MAP.get(platform)
    if platform_enum is None:
        return {"success": False, "message": f"Platform {platform} not supported yet for login via UI."}

    request = CrawlerStartRequest(
        platform=platform_enum,
        login_type=LoginTypeEnum.QRCODE,
        crawler_type=CrawlerTypeEnum.LOGIN,
        save_option=SaveDataOptionEnum.JSON,
        headless=False,
    )

    success = await crawler_manager.start(request)
    if success:
        return {"success": True, "message": f"Login process for {platform} started. Please check the popup browser window to scan QR code."}
    else:
        return {"success": False, "message": "Failed to start login process."}
