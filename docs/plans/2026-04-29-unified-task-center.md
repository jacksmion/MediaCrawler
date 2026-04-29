# Unified Task Center Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify TaskPanel (采集工场) and MonitorConsole (监控台) into a single TaskCenter with a two-column layout (task list + comment list), comment detail drawer, and a unified TaskManager backend.

**Architecture:** Replace CrawlerManager + DouyinMonitorManager with a single TaskManager that handles both one-shot and recurring tasks. Tasks are persisted via JSONL. Frontend merges into one TaskCenter component with left task list and right comment panel.

**Tech Stack:** Python/FastAPI (backend), React/Tailwind (frontend), JSONL (task persistence), Playwright (crawler).

---

### Task 1: Task Schemas

**Files:**
- Create: `api/schemas/task.py`
- Modify: `api/schemas/__init__.py`

**Step 1: Create task schemas**

Create `api/schemas/task.py`:

```python
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, Any


class TaskCreateRequest(BaseModel):
    """Request to create a new task."""
    name: str = ""
    platform: str  # dy, xhs, ks, bili, wb, tieba, zhihu
    account_id: str = ""
    crawler_type: str  # search, detail, creator
    mode: str = "once"  # once or loop
    loop_interval_seconds: int = 60  # minimum 5
    # Crawl config fields
    keywords: str = ""
    specified_ids: str = ""
    creator_ids: str = ""
    sort_type: str = ""
    enable_comments: bool = True
    enable_sub_comments: bool = False
    comment_time_filter_h: int = 0
    headless: bool = True


class TaskItemResponse(BaseModel):
    """Single task item."""
    task_id: str
    name: str
    platform: str
    account_id: str
    crawler_type: str
    mode: str  # once / loop
    status: str  # idle / running / paused / completed / error
    config: dict[str, Any] = {}
    loop_interval_seconds: int = 60
    created_at: str = ""
    last_run_at: str | None = None
    last_run_status: str | None = None
    comment_count: int = 0
    error_message: str | None = None


class TaskListResponse(BaseModel):
    """List of tasks."""
    tasks: list[TaskItemResponse]
```

**Step 2: Update `api/schemas/__init__.py`**

Add import and export for `TaskCreateRequest`, `TaskItemResponse`, `TaskListResponse` from `.task`.

**Step 3: Commit**

```bash
git add api/schemas/task.py api/schemas/__init__.py
git commit -m "feat: add unified task schemas"
```

---

### Task 2: TaskStore — JSONL Persistence

**Files:**
- Create: `api/services/task_store.py`

**Step 1: Create TaskStore**

Create `api/services/task_store.py` — a JSONL-based persistence layer modeled on the existing `MonitorStore` pattern:

```python
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "tasks"
ITEMS_FILE = DATA_DIR / "items.jsonl"
EVENTS_FILE = DATA_DIR / "events.jsonl"
_file_lock = threading.Lock()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with _file_lock:
        results = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return results


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _latest_snapshots(rows: list[dict], key: str = "task_id") -> dict[str, dict]:
    """Keep only the last row per key."""
    snapshots = {}
    for row in rows:
        k = row.get(key)
        if k:
            snapshots[k] = row
    return snapshots


def list_tasks() -> list[dict]:
    rows = _read_jsonl(ITEMS_FILE)
    snapshots = _latest_snapshots(rows)
    # Filter out deleted tasks
    return [v for v in snapshots.values() if v.get("deleted") is not True]


def get_task(task_id: str) -> Optional[dict]:
    rows = _read_jsonl(ITEMS_FILE)
    snapshots = _latest_snapshots(rows)
    item = snapshots.get(task_id)
    if item and item.get("deleted") is not True:
        return item
    return None


def create_task(fields: dict) -> dict:
    task_id = f"task_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "task_id": task_id,
        "status": "idle",
        "created_at": now,
        "last_run_at": None,
        "last_run_status": None,
        "comment_count": 0,
        "error_message": None,
        **fields,
    }
    _append_jsonl(ITEMS_FILE, item)
    append_event(task_id, "info", f"Task created: {fields.get('name', task_id)}")
    return item


def update_task(task_id: str, updates: dict) -> Optional[dict]:
    current = get_task(task_id)
    if not current:
        return None
    merged = {**current, **{k: v for k, v in updates.items() if v is not None}, "task_id": task_id}
    _append_jsonl(ITEMS_FILE, merged)
    return merged


def delete_task(task_id: str) -> bool:
    current = get_task(task_id)
    if not current:
        return False
    _append_jsonl(ITEMS_FILE, {**current, "deleted": True})
    append_event(task_id, "info", "Task deleted")
    return True


def append_event(task_id: str, level: str, message: str) -> None:
    event = {
        "event_id": uuid.uuid4().hex[:16],
        "task_id": task_id,
        "level": level,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _append_jsonl(EVENTS_FILE, event)


def list_events(task_id: str, limit: int = 100) -> list[dict]:
    rows = _read_jsonl(EVENTS_FILE)
    events = [r for r in rows if r.get("task_id") == task_id]
    return events[-limit:] if limit > 0 else events
```

