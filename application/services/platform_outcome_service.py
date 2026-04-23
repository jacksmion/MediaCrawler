from __future__ import annotations

from schemas.normalized.entities import ContentRecord
from schemas.tasks.models import CrawlJobEvent, RawRecord


class PlatformOutcomeService:
    """Application-level persistence/publishing helpers for connector task outcomes."""

    @staticmethod
    async def append_normalized_records(services, records: list[ContentRecord]) -> None:
        if records:
            await services.normalized_content_service.append_many(records)

    @staticmethod
    async def append_raw_record(
        services,
        *,
        platform_code: str,
        record_type: str,
        source_uri: str,
        request_meta: dict,
        response_body,
        metadata: dict,
    ) -> None:
        await services.raw_record_service.append(
            RawRecord(
                platform_code=platform_code,
                record_type=record_type,
                source_uri=source_uri,
                request_meta=request_meta,
                response_body=response_body,
                metadata=metadata,
            )
        )

    @staticmethod
    async def append_event(
        services,
        *,
        platform_code: str,
        job_id: str,
        event_type: str,
        message: str,
        details: dict,
    ) -> None:
        await services.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type=event_type,
                message=message,
                details=details,
            ),
            platform_code=platform_code,
        )

    @classmethod
    async def process_task_outcome(cls, services, *, platform_code: str, job_id: str, outcome: dict) -> dict:
        normalized_records = outcome.get("normalized_records", [])
        if normalized_records:
            await cls.append_normalized_records(services, normalized_records)

        raw_record = outcome.get("raw_record")
        if raw_record:
            await cls.append_raw_record(
                services,
                platform_code=platform_code,
                record_type=raw_record["record_type"],
                source_uri=raw_record["source_uri"],
                request_meta=raw_record.get("request_meta", {}),
                response_body=raw_record.get("response_body"),
                metadata=raw_record.get("metadata", {}),
            )

        for event in outcome.get("events", []):
            await cls.append_event(
                services,
                platform_code=platform_code,
                job_id=job_id,
                event_type=event["event_type"],
                message=event.get("message", ""),
                details=event.get("details", {}),
            )

        return outcome.get("response_payload", {})
