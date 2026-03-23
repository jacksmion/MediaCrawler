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
