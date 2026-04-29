# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException

from ..schemas import CrawlerStartRequest, CrawlerStatusResponse
from ..services.crawler_manager import crawler_manager
from ..services.account_service import get_account

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start a crawler task. Returns task_id on success."""
    if request.account_id:
        account = get_account(request.account_id)
        if not account:
            raise HTTPException(status_code=404, detail=f"Account '{request.account_id}' not found.")
    task_id = await crawler_manager.start(request)
    if not task_id:
        raise HTTPException(status_code=400, detail="Failed to start crawler. Concurrent limit reached or same-account task already running.")
    return {"status": "ok", "message": "Crawler started", "task_id": task_id}


@router.post("/stop/{task_id}")
async def stop_crawler(task_id: str):
    """Stop a specific crawler task."""
    success = await crawler_manager.stop(task_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Task {task_id} not found or not running.")
    return {"status": "ok", "message": f"Task {task_id} stopped"}


@router.get("/status", response_model=CrawlerStatusResponse)
async def get_crawler_status():
    """Get all crawler task statuses."""
    return crawler_manager.get_status()


@router.get("/logs/{task_id}")
async def get_logs(task_id: str, limit: int = 100):
    """Get recent logs for a specific task."""
    logs = crawler_manager.get_logs(task_id, limit)
    return {"logs": logs}
