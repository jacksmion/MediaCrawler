from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from typing import Any
from uuid import uuid4

import config
from database.db_session import get_session
from database.models import (
    RuntimeCrawlEventSnapshot,
    RuntimeCrawlJobSnapshot,
    RuntimeCrawlResultSnapshot,
    RuntimeCrawlTaskSnapshot,
    RuntimeNormalizedContent,
    RuntimeRawRecord,
)
from schemas.normalized.entities import ContentRecord
from schemas.tasks.models import CrawlJob, CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskResult

if TYPE_CHECKING:
    from database.mongodb_store_base import MongoDBStoreBase


RELATIONAL_SAVE_OPTIONS = {"db", "sqlite", "postgres"}
MONGO_SAVE_OPTIONS = {"mongodb"}


def uses_relational_backend() -> bool:
    return config.SAVE_DATA_OPTION in RELATIONAL_SAVE_OPTIONS


def uses_mongo_backend() -> bool:
    return config.SAVE_DATA_OPTION in MONGO_SAVE_OPTIONS


def uses_runtime_database_backend() -> bool:
    return uses_relational_backend() or uses_mongo_backend()


def _utc_timestamp() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _to_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _optional_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


class RuntimeMongoArchive:
    def __init__(self) -> None:
        from database.mongodb_store_base import MongoDBStoreBase

        self.store: MongoDBStoreBase = MongoDBStoreBase(collection_prefix="runtime")

    async def upsert_normalized_content(self, record: ContentRecord) -> None:
        content_key = f"{record.platform_code}:{record.platform_content_id}"
        await self.store.save_or_update(
            collection_suffix="normalized_contents",
            query={"content_key": content_key},
            data={
                "content_key": content_key,
                "platform_code": record.platform_code,
                "platform_content_id": record.platform_content_id,
                "content_type": record.content_type,
                "title": record.title,
                "body_text": record.body_text,
                "url": record.url,
                "author_platform_id": record.author_platform_id,
                "published_at": _optional_iso(record.published_at),
                "raw_payload": record.raw_payload,
                "metadata": record.metadata,
                "last_modify_ts": _utc_timestamp(),
            },
        )

    async def append_raw_record(self, record: RawRecord) -> None:
        snapshot_id = uuid4().hex
        await self.store.save_or_update(
            collection_suffix="raw_records",
            query={"snapshot_id": snapshot_id},
            data={
                "snapshot_id": snapshot_id,
                "platform_code": record.platform_code,
                "record_type": record.record_type,
                "source_uri": record.source_uri,
                "fetched_at": record.fetched_at.isoformat(),
                "request_meta": record.request_meta,
                "response_body": record.response_body,
                "content_hash": record.content_hash,
                "metadata": record.metadata,
                "add_ts": _utc_timestamp(),
            },
        )

    async def append_task_snapshot(self, task: CrawlTask) -> None:
        snapshot_id = uuid4().hex
        await self.store.save_or_update(
            collection_suffix="crawl_tasks",
            query={"snapshot_id": snapshot_id},
            data={
                "snapshot_id": snapshot_id,
                "task_id": task.task_id,
                "platform_code": task.platform_code,
                "task_type": task.task_type,
                "status": task.status,
                "schedule_type": task.schedule_type,
                "priority": task.priority,
                "params": task.params,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
                "add_ts": _utc_timestamp(),
            },
        )

    async def append_job_snapshot(self, job: CrawlJob) -> None:
        snapshot_id = uuid4().hex
        await self.store.save_or_update(
            collection_suffix="crawl_jobs",
            query={"snapshot_id": snapshot_id},
            data={
                "snapshot_id": snapshot_id,
                "job_id": job.job_id,
                "task_id": job.task_id,
                "platform_code": job.platform_code,
                "status": job.status,
                "batch_id": job.batch_id,
                "started_at": _optional_iso(job.started_at),
                "ended_at": _optional_iso(job.ended_at),
                "error_code": job.error_code,
                "error_message": job.error_message,
                "metrics": job.metrics,
                "add_ts": _utc_timestamp(),
            },
        )

    async def append_result_snapshot(self, result: PlatformTaskResult) -> None:
        snapshot_id = uuid4().hex
        await self.store.save_or_update(
            collection_suffix="crawl_results",
            query={"snapshot_id": snapshot_id},
            data={
                "snapshot_id": snapshot_id,
                "job_id": result.job_id,
                "platform_code": result.platform_code,
                "task_kind": result.task_kind,
                "success": result.success,
                "payload": result.payload,
                "metrics": result.metrics,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "created_at": result.created_at.isoformat(),
                "add_ts": _utc_timestamp(),
            },
        )

    async def append_event_snapshot(self, event: CrawlJobEvent, platform_code: str) -> None:
        snapshot_id = uuid4().hex
        await self.store.save_or_update(
            collection_suffix="crawl_events",
            query={"snapshot_id": snapshot_id},
            data={
                "snapshot_id": snapshot_id,
                "job_id": event.job_id,
                "platform_code": platform_code,
                "event_type": event.event_type,
                "message": event.message,
                "details": event.details,
                "created_at": event.created_at.isoformat(),
                "add_ts": _utc_timestamp(),
            },
        )


_mongo_archive: RuntimeMongoArchive | None = None


