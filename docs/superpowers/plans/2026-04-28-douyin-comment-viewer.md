# Douyin Comment Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Douyin-only comment viewer in the existing FastAPI + React app so users can browse comment sources, filter paginated comments, and inspect full comment details from current crawler output.

**Architecture:** Add a small backend read-model layer that discovers and normalizes Douyin comment files into a stable API shape, then add a dedicated React page wired to those APIs. Reuse `StateStore` path safety and file preview patterns, but keep comment viewing separate from the generic file explorer.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, React 19, Vite, ESLint, pytest, pytest-asyncio

---

## File Structure

### Backend files

- Create: `api/routers/comments.py`
  Purpose: FastAPI routes for comment sources, paginated comments, and comment details.
- Create: `api/schemas/comments.py`
  Purpose: Pydantic request/response models for the comment viewer APIs.
- Create: `api/services/comment_reader.py`
  Purpose: Discover Douyin comment files, adapt heterogeneous rows into a stable comment view model, and apply filtering/pagination.
- Modify: `api/routers/__init__.py`
  Purpose: Export the new comments router.
- Modify: `api/app.py`
  Purpose: Register the comments router under `/api`.
- Create: `tests/api/test_comments_api.py`
  Purpose: API tests for source listing, filtering, pagination, and detail lookup.
- Create: `tests/api/services/test_comment_reader.py`
  Purpose: Unit tests for file discovery and field adaptation.

### Frontend files

- Create: `webui-react/src/components/CommentViewer.jsx`
  Purpose: Dedicated Douyin comment viewer page with source list, table, filters, and detail drawer.
- Modify: `webui-react/src/App.jsx`
  Purpose: Add navigation entry and route switching for the new page.
- Create: `webui-react/src/components/commentViewerData.js`
  Purpose: Keep small presentational constants and helpers for labels/formatting out of the main component.

### Optional frontend test files

- Do not add frontend automated tests in this iteration.
  Reason: the current frontend has no test runner configured in `webui-react/package.json`, so this plan keeps verification to lint + build instead of bootstrapping a new test stack.

## Task 1: Build the backend comment read model

**Files:**
- Create: `api/services/comment_reader.py`
- Test: `tests/api/services/test_comment_reader.py`

- [ ] **Step 1: Write the failing unit tests for source discovery and row normalization**

