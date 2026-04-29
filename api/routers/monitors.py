from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas.monitors import (
    MonitorItemCreateRequest,
    MonitorItemListResponse,
    MonitorItemResponse,
    MonitorItemUpdateRequest,
    MonitorLogListResponse,
)
from api.services.douyin_monitor_manager import monitor_manager
from api.services.task_manager import task_manager, MAX_CONCURRENT

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("", response_model=MonitorItemListResponse)
async def list_monitors():
    return {"items": monitor_manager.list_items()}


@router.post("", response_model=MonitorItemResponse)
async def create_monitor(request: MonitorItemCreateRequest):
    try:
        return await monitor_manager.create_item(
            content_url=request.content_url,
            refresh_interval_seconds=request.refresh_interval_seconds,
            title=request.title,
            author_short_id=request.author_short_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{monitor_item_id}", response_model=MonitorItemResponse)
async def update_monitor(monitor_item_id: str, request: MonitorItemUpdateRequest):
    try:
        return await monitor_manager.update_item(monitor_item_id, request.model_dump(exclude_unset=True))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Monitor item not found") from exc


@router.post("/{monitor_item_id}/start", response_model=MonitorItemResponse)
async def start_monitor(monitor_item_id: str):
    if task_manager.active_count >= MAX_CONCURRENT:
        raise HTTPException(status_code=409, detail="Concurrent task limit reached. Stop a running task first.")
    try:
        return await monitor_manager.start_item(monitor_item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Monitor item not found") from exc


@router.post("/{monitor_item_id}/stop", response_model=MonitorItemResponse)
async def stop_monitor(monitor_item_id: str):
    try:
        return await monitor_manager.stop_item(monitor_item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Monitor item not found") from exc


@router.get("/{monitor_item_id}/logs", response_model=MonitorLogListResponse)
async def list_monitor_logs(monitor_item_id: str, limit: int = Query(default=100, ge=1, le=500)):
    return {"items": monitor_manager.list_logs(monitor_item_id, limit=limit)}