**Step 2: Commit**

```bash
git add api/services/task_store.py
git commit -m "feat: add TaskStore with JSONL persistence"
```

---

### Task 3: TaskManager — Unified Scheduler

**Files:**
- Create: `api/services/task_manager.py`

**Step 1: Create TaskManager**

Create `api/services/task_manager.py`. This replaces `CrawlerManager` and `DouyinMonitorManager`:

```python
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from application.services.crawler_runtime import CrawlerFactory, cleanup_runtime
from application.services.requirement_mapper import (
    apply_runtime_request_overrides,
    build_requirement_from_request_payload,
)
from api.services import task_store
from api.services.crawler_log_service import CrawlerLogService
from api.schemas.task import TaskCreateRequest, TaskItemResponse

MAX_CONCURRENT = 3


@dataclass(slots=True)
class TaskRuntime:
    task_id: str
    account_id: str
    platform: str
    crawler_type: str
    mode: str
    handle: Optional[asyncio.Task] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    loop_interval: int = 60


class ApiLogHandler(logging.Handler):
    def __init__(self, log_service: CrawlerLogService, task_id: str) -> None:
        super().__init__(level=logging.INFO)
        self.log_service = log_service
        self.task_id = task_id
        self.setFormatter(logging.Formatter(f"[{task_id}] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        message = self.format(record)
        level = self.log_service.parse_level(record.levelname)
        entry = self.log_service.create_entry(message, level)
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.log_service.push(entry), loop=loop))


class TaskManager:
    """Unified task scheduler for both one-shot and recurring crawl tasks."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._runtimes: dict[str, TaskRuntime] = {}
        self._log_services: dict[str, CrawlerLogService] = {}

    # --- Public API ---

    def list_tasks(self) -> list[TaskItemResponse]:
        items = task_store.list_tasks()
        result = []
        for item in items:
            rt = self._runtimes.get(item.get("task_id", ""))
            if rt and rt.status in ("running",):
                item["status"] = "running"
            result.append(TaskItemResponse(**item))
        return result

    def get_task(self, task_id: str) -> Optional[TaskItemResponse]:
        item = task_store.get_task(task_id)
        if not item:
            return None
        rt = self._runtimes.get(task_id)
        if rt and rt.status == "running":
            item["status"] = "running"
        return TaskItemResponse(**item)

    async def create_task(self, req: TaskCreateRequest) -> TaskItemResponse:
        fields = {
            "name": req.name or f"{req.platform}_{req.crawler_type}",
            "platform": req.platform,
            "account_id": req.account_id,
            "crawler_type": req.crawler_type,
            "mode": req.mode,
            "loop_interval_seconds": max(req.loop_interval_seconds, 5),
            "config": {
                "keywords": req.keywords,
                "specified_ids": req.specified_ids,
                "creator_ids": req.creator_ids,
                "sort_type": req.sort_type,
                "enable_comments": req.enable_comments,
                "enable_sub_comments": req.enable_sub_comments,
                "comment_time_filter_h": req.comment_time_filter_h,
                "headless": req.headless,
            },
        }
        item = task_store.create_task(fields)
        return TaskItemResponse(**item)

    async def start_task(self, task_id: str) -> bool:
        async with self._lock:
            item = task_store.get_task(task_id)
            if not item:
                return False

            # Check concurrent limit
            running = [rt for rt in self._runtimes.values() if rt.status == "running"]
            if len(running) >= MAX_CONCURRENT:
                return False

            account_id = item.get("account_id", "")
            # Check same-account conflict
            if account_id and any(rt.account_id == account_id and rt.status == "running" for rt in running):
                return False

            rt = TaskRuntime(
                task_id=task_id,
                account_id=account_id,
                platform=item["platform"],
                crawler_type=item["crawler_type"],
                mode=item.get("mode", "once"),
                status="running",
                started_at=datetime.now(),
                loop_interval=item.get("loop_interval_seconds", 60),
            )

            log_service = CrawlerLogService()
            self._log_services[task_id] = log_service

            rt.handle = asyncio.create_task(self._run(rt, item))
            self._runtimes[task_id] = rt

            task_store.update_task(task_id, {"status": "running"})
            task_store.append_event(task_id, "info", "Task started")
            return True

    async def pause_task(self, task_id: str) -> bool:
        """Pause a loop task (cancel the asyncio task but keep the TaskItem)."""
        async with self._lock:
            rt = self._runtimes.get(task_id)
            if not rt or rt.status != "running":
                return False
            if rt.mode != "loop":
                return False

            rt.status = "paused"
            if isinstance(rt.handle, asyncio.Task):
                rt.handle.cancel()

            task_store.update_task(task_id, {"status": "paused"})
            task_store.append_event(task_id, "info", "Task paused")
            return True

    async def stop_task(self, task_id: str) -> bool:
        """Stop a running task."""
        handle = None
        log_service = None
        async with self._lock:
            rt = self._runtimes.get(task_id)
            if not rt or rt.status != "running":
                return False

            rt.status = "stopping"
            log_service = self._log_services.get(task_id)
            handle = rt.handle
            if isinstance(handle, asyncio.Task):
                handle.cancel()

        # Wait outside lock
        if isinstance(handle, asyncio.Task):
            try:
                await asyncio.wait_for(handle, timeout=15.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        async with self._lock:
            rt = self._runtimes.get(task_id)
            if rt:
                rt.status = "idle"
                rt.handle = None

        task_store.update_task(task_id, {"status": "idle"})
        task_store.append_event(task_id, "info", "Task stopped")
        return True

    async def delete_task(self, task_id: str) -> bool:
        # Stop if running
        rt = self._runtimes.get(task_id)
        if rt and rt.status == "running":
            await self.stop_task(task_id)

        self._runtimes.pop(task_id, None)
        self._log_services.pop(task_id, None)
        return task_store.delete_task(task_id)

    # --- Log & Status ---

    def get_log_queue(self) -> asyncio.Queue:
        for log_service in self._log_services.values():
            return log_service.get_log_queue()
        return CrawlerLogService().get_log_queue()

    def get_logs(self, task_id: str, limit: int = 100) -> list[dict]:
        log_service = self._log_services.get(task_id)
        if not log_service:
            return []
        return [log.model_dump() for log in log_service.logs[-limit:]]

    def get_status(self) -> dict:
        # Cleanup stale runtimes
        stale = [tid for tid, rt in self._runtimes.items() if rt.status in ("idle", "paused", "completed", "error")]
        if len(stale) > 10:
            for tid in stale[:-10]:
                self._runtimes.pop(tid, None)
                self._log_services.pop(tid, None)

        tasks = []
        for tid, rt in self._runtimes.items():
            if rt.status in ("running", "stopping"):
                tasks.append({
                    "task_id": tid,
                    "account_id": rt.account_id,
                    "platform": rt.platform,
                    "crawler_type": rt.crawler_type,
                    "status": rt.status,
                    "started_at": rt.started_at.isoformat() if rt.started_at else None,
                })
        return {"tasks": tasks, "active_count": len([t for t in tasks if t["status"] == "running"])}

    @property
    def logs(self) -> list:
        for log_service in self._log_services.values():
            return log_service.logs
        return []

    def is_running(self, task_id: str | None = None) -> bool:
        if task_id:
            rt = self._runtimes.get(task_id)
            return rt is not None and rt.status == "running"
        return any(rt.status == "running" for rt in self._runtimes.values())

    # --- Internal ---

    async def _run(self, rt: TaskRuntime, item: dict) -> None:
        if rt.mode == "once":
            await self._run_once(rt, item)
            rt.status = "completed"
            task_store.update_task(rt.task_id, {"status": "completed"})
        else:
            await self._run_loop(rt, item)

    async def _run_loop(self, rt: TaskRuntime, item: dict) -> None:
        log_service = self._log_services.get(rt.task_id, CrawlerLogService())
        try:
            while rt.status == "running":
                try:
                    result = await self._run_once(rt, item)
                    task_store.update_task(rt.task_id, {
                        "last_run_at": datetime.now().isoformat(),
                        "last_run_status": "success",
                        "status": "running",
                    })
                except Exception as exc:
                    log_service.push(log_service.create_entry(f"Loop cycle error: {exc}", "error"))
                    task_store.update_task(rt.task_id, {
                        "last_run_at": datetime.now().isoformat(),
                        "last_run_status": "error",
                        "error_message": str(exc),
                    })

                await asyncio.sleep(rt.loop_interval)
        except asyncio.CancelledError:
            pass

    async def _run_once(self, rt: TaskRuntime, item: dict) -> dict[str, Any]:
        task_id = rt.task_id
        log_service = self._log_services.get(task_id, CrawlerLogService())
        crawler = None
        api_log_handler = ApiLogHandler(log_service, task_id)
        logger = logging.getLogger("MediaCrawler")

        try:
            logger.addHandler(api_log_handler)
            await log_service.push(log_service.create_entry(
                f"Starting crawl: platform={rt.platform}, account={rt.account_id}, type={rt.crawler_type}",
                "info",
            ))

            crawler = CrawlerFactory.create_crawler(platform=rt.platform)
            if hasattr(crawler, "account_id"):
                crawler.account_id = rt.account_id

            config = item.get("config", {})
            payload = {
                "platform": rt.platform,
                "crawler_type": rt.crawler_type,
                "keywords": config.get("keywords", ""),
                "specified_ids": config.get("specified_ids", ""),
                "creator_ids": config.get("creator_ids", ""),
                "sort_type": config.get("sort_type", ""),
                "enable_comments": config.get("enable_comments", True),
                "enable_sub_comments": config.get("enable_sub_comments", False),
                "comment_time_filter_h": config.get("comment_time_filter_h", 0),
                "headless": config.get("headless", True),
                "save_option": "jsonl",
            }
            apply_runtime_request_overrides(payload)

            requirement = build_requirement_from_request_payload(
                type("Req", (), {k: v for k, v in payload.items()})(),
                source="task_center",
            )
            result = await crawler.start_with_requirement(requirement)

            # Extract comment count from result if available
            comment_count = 0
            if isinstance(result, dict):
                for task_result in result.values():
                    if isinstance(task_result, list):
                        comment_count += len(task_result)

            task_store.update_task(task_id, {
                "comment_count": comment_count,
                "last_run_at": datetime.now().isoformat(),
                "last_run_status": "success",
            })
            await log_service.push(log_service.create_entry("Crawl completed successfully", "success"))
            return result or {}

        except asyncio.CancelledError:
            await log_service.push(log_service.create_entry("Task cancelled", "warning"))
            raise
        except Exception as exc:
            rt.status = "error"
            task_store.update_task(task_id, {
                "status": "error",
                "last_run_status": "error",
                "error_message": str(exc),
            })
            await log_service.push(log_service.create_entry(f"Crawl failed: {exc}", "error"))
            raise
        finally:
            logger.removeHandler(api_log_handler)
            await cleanup_runtime(crawler)


# Singleton
task_manager = TaskManager()
```