```python
from pathlib import Path

from api.services.comment_reader import CommentReaderService


def test_list_sources_groups_douyin_comment_files(tmp_path: Path):
    comment_dir = tmp_path / "data" / "dy"
    comment_dir.mkdir(parents=True)
    comment_file = comment_dir / "aweme_comments.jsonl"
    comment_file.write_text(
        "\n".join(
            [
                '{"aweme_id":"735001","cid":"c1","text":"想去玩","nickname":"阿青","create_time":1714300000,"ip_location":"江苏"}',
                '{"aweme_id":"735001","cid":"c2","text":"预算多少","nickname":"小雨","create_time":1714300200,"ip_location":"浙江"}',
            ]
        ),
        encoding="utf-8",
    )

    service = CommentReaderService(data_base_dir=tmp_path / "data")

    sources = service.list_sources()

    assert len(sources) == 1
    assert sources[0]["platform_code"] == "dy"
    assert sources[0]["platform_content_id"] == "735001"
    assert sources[0]["comment_count"] == 2


def test_list_comments_normalizes_old_douyin_fields(tmp_path: Path):
    comment_dir = tmp_path / "data" / "dy"
    comment_dir.mkdir(parents=True)
    comment_file = comment_dir / "aweme_comments.jsonl"
    comment_file.write_text(
        '{"aweme_id":"735001","cid":"c1","text":"一家三口怎么玩","nickname":"阿青","user_id":"u1","create_time":1714300000,"ip_location":"江苏","reply_id":"","reply_comment_total":3,"digg_count":8}\n',
        encoding="utf-8",
    )

    service = CommentReaderService(data_base_dir=tmp_path / "data")
    source_id = service.list_sources()[0]["source_id"]

    result = service.list_comments(source_id=source_id, keyword=None, comment_level=None, location=None, limit=20, offset=0, sort="published_at_desc")

    assert result["total"] == 1
    row = result["items"][0]
    assert row["platform_comment_id"] == "c1"
    assert row["comment_text"] == "一家三口怎么玩"
    assert row["author_nickname"] == "阿青"
    assert row["author_platform_id"] == "u1"
    assert row["ip_location"] == "江苏"
    assert row["comment_level"] == 1
    assert row["like_count"] == 8
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run:

```powershell
python -m pytest tests/api/services/test_comment_reader.py -v
```

Expected: FAIL with import errors because `api.services.comment_reader` and the test package do not exist yet.

- [ ] **Step 3: Write the minimal service and normalization model**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CommentViewRow:
    comment_id: str
    platform_comment_id: str
    platform_content_id: str
    parent_comment_id: str | None
    root_comment_id: str | None
    comment_level: int
    comment_text: str
    author_platform_id: str
    author_nickname: str
    author_avatar: str
    ip_location: str
    author_home_location: str
    published_at: str | None
    like_count: int
    reply_count: int
    raw_payload: dict[str, Any]
    metadata: dict[str, Any]


class CommentReaderService:
    def __init__(self, *, data_base_dir: str | Path = "data") -> None:
        self.data_base_dir = Path(data_base_dir)

    def list_sources(self) -> list[dict[str, Any]]:
        sources: dict[str, dict[str, Any]] = {}
        for file_path in (self.data_base_dir / "dy").rglob("*.jsonl"):
            if "comment" not in file_path.name.lower():
                continue
            for row in self._read_jsonl(file_path):
                content_id = str(row.get("aweme_id") or row.get("platform_content_id") or "")
                if not content_id:
                    continue
                source_id = f"dy:{content_id}:{file_path.relative_to(self.data_base_dir)}"
                source = sources.setdefault(
                    source_id,
                    {
                        "source_id": source_id,
                        "platform_code": "dy",
                        "platform_content_id": content_id,
                        "content_title": str(row.get("title") or row.get("aweme_title") or ""),
                        "content_url": str(row.get("aweme_url") or ""),
                        "comment_count": 0,
                        "latest_comment_at": None,
                        "updated_at": file_path.stat().st_mtime,
                        "file_path": str(file_path.relative_to(self.data_base_dir)),
                    },
                )
                source["comment_count"] += 1
                source["latest_comment_at"] = self._max_ts(source["latest_comment_at"], row.get("create_time"))
        return sorted(sources.values(), key=lambda item: item["updated_at"], reverse=True)

    def list_comments(
        self,
        *,
        source_id: str,
        keyword: str | None,
        comment_level: int | None,
        location: str | None,
        limit: int,
        offset: int,
        sort: str,
    ) -> dict[str, Any]:
        file_path, content_id = self._resolve_source_id(source_id)
        rows = [
            self._normalize_row(row, content_id=content_id)
            for row in self._read_jsonl(file_path)
            if str(row.get("aweme_id") or row.get("platform_content_id") or "") == content_id
        ]
        if keyword:
            rows = [row for row in rows if keyword.lower() in row.comment_text.lower()]
        if comment_level is not None:
            rows = [row for row in rows if row.comment_level == comment_level]
        if location:
            rows = [row for row in rows if location.lower() in row.ip_location.lower()]
        rows.sort(key=lambda row: row.published_at or "", reverse=(sort != "published_at_asc"))
        total = len(rows)
        paged = rows[offset: offset + limit]
        return {
            "items": [self._serialize_row(row) for row in paged],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_comment_detail(self, *, source_id: str, comment_id: str) -> dict[str, Any]:
        file_path, content_id = self._resolve_source_id(source_id)
        for row in self._read_jsonl(file_path):
            normalized = self._normalize_row(row, content_id=content_id)
            if normalized.comment_id == comment_id:
                payload = self._serialize_row(normalized)
                payload["raw_payload"] = normalized.raw_payload
                payload["metadata"] = normalized.metadata
                payload["first_seen_run_id"] = None
                payload["last_seen_run_id"] = None
                return payload
        raise FileNotFoundError(comment_id)
```

