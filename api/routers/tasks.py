from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.task import TaskCreateRequest, TaskItemResponse, TaskListResponse
from api.services.task_manager import task_manager
from api.services.account_service import get_account

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
async def list_tasks():
    return TaskListResponse(tasks=task_manager.list_tasks())


@router.post("", response_model=TaskItemResponse)
async def create_task(req: TaskCreateRequest):
    if req.account_id:
        account = get_account(req.account_id)
        if not account:
            raise HTTPException(status_code=404, detail=f"Account '{req.account_id}' not found.")
    return await task_manager.create_task(req)


@router.get("/{task_id}", response_model=TaskItemResponse)
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    success = await task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok"}


@router.post("/{task_id}/start")
async def start_task(task_id: str):
    success = await task_manager.start_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start. Concurrent limit reached or same-account conflict.")
    return {"status": "ok", "message": "Task started"}


@router.post("/{task_id}/pause")
async def pause_task(task_id: str):
    success = await task_manager.pause_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not running or not a loop task.")
    return {"status": "ok", "message": "Task paused"}


@router.post("/{task_id}/stop")
async def stop_task(task_id: str):
    success = await task_manager.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not running.")
    return {"status": "ok", "message": "Task stopped"}


@router.get("/{task_id}/logs")
async def get_logs(task_id: str, limit: int = 100):
    return {"logs": task_manager.get_logs(task_id, limit)}


@router.get("/{task_id}/events")
async def get_events(task_id: str, limit: int = 100):
    from api.services import task_store
    return {"events": task_store.list_events(task_id, limit)}
