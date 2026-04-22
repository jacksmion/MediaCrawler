from __future__ import annotations

import json
from pathlib import Path

from schemas.tasks.models import CrawlJobEvent


class EventService:
    """Archives runtime events for the platform migration phase."""

    def __init__(self, base_dir: str | Path = "data/platform_runtime/events") -> None:
        self.base_dir = Path(base_dir)

    async def append(self, event: CrawlJobEvent, platform_code: str) -> Path:
        """Append an event to a platform-scoped JSONL file."""
        target_dir = self.base_dir / platform_code
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{event.event_type}.jsonl"
        payload = {
            "job_id": event.job_id,
            "event_type": event.event_type,
            "message": event.message,
            "details": event.details,
            "created_at": event.created_at.isoformat(),
        }
        with file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return file_path

