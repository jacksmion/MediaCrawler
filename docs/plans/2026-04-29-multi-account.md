# Multi-Account Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support multiple accounts per platform with concurrent crawling and account rotation.

**Architecture:** Each account gets an isolated browser profile directory under `browser_data/<account_id>/`. A new `AccountService` manages account CRUD persisted to `browser_data/accounts.json`. `CrawlerManager` is refactored from single-task to multi-task with per-account concurrency control. The UI AccountCenter is rebuilt to show per-platform account lists with add/login/delete actions.

**Tech Stack:** Python/FastAPI (backend), React/Tailwind (frontend), Playwright (browser automation), JSON file (account persistence).

---

### Task 1: Account Model & Service

**Files:**
- Create: `api/services/account_service.py`
- Create: `api/schemas/account.py`

**Step 1: Create account schema**

Create `api/schemas/account.py`:

```python
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class AccountCreateRequest(BaseModel):
    """Request to add a new account."""
    platform: str
    name: str = ""
    remark: str = ""


class AccountResponse(BaseModel):
    """Single account info."""
    account_id: str
    name: str
    platform: str
    remark: str
    status: str = "unknown"          # active / expired / unknown
    login_type: str = "none"         # standard / cdp / none
    last_login_at: str | None = None
    last_active: float | None = None  # directory mtime timestamp
    created_at: str


class AccountListResponse(BaseModel):
    """List of accounts grouped optionally by platform."""
    accounts: list[AccountResponse]
```

**Step 2: Create account service**

Create `api/services/account_service.py`:

```python
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from api.schemas.account import AccountCreateRequest, AccountResponse

BROWSER_DATA_DIR = Path(__file__).parent.parent.parent / "browser_data"
ACCOUNTS_FILE = BROWSER_DATA_DIR / "accounts.json"


def _load_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.exists():
        return []
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_accounts(accounts: list[dict]) -> None:
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
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
        enriched = _enrich_status(a)
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
    enriched = _enrich_status(account)
    return AccountResponse(**enriched)


def delete_account(account_id: str) -> bool:
    accounts = _load_accounts()
    target = next((a for a in accounts if a["account_id"] == account_id), None)
    if target is None:
        return False

    # Remove profile directory
    for d in [BROWSER_DATA_DIR / account_id, BROWSER_DATA_DIR / f"cdp_{account_id}"]:
        if d.exists():
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    accounts = [a for a in accounts if a["account_id"] != account_id]
    _save_accounts(accounts)
    return True


def get_account(account_id: str) -> Optional[AccountResponse]:
    accounts = _load_accounts()
    target = next((a for a in accounts if a["account_id"] == account_id), None)
    if target is None:
        return None
    enriched = _enrich_status(target)
    return AccountResponse(**enriched)
```

**Step 3: Commit**

```bash
git add api/schemas/account.py api/services/account_service.py
git commit -m "feat: add account model and service with JSON persistence"
```

---

### Task 2: Update Schemas for Multi-Task

**Files:**
- Modify: `api/schemas/crawler.py` (add `account_id`, `task_id` to requests; add `TaskStatus`)
- Modify: `api/schemas/__init__.py` (export new schemas)

**Step 1: Update CrawlerStartRequest and add TaskStatus**

In `api/schemas/crawler.py`, add `account_id` and `task_id` to `CrawlerStartRequest` (after line 58):

```python
class CrawlerStartRequest(BaseModel):
    """Crawler start request"""
    platform: PlatformEnum
    login_type: LoginTypeEnum = LoginTypeEnum.QRCODE
    crawler_type: CrawlerTypeEnum = CrawlerTypeEnum.SEARCH
    keywords: str = ""
    specified_ids: str = ""
    creator_ids: str = ""
    start_page: int = 1
    enable_comments: bool = True
    enable_sub_comments: bool = False
    save_option: SaveDataOptionEnum = SaveDataOptionEnum.JSONL
    cookies: str = ""
    headless: bool = False
    sort_type: str = ""
    comment_time_filter_h: int = 0
    account_id: str = ""       # NEW: which account to use
    task_id: str = ""           # NEW: optional task ID, auto-generated if empty
```