**Step 2: Commit**

```bash
git add api/services/task_manager.py
git commit -m "feat: add TaskManager — unified scheduler for one-shot and loop tasks"
```

---

### Task 4: Task Router

**Files:**
- Create: `api/routers/tasks.py`

**Step 1: Create task router**

Create `api/routers/tasks.py`:

```python
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
```

**Step 2: Commit**

```bash
git add api/routers/tasks.py
git commit -m "feat: add /api/tasks router with CRUD, start/pause/stop"
```

---

### Task 5: Register New Router & Update WebSocket

**Files:**
- Modify: `api/app.py` — register tasks router, remove old crawler/monitors routers
- Modify: `api/routers/websocket.py` — point to `task_manager` instead of `crawler_manager`

**Step 1: Update `api/app.py`**

In the router registration section:
- Add `from .routers.tasks import router as tasks_router`
- Add `app.include_router(tasks_router, prefix="/api")`
- Keep the old `crawler_router` and `monitors_router` for now (they will be removed later after UI migration)
- Update the websocket status format to match the new `get_status()` shape (it already returns `{"tasks": [...], "active_count": N}` which matches)

**Step 2: Update `api/routers/websocket.py`**

Change imports from `crawler_manager` to use `task_manager` from `api.services.task_manager`. The `get_log_queue()`, `logs`, and `get_status()` method signatures are compatible.