def get_runtime_mongo_archive() -> RuntimeMongoArchive:
    global _mongo_archive
    if _mongo_archive is None:
        _mongo_archive = RuntimeMongoArchive()
    return _mongo_archive


async def upsert_normalized_content_record(record: ContentRecord) -> None:
    published_at = _optional_iso(record.published_at)
    if uses_relational_backend():
        content_key = f"{record.platform_code}:{record.platform_content_id}"
        async with get_session() as session:
            existing = await session.get(RuntimeNormalizedContent, content_key)
            add_ts = _utc_timestamp()
            if existing is None:
                session.add(
                    RuntimeNormalizedContent(
                        content_key=content_key,
                        platform_code=record.platform_code,
                        platform_content_id=record.platform_content_id,
                        content_type=record.content_type,
                        title=record.title,
                        body_text=record.body_text,
                        url=record.url,
                        author_platform_id=record.author_platform_id,
                        published_at=published_at,
                        raw_payload=_to_json(record.raw_payload),
                        metadata=_to_json(record.metadata),
                        add_ts=add_ts,
                        last_modify_ts=add_ts,
                    )
                )
            else:
                existing.content_type = record.content_type
                existing.title = record.title
                existing.body_text = record.body_text
                existing.url = record.url
                existing.author_platform_id = record.author_platform_id
                existing.published_at = published_at
                existing.raw_payload = _to_json(record.raw_payload)
                existing.metadata = _to_json(record.metadata)
                existing.last_modify_ts = add_ts
        return
    if uses_mongo_backend():
        await get_runtime_mongo_archive().upsert_normalized_content(record)


async def append_raw_record(record: RawRecord) -> None:
    if uses_relational_backend():
        async with get_session() as session:
            session.add(
                RuntimeRawRecord(
                    snapshot_id=uuid4().hex,
                    platform_code=record.platform_code,
                    record_type=record.record_type,
                    source_uri=record.source_uri,
                    fetched_at=record.fetched_at.isoformat(),
                    request_meta=_to_json(record.request_meta),
                    response_body=_to_json(record.response_body),
                    content_hash=record.content_hash,
                    metadata=_to_json(record.metadata),
                    add_ts=_utc_timestamp(),
                )
            )
        return
    if uses_mongo_backend():
        await get_runtime_mongo_archive().append_raw_record(record)


async def append_task_snapshot(task: CrawlTask) -> None:
    if uses_relational_backend():
        async with get_session() as session:
            session.add(
                RuntimeCrawlTaskSnapshot(
                    snapshot_id=uuid4().hex,
                    task_id=task.task_id,
                    platform_code=task.platform_code,
                    task_type=task.task_type,
                    status=task.status,
                    schedule_type=task.schedule_type,
                    priority=task.priority,
                    params=_to_json(task.params),
                    created_at=task.created_at.isoformat(),
                    updated_at=task.updated_at.isoformat(),
                    add_ts=_utc_timestamp(),
                )
            )
        return
    if uses_mongo_backend():
        await get_runtime_mongo_archive().append_task_snapshot(task)


async def append_job_snapshot(job: CrawlJob) -> None:
    if uses_relational_backend():
        async with get_session() as session:
            session.add(
                RuntimeCrawlJobSnapshot(
                    snapshot_id=uuid4().hex,
                    job_id=job.job_id,
                    task_id=job.task_id,
                    platform_code=job.platform_code,
                    status=job.status,
                    batch_id=job.batch_id,
                    started_at=_optional_iso(job.started_at),
                    ended_at=_optional_iso(job.ended_at),
                    error_code=job.error_code,
                    error_message=job.error_message,
                    metrics=_to_json(job.metrics),
                    add_ts=_utc_timestamp(),
                )
            )
        return
    if uses_mongo_backend():
        await get_runtime_mongo_archive().append_job_snapshot(job)


async def append_result_snapshot(result: PlatformTaskResult) -> None:
    if uses_relational_backend():
        async with get_session() as session:
            session.add(
                RuntimeCrawlResultSnapshot(
                    snapshot_id=uuid4().hex,
                    job_id=result.job_id,
                    platform_code=result.platform_code,
                    task_kind=result.task_kind,
                    success=1 if result.success else 0,
                    payload=_to_json(result.payload),
                    metrics=_to_json(result.metrics),
                    error_code=result.error_code,
                    error_message=result.error_message,
                    created_at=result.created_at.isoformat(),
                    add_ts=_utc_timestamp(),
                )
            )
        return
    if uses_mongo_backend():
        await get_runtime_mongo_archive().append_result_snapshot(result)


async def append_event_snapshot(event: CrawlJobEvent, platform_code: str) -> None:
    if uses_relational_backend():
        async with get_session() as session:
            session.add(
                RuntimeCrawlEventSnapshot(
                    snapshot_id=uuid4().hex,
                    job_id=event.job_id,
                    platform_code=platform_code,
                    event_type=event.event_type,
                    message=event.message,
                    details=_to_json(event.details),
                    created_at=event.created_at.isoformat(),
                    add_ts=_utc_timestamp(),
                )
            )
        return
    if uses_mongo_backend():
        await get_runtime_mongo_archive().append_event_snapshot(event, platform_code)
