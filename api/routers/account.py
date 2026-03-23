# -*- coding: utf-8 -*-
from fastapi import APIRouter
from pathlib import Path
import os

router = APIRouter(prefix="/account", tags=["account"])

# Browser data directory
BROWSER_DATA_DIR = Path(__file__).parent.parent.parent / "browser_data"

@router.get("/status")
async def get_account_status():
    """Get login status for all platforms by checking browser_data directory"""
    platforms = ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]
    status = []

    if not BROWSER_DATA_DIR.exists():
        return {"accounts": []}

    for platform in platforms:
        # Check standard user data dir
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
    from ..services.crawler_manager import crawler_manager
    from ..schemas.crawler import CrawlerStartRequest, PlatformEnum, CrawlerTypeEnum, SaveDataOptionEnum, LoginTypeEnum
    
    # Check if a task is already running
    status = crawler_manager.get_status()
    if status["status"] != "idle":
        return {"success": False, "message": f"Another task ({status['platform']}) is already running. Please stop it first."}

    # Map string platform to Enum
    platform_map = {
        "xhs": PlatformEnum.XHS,
        "dy": PlatformEnum.DOUYIN,
        "ks": PlatformEnum.KUAISHOU,
        "bili": PlatformEnum.BILIBILI,
        "wb": PlatformEnum.WEIBO,
        "tieba": PlatformEnum.TIEBA,
        "zhihu": PlatformEnum.ZHIHU,
    }
    
    if platform not in platform_map:
        return {"success": False, "message": f"Platform {platform} not supported yet for login via UI."}

    request = CrawlerStartRequest(
        platform=platform_map[platform],
        login_type=LoginTypeEnum.QRCODE,
        crawler_type=CrawlerTypeEnum.LOGIN,
        save_option=SaveDataOptionEnum.JSON,
        headless=False  # Must be false to show QR code
    )
    
    success = await crawler_manager.start(request)
    if success:
        return {"success": True, "message": f"Login process for {platform} started. Please check the popup browser window to scan QR code."}
    else:
        return {"success": False, "message": "Failed to start login process."}