```python
from ..services.task_manager import task_manager
# Replace all references to crawler_manager with task_manager
```

**Step 3: Commit**

```bash
git add api/app.py api/routers/websocket.py
git commit -m "feat: register tasks router, update websocket to use TaskManager"
```

---

### Task 6: Build TaskCenter Frontend — Left Panel (Task List)

**Files:**
- Create: `webui-react/src/components/TaskCenter.jsx`

**Step 1: Create TaskCenter component with task list**

This is the main component. It needs:
- Left panel: scrollable task list with status badges, action buttons (start/pause/stop/delete)
- `[+ 新建]` button that opens a create-task modal
- Task creation modal with: name, platform selector, account selector, crawler type, mode (once/loop), interval, keywords/IDs, etc.

The component fetches tasks from `GET /api/tasks`, creates via `POST /api/tasks`, and controls via `POST /api/tasks/{id}/start|pause|stop`.

Use the existing `CommentReaderService` API (`GET /api/comments?source_id=...`) to load comments for the selected task. The `source_id` mapping needs to be derived from the task's `platform + content_id` based on how data is stored in `data/platform_runtime/`.

This step focuses on the left panel + create modal only. The right panel (comment list + detail drawer) will be added in Task 7.

**Step 2: Commit**

```bash
git add webui-react/src/components/TaskCenter.jsx
git commit -m "feat: TaskCenter component with task list and create modal"
```