Add `TaskStatus` model after `CrawlerStatusResponse`:

```python
class TaskStatus(BaseModel):
    """Single task status entry."""
    task_id: str
    account_id: str
    platform: str
    crawler_type: str
    status: str                # idle / running / stopping / error / completed
    started_at: str | None = None

class CrawlerStatusResponse(BaseModel):
    """Crawler status response - multi-task"""
    tasks: list[TaskStatus] = []
    active_count: int = 0
```

Remove the old single-task fields from `CrawlerStatusResponse` (status, platform, crawler_type, started_at, error_message) and replace with the above.

**Step 2: Update `__init__.py` exports**

In `api/schemas/__init__.py`, add `TaskStatus` to the import from `.crawler` and to `__all__`.

**Step 3: Commit**

```bash
git add api/schemas/crawler.py api/schemas/__init__.py
git commit -m "feat: add account_id/task_id to CrawlerStartRequest, TaskStatus model"
```

---

### Task 3: Refactor CrawlerManager for Multi-Task

**Files:**
- Modify: `api/services/crawler_manager.py`

**Step 1: Refactor CrawlerManager**

Replace the single `CrawlerRuntimeState` with a dict keyed by `task_id`. Add concurrency limits and account-id collision check. Key changes:

1. `self._tasks: dict[str, CrawlerRuntimeState]` replaces `self.runtime`
2. `CrawlerRuntimeState` gains `account_id: str` and `task_id: str` fields
3. Each task gets its own `CrawlerLogService` in `self._log_services: dict[str, CrawlerLogService]`
4. `start()` generates `task_id` if not provided, checks same-account conflict, enforces `MAX_CONCURRENT_TASKS`
5. `stop(task_id)` cancels a specific task
6. `get_status()` returns all tasks (for `CrawlerStatusResponse`)
7. `logs` property becomes `get_logs(task_id)` method
8. `MAX_CONCURRENT_TASKS = 3` class constant

The full refactored class structure:

```python
MAX_CONCURRENT_TASKS = 3


@dataclass(slots=True)
class CrawlerRuntimeState:
    task_id: str
    account_id: str
    handle: Optional[object] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    current_config: Optional[object] = None
    platform: str = ""
    crawler_type: str = ""


class CrawlerManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._tasks: dict[str, CrawlerRuntimeState] = {}
        self._log_services: dict[str, CrawlerLogService] = {}
        self.runtime_config_service = RuntimeConfigService()

    # --- Task management ---

    async def start(self, config: CrawlerStartRequest) -> str | None:
        """Start a crawler task. Returns task_id on success, None on failure."""
        async with self._lock:
            account_id = config.account_id or self._default_account_id(config.platform.value)

            # Check concurrent limit
            running = [t for t in self._tasks.values() if t.status == "running"]
            if len(running) >= MAX_CONCURRENT_TASKS:
                return None

            # Check same-account conflict
            if any(t.account_id == account_id and t.status == "running" for t in running):
                return None

            task_id = config.task_id or f"task_{uuid.uuid4().hex[:8]}"
            if task_id in self._tasks and self._tasks[task_id].status == "running":
                return None

            log_service = CrawlerLogService()
            self._log_services[task_id] = log_service

            resolved_config = await self._resolve_config(config)
            # Patch account_id into resolved config for connector to use
            resolved_config.account_id = account_id

            await log_service.push(log_service.create_entry(
                f"Starting crawler: platform={resolved_config.platform.value}, account={account_id}",
                "info",
            ))

            try:
                runtime = CrawlerRuntimeState(
                    task_id=task_id,
                    account_id=account_id,
                    status="running",
                    started_at=datetime.now(),
                    current_config=resolved_config,
                    platform=resolved_config.platform.value,
                    crawler_type=resolved_config.crawler_type.value,
                )
                handle = InProcessCrawlerHandle(
                    task=asyncio.create_task(self._run_crawler(runtime, resolved_config))
                )
                runtime.handle = handle
                self._tasks[task_id] = runtime

                await log_service.push(log_service.create_entry(
                    f"Crawler started: {resolved_config.platform.value}, account={account_id}",
                    "success",
                ))
                return task_id
            except Exception as e:
                await log_service.push(log_service.create_entry(f"Failed to start: {e}", "error"))
                return None

    async def stop(self, task_id: str) -> bool:
        """Stop a specific task."""
        async with self._lock:
            runtime = self._tasks.get(task_id)
            if not runtime or runtime.status != "running":
                return False

            runtime.status = "stopping"
            log_service = self._log_services.get(task_id)
            if log_service:
                await log_service.push(log_service.create_entry("Cancelling task...", "warning"))

            handle = runtime.handle
            if isinstance(handle, InProcessCrawlerHandle):
                handle.task.cancel()
                try:
                    await asyncio.wait_for(handle.task, timeout=15.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            runtime.status = "idle"
            runtime.handle = None
            runtime.current_config = None
            return True

    def get_status(self) -> dict:
        """Return multi-task status for API response."""
        tasks = []
        for tid, rt in self._tasks.items():
            if rt.status in ("running", "stopping"):
                tasks.append({
                    "task_id": tid,
                    "account_id": rt.account_id,
                    "platform": rt.platform,
                    "crawler_type": rt.crawler_type,
                    "status": rt.status,
                    "started_at": rt.started_at.isoformat() if rt.started_at else None,
                })
        return {
            "tasks": tasks,
            "active_count": len([t for t in tasks if t["status"] == "running"]),
        }

    def get_logs(self, task_id: str, limit: int = 100) -> list:
        """Get logs for a specific task."""
        log_service = self._log_services.get(task_id)
        if not log_service:
            return []
        logs = log_service.logs[-limit:] if limit > 0 else log_service.logs
        return [log.model_dump() for log in logs]

    def is_running(self, task_id: str | None = None) -> bool:
        if task_id:
            rt = self._tasks.get(task_id)
            return rt is not None and rt.status == "running"
        return any(rt.status == "running" for rt in self._tasks.values())

    # --- Internal ---

    def _default_account_id(self, platform: str) -> str:
        """Fallback: use the legacy single-profile directory pattern."""
        return f"{platform}_user_data_dir"

    async def _run_crawler(self, runtime: CrawlerRuntimeState, resolved_config) -> None:
        task_id = runtime.task_id
        log_service = self._log_services.get(task_id, CrawlerLogService())
        crawler = None
        api_log_handler = ApiLogHandler(log_service)
        logger = logging.getLogger("MediaCrawler")
        try:
            logger.addHandler(api_log_handler)
            payload = resolved_config.model_dump(mode="json")
            apply_runtime_request_overrides(payload)
            crawler = CrawlerFactory.create_crawler(platform=resolved_config.platform.value)
            # Inject account_id for profile isolation
            if hasattr(crawler, "account_id"):
                crawler.account_id = resolved_config.account_id
            if resolved_config.crawler_type.value == "login":
                await crawler.start()
            else:
                requirement = build_requirement_from_request_payload(resolved_config, source="webui_api")
                await crawler.start_with_requirement(requirement)
            if runtime.status == "running":
                await log_service.push(log_service.create_entry("Crawler completed successfully", "success"))
                runtime.status = "completed"
        except asyncio.CancelledError:
            await log_service.push(log_service.create_entry("Task cancelled", "warning"))
            runtime.status = "idle"
            raise
        except Exception as exc:
            runtime.status = "error"
            await log_service.push(log_service.create_entry(f"Crawler failed: {exc}", "error"))
        finally:
            logger.removeHandler(api_log_handler)
            await cleanup_runtime(crawler)
            runtime.handle = None

    async def _resolve_config(self, request: CrawlerStartRequest):
        config_payload = await self.runtime_config_service.get_all()
        resolved_data = merge_request_with_runtime_overrides(
            request.model_dump(),
            config_payload["merged"],
            override_keys=config_payload["overrides"],
            explicit_fields=set(request.model_fields_set),
        )
        from ..schemas import ResolvedCrawlerConfig
        resolved = ResolvedCrawlerConfig(**resolved_data)
        resolved.account_id = request.account_id
        return resolved
```

