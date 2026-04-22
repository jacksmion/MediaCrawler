from __future__ import annotations

import json
from pathlib import Path

from schemas.tasks.models import RawRecord


class RawRecordService:
    """Archives raw records locally during the platform migration phase."""

    def __init__(self, base_dir: str | Path = "data/platform_runtime/raw") -> None:
        self.base_dir = Path(base_dir)

    async def append(self, record: RawRecord) -> Path:
        """Append a raw record to a JSONL archive file grouped by platform and type."""
        target_dir = self.base_dir / record.platform_code
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{record.record_type}.jsonl"
        payload = {
            "platform_code": record.platform_code,
            "record_type": record.record_type,
            "source_uri": record.source_uri,
            "fetched_at": record.fetched_at.isoformat(),
            "request_meta": record.request_meta,
            "response_body": record.response_body,
            "content_hash": record.content_hash,
            "metadata": record.metadata,
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            import aiofiles  # type: ignore

            async with aiofiles.open(file_path, "a", encoding="utf-8") as file:
                await file.write(line)
        except ModuleNotFoundError:
            with file_path.open("a", encoding="utf-8") as file:
                file.write(line)
        return file_path