- [ ] **Step 4: Complete the helper methods required by the tests**

```python
    def _resolve_source_id(self, source_id: str) -> tuple[Path, str]:
        _, content_id, rel_path = source_id.split(":", 2)
        file_path = self.data_base_dir / rel_path
        if not file_path.exists():
            raise FileNotFoundError(source_id)
        return file_path, content_id

    def _normalize_row(self, row: dict[str, Any], *, content_id: str) -> CommentViewRow:
        platform_comment_id = str(row.get("cid") or row.get("comment_id") or row.get("platform_comment_id") or "")
        parent_comment_id = str(row.get("reply_id") or row.get("parent_comment_id") or "") or None
        root_comment_id = str(row.get("root_comment_id") or parent_comment_id or platform_comment_id)
        published_at = self._to_iso(row.get("create_time") or row.get("published_at"))
        return CommentViewRow(
            comment_id=f"dy:{content_id}:{platform_comment_id}",
            platform_comment_id=platform_comment_id,
            platform_content_id=content_id,
            parent_comment_id=parent_comment_id,
            root_comment_id=root_comment_id,
            comment_level=2 if parent_comment_id else 1,
            comment_text=str(row.get("text") or row.get("content") or ""),
            author_platform_id=str(row.get("user_id") or row.get("author_platform_id") or ""),
            author_nickname=str(row.get("nickname") or row.get("author_nickname") or ""),
            author_avatar=str(row.get("avatar") or row.get("author_avatar") or ""),
            ip_location=str(row.get("ip_location") or row.get("ipLabel") or ""),
            author_home_location=str(row.get("author_home_location") or ""),
            published_at=published_at,
            like_count=int(row.get("digg_count") or row.get("like_count") or 0),
            reply_count=int(row.get("reply_comment_total") or row.get("reply_count") or 0),
            raw_payload=row,
            metadata={},
        )

    def _serialize_row(self, row: CommentViewRow) -> dict[str, Any]:
        return {
            "comment_id": row.comment_id,
            "platform_comment_id": row.platform_comment_id,
            "platform_content_id": row.platform_content_id,
            "parent_comment_id": row.parent_comment_id,
            "root_comment_id": row.root_comment_id,
            "comment_level": row.comment_level,
            "comment_text": row.comment_text,
            "author_platform_id": row.author_platform_id,
            "author_nickname": row.author_nickname,
            "author_avatar": row.author_avatar,
            "ip_location": row.ip_location,
            "author_home_location": row.author_home_location,
            "published_at": row.published_at,
            "like_count": row.like_count,
            "reply_count": row.reply_count,
            "raw_payload_available": True,
        }

    def _read_jsonl(self, file_path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
        return rows

    @staticmethod
    def _to_iso(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, str) and "T" in value:
            return value
        try:
            return datetime.fromtimestamp(int(value)).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _max_ts(current: Any, candidate: Any) -> Any:
        try:
            current_int = int(current) if current is not None else 0
            candidate_int = int(candidate) if candidate is not None else 0
            return max(current_int, candidate_int)
        except (TypeError, ValueError):
            return current
```

- [ ] **Step 5: Run the unit tests to verify they pass**

Run:

```powershell
python -m pytest tests/api/services/test_comment_reader.py -v
```

Expected: PASS with 2 passing tests.

- [ ] **Step 6: Commit**

```powershell
git add api/services/comment_reader.py tests/api/services/test_comment_reader.py
git commit -m "feat: add douyin comment reader service"
```

## Task 2: Expose the backend APIs