**Step 2: Commit**

```bash
git add api/services/crawler_manager.py
git commit -m "feat: refactor CrawlerManager for multi-task with per-account concurrency"
```

---

### Task 4: Update ResolvedCrawlerConfig & ConnectorCrawlerBase

**Files:**
- Modify: `api/schemas/crawler.py` (add `account_id` to `ResolvedCrawlerConfig`)
- Modify: `application/services/connector_crawlers.py` (use `account_id` for profile path)

**Step 1: Add account_id to ResolvedCrawlerConfig**

In `api/schemas/crawler.py`, add `account_id: str = ""` to `ResolvedCrawlerConfig`.

**Step 2: Modify ConnectorCrawlerBase to use account_id for browser profile**

In `application/services/connector_crawlers.py`:

1. Add `self.account_id: str = ""` to `ConnectorCrawlerBase.__init__` (after line 47).

2. Modify `launch_browser()` (lines 175-194) to use `self.account_id` instead of the hardcoded template:

```python
async def launch_browser(self, chromium, playwright_proxy, user_agent, headless=True):
    if config.SAVE_LOGIN_STATE:
        profile_name = self.account_id or (config.USER_DATA_DIR % config.PLATFORM)
        user_data_dir = os.path.join(os.getcwd(), "browser_data", profile_name)
        return await chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            accept_downloads=True,
            headless=headless,
            proxy=playwright_proxy,
            channel="chrome",
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent,
        )
    browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")
    return await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
```

3. Modify `launch_browser_with_cdp()` similarly — in `cdp_browser.py` the path is also constructed with the template. We need to pass `account_id` through to `CDPBrowserManager` so it can use it. The simplest approach: set `config.PLATFORM` temporarily or add a parameter. Add an `account_id` parameter to `CDPBrowserManager.launch_and_connect()` and use it in the user-data-dir construction.

In `runtime/browser/cdp_browser.py`, modify `_launch_browser()` to accept an optional `account_id`:

```python
async def _launch_browser(self, browser_path: str, headless: bool, account_id: str = ""):
    user_data_dir = None
    if config.SAVE_LOGIN_STATE:
        profile_name = account_id or f"cdp_{config.USER_DATA_DIR % config.PLATFORM}"
        user_data_dir = os.path.join(os.getcwd(), "browser_data", profile_name)
        os.makedirs(user_data_dir, exist_ok=True)
```

Then pass it through from `launch_and_connect()` and from `connector_crawlers.py`'s `launch_browser_with_cdp()`.

4. Update `_build_connector_context()` to include the real account_id:

```python
def _build_connector_context(self, job_id: str, task_id: str):
    from connectors.base.models import ConnectorContext
    return ConnectorContext(
        account_id=self.account_id or None,
        proxy=self._platform_http_proxy,
        metadata={"source": f"{self.platform_name}_connector_crawler", "job_id": job_id, "task_id": task_id},
    )
```

**Step 3: Commit**

```bash
git add api/schemas/crawler.py application/services/connector_crawlers.py runtime/browser/cdp_browser.py
git commit -m "feat: connector uses account_id for browser profile isolation"
```

---

### Task 5: Update Account Router for Multi-Account

**Files:**
- Modify: `api/routers/account.py`

**Step 1: Rewrite account router**

Replace the entire `api/routers/account.py` with multi-account CRUD endpoints:

```python
from __future__ import annotations

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

    # Find the PlatformEnum value
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
        raise HTTPException(status_code=400, detail="Failed to start login. A task may already be running for this account.")
    return {"success": True, "message": f"Login started for {account.name}. Check the browser window to scan QR code.", "task_id": task_id}


@router.get("/{account_id}/status", response_model=AccountResponse)
async def get_account_status(account_id: str):
    """Get login status for a specific account."""
    account = get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account
```

**Step 2: Commit**

```bash
git add api/routers/account.py
git commit -m "feat: rewrite account router with multi-account CRUD and login"
```

---

### Task 6: Update Crawler Router for Multi-Task

**Files:**
- Modify: `api/routers/crawler.py`

**Step 1: Update crawler endpoints for multi-task**

```python
from fastapi import APIRouter, HTTPException

from ..schemas import CrawlerStartRequest, CrawlerStatusResponse
from ..services.crawler_manager import crawler_manager

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start a crawler task. Returns task_id on success."""
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
```

**Step 2: Commit**

```bash
git add api/routers/crawler.py
git commit -m "feat: crawler router supports multi-task start/stop/status/logs"
```

---

### Task 7: Update Session Store for Multi-Account

**Files:**
- Modify: `runtime/session/store.py`

**Step 1: Change InMemorySessionStore to dict-keyed**

```python
from __future__ import annotations

from runtime.session.models import SessionState


class InMemorySessionStore:
    """Per-account session store backed by an in-memory dict."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def save(self, session: SessionState) -> SessionState:
        key = session.account_id or session.platform_code
        self._sessions[key] = session
        return session

    def load(self, account_id: str = "", platform_code: str = "") -> SessionState | None:
        key = account_id or platform_code
        return self._sessions.get(key)

    def load_all(self) -> list[SessionState]:
        return list(self._sessions.values())
```

**Step 2: Commit**

```bash
git add runtime/session/store.py
git commit -m "feat: session store supports multiple accounts via dict key"
```

---

### Task 8: Rebuild AccountCenter UI

**Files:**
- Modify: `webui-react/src/components/AccountCenter.jsx`

**Step 1: Rewrite AccountCenter for multi-account**

The new UI groups accounts by platform, supports add/delete/login per account, and uses a modal dialog for the add-account form.

Key structure:
- Fetch accounts from `GET /api/account/list`
- Group by `account.platform`
- Per-platform section header with platform name
- Per-account card: name, status badge, login button, delete button
- "Add account" button opens a simple form (platform selector + name input)
- Login triggers `POST /api/account/{account_id}/login`
- Delete triggers `DELETE /api/account/{account_id}` with confirmation

**Step 2: Commit**

```bash
git add webui-react/src/components/AccountCenter.jsx
git commit -m "feat: rebuild AccountCenter UI for multi-account management"
```

---

### Task 9: Update TaskPanel to Select Account

**Files:**
- Modify: `webui-react/src/components/TaskPanel.jsx` (or equivalent task start UI component)

**Step 1: Add account selector to task start form**

When the user selects a platform, fetch accounts for that platform and show a dropdown to pick which account to use. Pass `account_id` in the `CrawlerStartRequest` when starting a crawler.

**Step 2: Update task list to show per-task status**

The status endpoint now returns a list of tasks. Update the task list display to show `task_id`, `account_id`, `platform`, `status`, and a stop button per task.

**Step 3: Commit**

```bash
git add webui-react/src/components/TaskPanel.jsx
git commit -m "feat: TaskPanel shows account selector and multi-task status"
```

---

### Task 10: Integration Test & Cleanup

**Step 1: Manual smoke test**

1. Start the API server
2. Open the web UI
3. Add two accounts for platform "dy"
4. Login to both accounts via QR code
5. Start two concurrent crawl tasks using different accounts
6. Verify both run simultaneously
7. Stop one task, verify the other continues
8. Delete an account, verify its profile directory is removed

**Step 2: Fix any issues found during smoke testing**

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete multi-account support with concurrent crawling"
```
