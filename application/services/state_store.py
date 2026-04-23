from __future__ import annotations

import csv
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from runtime.storage.persistence import (
    append_event_snapshot,
    append_job_snapshot,
    append_raw_record,
    append_result_snapshot,
    append_task_snapshot,
    upsert_normalized_content_record,
    uses_runtime_database_backend,
)
from schemas.normalized.entities import ContentRecord
from schemas.tasks.models import CrawlJob, CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskResult


class StateStore:
    """Unified application-level persistence for task/job/result/event/content state."""

    def __init__(
        self,
        *,
        tasks_base_dir: str | Path = "data/platform_runtime/tasks",
        events_base_dir: str | Path = "data/platform_runtime/events",
        normalized_base_dir: str | Path = "data/platform_runtime/normalized",
        raw_base_dir: str | Path = "data/platform_runtime/raw",
    ) -> None:
        self.data_base_dir = Path("data")
        self.tasks_base_dir = Path(tasks_base_dir)
        self.events_base_dir = Path(events_base_dir)
        self.normalized_base_dir = Path(normalized_base_dir)
        self.raw_base_dir = Path(raw_base_dir)

    async def create_task(
        self,
        *,
        task_id: str,
        platform_code: str,
        task_type: str,
        params: dict,
        schedule_type: str = "manual",
        priority: int = 0,
    ) -> CrawlTask:
        task = CrawlTask(
            task_id=task_id,
            platform_code=platform_code,
            task_type=task_type,
            status="ready",
            schedule_type=schedule_type,
            priority=priority,
            params=params,
        )
        if uses_runtime_database_backend():
            await append_task_snapshot(task)
            return task
        await self._append_snapshot(self.tasks_base_dir, platform_code, "tasks", self._serialize_task(task))
        return task

    async def create_job(
        self,
        *,
        job_id: str,
        task: CrawlTask,
        batch_id: str | None = None,
    ) -> CrawlJob:
        job = CrawlJob(
            job_id=job_id,
            task_id=task.task_id,
            platform_code=task.platform_code,
            status="queued",
            batch_id=batch_id,
        )
        if uses_runtime_database_backend():
            await append_job_snapshot(job)
            return job
        await self._append_snapshot(self.tasks_base_dir, task.platform_code, "jobs", self._serialize_job(job))
        return job

    async def mark_job_running(self, job: CrawlJob) -> CrawlJob:
        running_job = replace(job, status="running", started_at=job.started_at or datetime.utcnow())
        if uses_runtime_database_backend():
            await append_job_snapshot(running_job)
            return running_job
        await self._append_snapshot(self.tasks_base_dir, job.platform_code, "jobs", self._serialize_job(running_job))
        return running_job

    async def mark_job_succeeded(self, job: CrawlJob, *, metrics: dict | None = None) -> CrawlJob:
        succeeded_job = replace(
            job,
            status="succeeded",
            ended_at=datetime.utcnow(),
            metrics=metrics or job.metrics,
            error_code=None,
            error_message="",
        )
        if uses_runtime_database_backend():
            await append_job_snapshot(succeeded_job)
            return succeeded_job
        await self._append_snapshot(self.tasks_base_dir, job.platform_code, "jobs", self._serialize_job(succeeded_job))
        return succeeded_job

    async def mark_job_failed(
        self,
        job: CrawlJob,
        *,
        error_code: str | None,
        error_message: str,
        metrics: dict | None = None,
    ) -> CrawlJob:
        failed_job = replace(
            job,
            status="failed",
            ended_at=datetime.utcnow(),
            error_code=error_code,
            error_message=error_message,
            metrics=metrics or job.metrics,
        )
        if uses_runtime_database_backend():
            await append_job_snapshot(failed_job)
            return failed_job
        await self._append_snapshot(self.tasks_base_dir, job.platform_code, "jobs", self._serialize_job(failed_job))
        return failed_job

    async def append_result(self, result: PlatformTaskResult) -> Path:
        if uses_runtime_database_backend():
            await append_result_snapshot(result)
            return self.tasks_base_dir
        payload = {
            "job_id": result.job_id,
            "platform_code": result.platform_code,
            "task_kind": result.task_kind,
            "success": result.success,
            "payload": result.payload,
            "metrics": result.metrics,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "created_at": result.created_at.isoformat(),
        }
        return await self._append_snapshot(self.tasks_base_dir, result.platform_code, "results", payload)

    async def append_event(self, event: CrawlJobEvent, *, platform_code: str) -> Path:
        if uses_runtime_database_backend():
            await append_event_snapshot(event, platform_code)
            return self.events_base_dir
        payload = {
            "job_id": event.job_id,
            "event_type": event.event_type,
            "message": event.message,
            "details": event.details,
            "created_at": event.created_at.isoformat(),
        }
        return await self._append_snapshot(self.events_base_dir, platform_code, event.event_type, payload)

    async def append_normalized_records(self, records: list[ContentRecord]) -> Path | None:
        if not records:
            return None
        if uses_runtime_database_backend():
            for record in records:
                await upsert_normalized_content_record(record)
            return None
        platform_code = records[0].platform_code
        target_dir = self.normalized_base_dir / platform_code
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / "contents.jsonl"
        with file_path.open("a", encoding="utf-8") as file:
            for record in records:
                payload = asdict(record)
                if record.published_at is not None:
                    payload["published_at"] = record.published_at.isoformat()
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return file_path

    async def append_raw_record(self, record: RawRecord) -> Path:
        if uses_runtime_database_backend():
            await append_raw_record(record)
            return self.raw_base_dir
        target_dir = self.raw_base_dir / record.platform_code
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

    async def process_task_outcome(self, *, platform_code: str, job_id: str, outcome: dict) -> dict:
        normalized_records = outcome.get("normalized_records", [])
        if normalized_records:
            await self.append_normalized_records(normalized_records)

        raw_record = outcome.get("raw_record")
        if raw_record:
            await self.append_raw_record(
                RawRecord(
                    platform_code=platform_code,
                    record_type=raw_record["record_type"],
                    source_uri=raw_record["source_uri"],
                    request_meta=raw_record.get("request_meta", {}),
                    response_body=raw_record.get("response_body"),
                    metadata=raw_record.get("metadata", {}),
                )
            )

        for event in outcome.get("events", []):
            await self.append_event(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type=event["event_type"],
                    message=event.get("message", ""),
                    details=event.get("details", {}),
                ),
                platform_code=platform_code,
            )

        return outcome.get("response_payload", {})

    def list_data_files(self, *, platform: str | None = None, file_type: str | None = None) -> list[dict[str, Any]]:
        if not self.data_base_dir.exists():
            return []

        files: list[dict[str, Any]] = []
        supported_extensions = {".json", ".jsonl", ".csv", ".xlsx", ".xls"}

        for file_path in self.data_base_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in supported_extensions:
                continue
            rel_path = str(file_path.relative_to(self.data_base_dir))
            if platform and platform.lower() not in rel_path.lower():
                continue
            if file_type and file_path.suffix[1:].lower() != file_type.lower():
                continue
            try:
                files.append(self.get_file_info(file_path))
            except Exception:
                continue

        files.sort(key=lambda item: item["modified_at"], reverse=True)
        return files

    def resolve_data_file(self, file_path: str) -> Path:
        full_path = self.data_base_dir / file_path
        if not full_path.exists():
            raise FileNotFoundError("File not found")
        if not full_path.is_file():
            raise IsADirectoryError("Not a file")
        try:
            full_path.resolve().relative_to(self.data_base_dir.resolve())
        except ValueError as exc:
            raise PermissionError("Access denied") from exc
        return full_path

    def preview_data_file(self, file_path: str, *, limit: int = 100) -> dict[str, Any]:
        full_path = self.resolve_data_file(file_path)
        try:
            if full_path.suffix == ".json":
                with full_path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
                    if isinstance(data, list):
                        return {"data": data[:limit], "total": len(data)}
                    return {"data": data, "total": 1}
            if full_path.suffix == ".csv":
                with full_path.open("r", encoding="utf-8") as file:
                    reader = csv.DictReader(file)
                    rows = []
                    for index, row in enumerate(reader):
                        if index >= limit:
                            break
                        rows.append(row)
                    file.seek(0)
                    total = max(0, sum(1 for _ in file) - 1)
                    return {"data": rows, "total": total}
            if full_path.suffix.lower() in (".xlsx", ".xls"):
                import pandas as pd

                df = pd.read_excel(full_path, nrows=limit)
                df_count = pd.read_excel(full_path, usecols=[0])
                total = len(df_count)
                rows = df.where(pd.notnull(df), None).to_dict(orient="records")
                return {"data": rows, "total": total, "columns": list(df.columns)}
            if full_path.suffix == ".jsonl":
                with full_path.open("r", encoding="utf-8") as file:
                    rows = []
                    for index, line in enumerate(file):
                        if index >= limit:
                            break
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                    file.seek(0)
                    total = sum(1 for _ in file)
                    return {"data": rows, "total": total}
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON file") from exc

        raise ValueError("Unsupported file type for preview")

    def get_data_stats(self) -> dict[str, Any]:
        if not self.data_base_dir.exists():
            return {"total_files": 0, "total_size": 0, "by_platform": {}, "by_type": {}}

        stats = {
            "total_files": 0,
            "total_size": 0,
            "by_platform": {},
            "by_type": {},
        }
        supported_extensions = {".json", ".csv", ".xlsx", ".xls"}

        for file_path in self.data_base_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in supported_extensions:
                continue
            try:
                stat = file_path.stat()
                stats["total_files"] += 1
                stats["total_size"] += stat.st_size
                file_type = file_path.suffix[1:].lower()
                stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1
                rel_path = str(file_path.relative_to(self.data_base_dir))
                for platform in ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]:
                    if platform in rel_path.lower():
                        stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                        break
            except Exception:
                continue

        return stats

    def get_data_trends(self, *, days: int = 7) -> dict[str, Any]:
        if not self.data_base_dir.exists():
            return {"trends": []}

        trends: dict[str, int] = {}
        today = datetime.now().date()
        for index in range(days):
            date_str = (today - timedelta(days=index)).strftime("%Y-%m-%d")
            trends[date_str] = 0

        supported_extensions = {".json", ".jsonl", ".csv", ".xlsx", ".xls"}
        for file_path in self.data_base_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in supported_extensions:
                continue
            try:
                modified = datetime.fromtimestamp(file_path.stat().st_mtime).date().strftime("%Y-%m-%d")
                if modified in trends:
                    info = self.get_file_info(file_path)
                    trends[modified] += info.get("record_count") or 0
            except Exception:
                continue

        return {"trends": [{"date": date_value, "count": count} for date_value, count in sorted(trends.items())]}

    def get_file_info(self, file_path: Path) -> dict[str, Any]:
        stat = file_path.stat()
        record_count = None

        try:
            if file_path.suffix == ".json":
                with file_path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
                    if isinstance(data, list):
                        record_count = len(data)
            elif file_path.suffix in (".csv", ".jsonl"):
                with file_path.open("r", encoding="utf-8") as file:
                    record_count = sum(1 for _ in file)
                    if file_path.suffix == ".csv":
                        record_count -= 1
        except Exception:
            pass

        return {
            "name": file_path.name,
            "path": str(file_path.relative_to(self.data_base_dir)),
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "record_count": record_count,
            "type": file_path.suffix[1:] if file_path.suffix else "unknown",
        }

    async def _append_snapshot(self, base_dir: Path, platform_code: str, snapshot_type: str, payload: dict) -> Path:
        target_dir = base_dir / platform_code
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{snapshot_type}.jsonl"
        with file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return file_path

    @staticmethod
    def _serialize_task(task: CrawlTask) -> dict:
        payload = asdict(task)
        payload["created_at"] = task.created_at.isoformat()
        payload["updated_at"] = task.updated_at.isoformat()
        return payload

    @staticmethod
    def _serialize_job(job: CrawlJob) -> dict:
        payload = asdict(job)
        payload["started_at"] = job.started_at.isoformat() if job.started_at else None
        payload["ended_at"] = job.ended_at.isoformat() if job.ended_at else None
        return payload