---

### Task 7: Build TaskCenter Frontend — Right Panel (Comments + Detail Drawer)

**Files:**
- Modify: `webui-react/src/components/TaskCenter.jsx`

**Step 1: Add right panel comment list**

When a task is selected in the left panel, the right panel shows:
- Header with task name + status
- Comment list fetched from `GET /api/comments?source_id=dy:{content_id}:...`
- Search/filter bar (keyword, time range)
- Each comment row shows: time, author, text preview
- Click a comment to open detail drawer

**Step 2: Add comment detail drawer**

Reuse the existing drawer/overlay pattern from the current `CommentViewer.jsx`. When a comment is clicked, a slide-in panel shows:
- Author info (nickname, short_id, avatar)
- Full comment text
- Like count, reply count
- Sub-comments/replies list
- Close button

Port the relevant rendering logic from `CommentViewer.jsx`.

**Step 3: Commit**

```bash
git add webui-react/src/components/TaskCenter.jsx
git commit -m "feat: TaskCenter comment list and detail drawer"
```

---

### Task 8: Update Navigation

**Files:**
- Modify: `webui-react/src/App.jsx`

**Step 1: Update sidebar navigation**

Replace the 5-tab navigation with 4 tabs:
```javascript
const navItems = [
  { key: 'dashboard', icon: ChartBarIcon, label: '仪表盘' },
  { key: 'tasks', icon: CommandLineIcon, label: '任务中心' },
  { key: 'account', icon: UserGroupIcon, label: '账号管理' },
  { key: 'settings', icon: Cog6ToothIcon, label: '系统设置' },
];
```

Update `renderContent()` switch to render `TaskCenter` for `'tasks'`.

**Step 2: Commit**

```bash
git add webui-react/src/App.jsx
git commit -m "feat: update navigation — merge into 4 tabs with TaskCenter"
```

---

### Task 9: Wire Up Real-time Updates

**Files:**
- Modify: `webui-react/src/components/TaskCenter.jsx`

**Step 1: Add WebSocket subscriptions**

Connect to:
- `ws://{host}:8080/api/ws/logs` — receive log entries, filter by selected task_id
- `ws://{host}:8080/api/ws/status` — receive task status updates, refresh task list

Display live logs in a collapsible panel at the bottom of the right column.

**Step 2: Add auto-refresh for loop tasks**

When a loop task is selected and running, auto-refresh comments every `loop_interval_seconds` to show new comments as they come in.

**Step 3: Commit**

```bash
git add webui-react/src/components/TaskCenter.jsx
git commit -m "feat: TaskCenter real-time WebSocket updates and auto-refresh"
```

---

### Task 10: Integration Test & Cleanup

**Step 1: Manual smoke test**

1. Start API server: `.venv/Scripts/python -m api.app`
2. Start frontend: `cd webui-react && npm run dev`
3. Open UI → 账号管理 → add a dy account → login via QR
4. Open 任务中心 → create a "once" search task → start → verify it runs and completes
5. Create a "loop" detail task → start → verify it loops → pause → resume → stop
6. Click a completed task → verify comments load in right panel
7. Click a comment → verify detail drawer opens with replies
8. Delete a task → verify it disappears

**Step 2: Verify backwards compatibility**

The old `/api/crawler/*` and `/api/monitors/*` routes still exist (not yet deleted) so nothing breaks if accessed directly.

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: unified TaskCenter replacing TaskPanel and MonitorConsole"
```

---

## Future Cleanup (not in this plan)

After the TaskCenter is verified working:
- Delete `api/routers/crawler.py` and `api/services/crawler_manager.py`
- Delete `api/routers/monitors.py` and `api/services/douyin_monitor_manager.py`
- Delete `application/services/douyin_comment_monitor_executor.py`
- Delete `application/services/monitor_store.py`
- Delete `webui-react/src/components/TaskPanel.jsx`
- Delete `webui-react/src/components/MonitorConsole.jsx`
- Delete `webui-react/src/components/CommentViewer.jsx`
- Remove old router registrations from `api/app.py`
