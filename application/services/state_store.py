from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

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
