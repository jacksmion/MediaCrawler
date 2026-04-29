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
    snapshots = {}
    for row in rows:
        k = row.get(key)
        if k:
            snapshots[k] = row
    return snapshots


def list_tasks() -> list[dict]:
    rows = _read_jsonl(ITEMS_FILE)
    snapshots = _latest_snapshots(rows)
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