**Files:**
- Create: `api/routers/comments.py`
- Create: `api/schemas/comments.py`
- Modify: `api/routers/__init__.py`
- Modify: `api/app.py`
- Test: `tests/api/test_comments_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
from fastapi.testclient import TestClient

from api.app import create_app


def test_comment_sources_endpoint_returns_douyin_sources(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "dy"
    data_dir.mkdir(parents=True)
    (data_dir / "aweme_comments.jsonl").write_text(
        '{"aweme_id":"735001","cid":"c1","text":"想去玩","nickname":"阿青","create_time":1714300000,"ip_location":"江苏"}\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("MEDIA_CRAWLER_PROJECT_ROOT", str(tmp_path))

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/comments/sources")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["platform_code"] == "dy"


def test_comments_endpoint_filters_by_keyword(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "dy"
    data_dir.mkdir(parents=True)
    (data_dir / "aweme_comments.jsonl").write_text(
        "\n".join(
            [
                '{"aweme_id":"735001","cid":"c1","text":"一家三口怎么玩","nickname":"阿青","create_time":1714300000,"ip_location":"江苏"}',
                '{"aweme_id":"735001","cid":"c2","text":"预算多少","nickname":"小雨","create_time":1714300200,"ip_location":"浙江"}',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MEDIA_CRAWLER_PROJECT_ROOT", str(tmp_path))

    app = create_app()
    client = TestClient(app)
    source_id = client.get("/api/comments/sources").json()["items"][0]["source_id"]

    response = client.get("/api/comments", params={"source_id": source_id, "keyword": "预算"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["comment_text"] == "预算多少"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run:

```powershell
python -m pytest tests/api/test_comments_api.py -v
```

Expected: FAIL because `/api/comments/*` routes and response models do not exist yet.

- [ ] **Step 3: Add request and response models**

```python
from pydantic import BaseModel, Field


class CommentSourceResponse(BaseModel):
    source_id: str
    platform_code: str
    platform_content_id: str
    content_title: str = ""
    content_url: str = ""
    comment_count: int = 0
    latest_comment_at: str | int | None = None
    updated_at: float
    file_path: str


class CommentSourceListResponse(BaseModel):
    items: list[CommentSourceResponse]


class CommentListItemResponse(BaseModel):
    comment_id: str
    platform_comment_id: str
    platform_content_id: str
    parent_comment_id: str | None = None
    root_comment_id: str | None = None
    comment_level: int
    comment_text: str
    author_platform_id: str = ""
    author_nickname: str = ""
    author_avatar: str = ""
    ip_location: str = ""
    author_home_location: str = ""
    published_at: str | None = None
    like_count: int = 0
    reply_count: int = 0
    raw_payload_available: bool = False


class CommentListResponse(BaseModel):
    items: list[CommentListItemResponse]
    total: int
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
```

- [ ] **Step 4: Add the router and wire it into the app**

```python
from fastapi import APIRouter, HTTPException, Query

from api.schemas.comments import CommentListResponse, CommentSourceListResponse
from api.services.comment_reader import CommentReaderService

router = APIRouter(prefix="/comments", tags=["comments"])
comment_reader = CommentReaderService()


@router.get("/sources", response_model=CommentSourceListResponse)
async def list_comment_sources():
    return {"items": comment_reader.list_sources()}


@router.get("", response_model=CommentListResponse)
async def list_comments(
    source_id: str,
    keyword: str | None = None,
    comment_level: int | None = Query(default=None, ge=1, le=2),
    location: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="published_at_desc"),
):
    try:
        return comment_reader.list_comments(
            source_id=source_id,
            keyword=keyword,
            comment_level=comment_level,
            location=location,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Comment source not found") from exc


@router.get("/{comment_id}")
async def get_comment_detail(source_id: str, comment_id: str):
    try:
        return comment_reader.get_comment_detail(source_id=source_id, comment_id=comment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Comment not found") from exc
```

Also update integrations:

```python
from .comments import router as comments_router

__all__ = ["crawler_router", "data_router", "websocket_router", "account_router", "config_router", "comments_router"]
```

```python
from .routers import account_router, comments_router, config_router, crawler_router, data_router, websocket_router

app.include_router(comments_router, prefix="/api")
```

- [ ] **Step 5: Run the API tests to verify they pass**

Run:

```powershell
python -m pytest tests/api/test_comments_api.py -v
```

Expected: PASS with source listing and keyword filtering covered.

- [ ] **Step 6: Run the full backend test slice**

Run:

```powershell
python -m pytest tests/api -v
```

Expected: PASS for the newly added API and service tests.

- [ ] **Step 7: Commit**

```powershell
git add api/app.py api/routers/__init__.py api/routers/comments.py api/schemas/comments.py tests/api/test_comments_api.py
git commit -m "feat: add douyin comment viewer api"
```

## Task 3: Add the React comment viewer page

**Files:**
- Create: `webui-react/src/components/CommentViewer.jsx`
- Create: `webui-react/src/components/commentViewerData.js`
- Modify: `webui-react/src/App.jsx`

- [ ] **Step 1: Add the navigation entry and blank page mount**

```jsx
import CommentViewer from './components/CommentViewer';

const [activeTab, setActiveTab] = useState('dashboard');

case 'comments': return <CommentViewer />;

<NavItem
  icon={ChatBubbleLeftRightIcon}
  label="评论查看"
  active={activeTab === 'comments'}
  onClick={() => setActiveTab('comments')}
/>
```

- [ ] **Step 2: Run lint to verify the placeholder page fails cleanly if imports are missing**

Run:

```powershell
& 'C:\Program Files\nodejs\npm.cmd' run lint
```

Expected: FAIL until `CommentViewer.jsx` and the new icon import exist.

- [ ] **Step 3: Create the minimal viewer page with source loading**

```jsx
import React, { useEffect, useMemo, useState } from 'react';

const API_BASE = `http://${window.location.hostname}:8080/api/comments`;

export default function CommentViewer() {
  const [sources, setSources] = useState([]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [comments, setComments] = useState([]);
  const [selectedComment, setSelectedComment] = useState(null);
  const [keyword, setKeyword] = useState('');
  const [commentLevel, setCommentLevel] = useState('');
  const [location, setLocation] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    const loadSources = async () => {
      setLoading(true);
      const response = await fetch(`${API_BASE}/sources`);
      const body = await response.json();
      setSources(body.items || []);
      setSelectedSourceId((body.items || [])[0]?.source_id || '');
      setLoading(false);
    };
    loadSources();
  }, []);
```

- [ ] **Step 4: Add comment list fetching, filters, and detail drawer**

```jsx
  useEffect(() => {
    if (!selectedSourceId) {
      setComments([]);
      return;
    }
    const params = new URLSearchParams({ source_id: selectedSourceId, limit: '50', offset: '0' });
    if (keyword) params.set('keyword', keyword);
    if (commentLevel) params.set('comment_level', commentLevel);
    if (location) params.set('location', location);

    const loadComments = async () => {
      const response = await fetch(`${API_BASE}?${params.toString()}`);
      const body = await response.json();
      setComments(body.items || []);
      setSelectedComment(null);
    };
    loadComments();
  }, [selectedSourceId, keyword, commentLevel, location]);

  const handleSelectComment = async (commentId) => {
    setDetailLoading(true);
    const params = new URLSearchParams({ source_id: selectedSourceId });
    const response = await fetch(`${API_BASE}/${encodeURIComponent(commentId)}?${params.toString()}`);
    const body = await response.json();
    setSelectedComment(body);
    setDetailLoading(false);
  };
```

- [ ] **Step 5: Render the three-panel UI**

```jsx
  return (
    <div className="h-full grid grid-cols-[320px_minmax(0,1fr)_360px] gap-6 p-8">
      <section className="rounded-3xl border border-slate-800 bg-slate-900 overflow-hidden">
        <header className="border-b border-slate-800 px-5 py-4">
          <h2 className="text-lg font-bold">抖音评论来源</h2>
        </header>
        <div className="overflow-y-auto h-[calc(100%-64px)]">
          {sources.map((source) => (
            <button
              key={source.source_id}
              onClick={() => setSelectedSourceId(source.source_id)}
              className={`w-full px-5 py-4 text-left border-b border-slate-800/70 ${selectedSourceId === source.source_id ? 'bg-blue-600/10' : 'hover:bg-slate-800/50'}`}
            >
              <div className="text-sm font-semibold text-slate-200">{source.content_title || source.platform_content_id}</div>
              <div className="mt-1 text-xs text-slate-500">{source.comment_count} 条评论</div>
            </button>
          ))}
        </div>
      </section>
      <section className="rounded-3xl border border-slate-800 bg-slate-900 overflow-hidden">
        <header className="border-b border-slate-800 px-5 py-4 flex gap-3">
          <input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索评论关键词" className="flex-1 rounded-xl bg-slate-950 border border-slate-800 px-3 py-2" />
          <select value={commentLevel} onChange={(e) => setCommentLevel(e.target.value)} className="rounded-xl bg-slate-950 border border-slate-800 px-3 py-2">
            <option value="">全部层级</option>
            <option value="1">一级评论</option>
            <option value="2">二级回复</option>
          </select>
          <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="地区/IP属地" className="w-36 rounded-xl bg-slate-950 border border-slate-800 px-3 py-2" />
        </header>
```

- [ ] **Step 6: Run lint and build to verify the new page integrates**

Run:

```powershell
& 'C:\Program Files\nodejs\npm.cmd' run lint
& 'C:\Program Files\nodejs\npm.cmd' run build
```

Expected: PASS for both commands.

- [ ] **Step 7: Commit**

```powershell
git add webui-react/src/App.jsx webui-react/src/components/CommentViewer.jsx webui-react/src/components/commentViewerData.js
git commit -m "feat: add douyin comment viewer page"
```

## Task 4: End-to-end verification and empty-state polish

**Files:**
- Modify: `api/services/comment_reader.py`
- Modify: `api/routers/comments.py`
- Modify: `webui-react/src/components/CommentViewer.jsx`

- [ ] **Step 1: Add explicit empty-state behavior for missing sources and empty result sets**

```python
@router.get("/sources", response_model=CommentSourceListResponse)
async def list_comment_sources():
    items = comment_reader.list_sources()
    return {"items": items}
```

```jsx
if (!loading && sources.length === 0) {
  return (
    <div className="p-8">
      <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-900/60 p-12 text-center text-slate-400">
        暂未发现可查看的抖音评论数据，请先完成一次抖音评论抓取。
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add error state handling around fetches**

```jsx
const [error, setError] = useState('');

try {
  const response = await fetch(`${API_BASE}/sources`);
  if (!response.ok) throw new Error('加载评论来源失败');
  const body = await response.json();
  setSources(body.items || []);
  setError('');
} catch (err) {
  setError(err instanceof Error ? err.message : '加载失败');
}
```

- [ ] **Step 3: Run backend tests and frontend build as final verification**

Run:

```powershell
python -m pytest tests/api -v
& 'C:\Program Files\nodejs\npm.cmd' run lint
& 'C:\Program Files\nodejs\npm.cmd' run build
```

Expected: PASS for all commands.

- [ ] **Step 4: Manual verification against a real local comment file**

Run:

```powershell
uv run python -m api.main
```

Then verify manually:

- Visit the WebUI
- Open `评论查看`
- Confirm at least one Douyin source appears
- Click a source and confirm comments render
- Search by a keyword present in the file
- Filter to `一级评论` and `二级回复`
- Open one detail panel and confirm raw payload renders

Expected: all interactions succeed without blank screens.

- [ ] **Step 5: Commit**

```powershell
git add api/services/comment_reader.py api/routers/comments.py webui-react/src/components/CommentViewer.jsx
git commit -m "fix: polish douyin comment viewer states"
```

## Self-Review

### Spec coverage

- Dedicated Douyin-only comment page: covered by Task 3.
- Comment source listing: covered by Task 1 and Task 2.
- Paginated comment browsing with filters: covered by Task 1, Task 2, and Task 3.
- Comment detail with raw payload: covered by Task 1, Task 2, and Task 3.
- Empty/error states: covered by Task 4.
- Future-friendly structure for monitor-item evolution: preserved by the separate router and reader service in Tasks 1 and 2.

### Placeholder scan

- No `TODO` or `TBD` placeholders remain.
- Each code-changing step includes concrete code.
- Every verification step has a command and expected outcome.

### Type consistency

- Backend uses one stable row shape: `comment_id`, `platform_comment_id`, `comment_text`, `author_nickname`, `ip_location`, `comment_level`.
- Frontend steps reference the same API field names.
- Router paths remain consistent across tests and UI fetches: `/api/comments/sources`, `/api/comments`, `/api/comments/{comment_id}`.
