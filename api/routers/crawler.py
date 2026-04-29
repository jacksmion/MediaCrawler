# -*- coding: utf-8 -*-
# Legacy crawler router — bridges to the unified TaskManager.
# Kept for backwards compatibility; prefer /api/tasks/* for new code.

from fastapi import APIRouter, HTTPException

from ..schemas import CrawlerStartRequest, CrawlerStatusResponse
from ..services.task_manager import task_manager
from ..services.account_service import get_account

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start a crawler task via the legacy API. Bridges to TaskManager."""
    if request.account_id:
        account = get_account(request.account_id)
        if not account:
            raise HTTPException(status_code=404, detail=f"Account '{request.account_id}' not found.")

    from api.schemas.task import TaskCreateRequest
    task_req = TaskCreateRequest(
        name=f"{request.platform.value}_{request.crawler_type.value}",
        platform=request.platform.value,
        account_id=request.account_id,
        crawler_type=request.crawler_type.value,
        mode="once",
        keywords=request.keywords,
        specified_ids=request.specified_ids,
        creator_ids=request.creator_ids,
        sort_type=request.sort_type,
        enable_comments=request.enable_comments,
        enable_sub_comments=request.enable_sub_comments,
        comment_time_filter_h=request.comment_time_filter_h,
        headless=request.headless,
    )
    task_item = await task_manager.create_task(task_req)
    success = await task_manager.start_task(task_item.task_id)
    if not success:
        await task_manager.delete_task(task_item.task_id)
        raise HTTPException(status_code=400, detail="Failed to start crawler. Concurrent limit reached or same-account conflict.")
    return {"status": "ok", "message": "Crawler started", "task_id": task_item.task_id}


@router.post("/stop/{task_id}")
async def stop_crawler(task_id: str):
    """Stop a specific crawler task."""
    success = await task_manager.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Task {task_id} not found or not running.")
    return {"status": "ok", "message": f"Task {task_id} stopped"}


@router.get("/status", response_model=CrawlerStatusResponse)
async def get_crawler_status():
    """Get all crawler task statuses."""
    return task_manager.get_status()


@router.get("/logs/{task_id}")
async def get_logs(task_id: str, limit: int = 100):
    """Get recent logs for a specific task."""
    logs = task_manager.get_logs(task_id, limit)
    return {"logs": logs}
