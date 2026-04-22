from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from runtime.storage.persistence import (
    upsert_normalized_content_record,
    uses_runtime_database_backend,
)
from schemas.normalized.entities import ContentRecord


class NormalizedContentService:
    """Archives normalized content records before DB-backed persistence exists."""

    def __init__(self, base_dir: str | Path = "data/platform_runtime/normalized") -> None:
        self.base_dir = Path(base_dir)

    async def append_many(self, records: list[ContentRecord]) -> Path | None:
        """Append a batch of normalized records grouped by platform."""
        if not records:
            return None
        if uses_runtime_database_backend():
            for record in records:
                await upsert_normalized_content_record(record)
            return None
        platform_code = records[0].platform_code
        target_dir = self.base_dir / platform_code
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / "contents.jsonl"
        with file_path.open("a", encoding="utf-8") as file:
            for record in records:
                payload = asdict(record)
                if record.published_at is not None:
                    payload["published_at"] = record.published_at.isoformat()
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return file_path
