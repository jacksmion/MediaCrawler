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
    author_short_id: str
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
        content_index = self._load_content_index()
        for file_path in self._iter_comment_files():
            for row in self._iter_comment_rows(file_path):
                content_id = str(row.get("aweme_id") or row.get("platform_content_id") or "")
                if not content_id:
                    continue

                content_record = content_index.get(content_id, {})
                source_id = f"dy:{content_id}:{file_path.relative_to(self.data_base_dir)}"
                source = sources.setdefault(
                    source_id,
                    {
                        "source_id": source_id,
                        "platform_code": "dy",
                        "platform_content_id": content_id,
                        "content_title": str(
                            row.get("title")
                            or row.get("aweme_title")
                            or content_record.get("title")
                            or content_record.get("aweme_title")
                            or ""
                        ),
                        "content_url": str(
                            row.get("aweme_url")
                            or row.get("url")
                            or content_record.get("url")
                            or content_record.get("aweme_url")
                            or ""
                        ),
                        "author_short_id": str(
                            content_record.get("author_short_id")
                            or row.get("short_id")
                            or ""
                        ),
                        "comment_count": 0,
                        "latest_comment_at": None,
                        "updated_at": file_path.stat().st_mtime,
                        "file_path": str(file_path.relative_to(self.data_base_dir)),
                    },
                )
                source["comment_count"] += 1
                source["latest_comment_at"] = self._max_ts(source["latest_comment_at"], row.get("create_time"))
                if not source["content_title"]:
                    source["content_title"] = str(
                        content_record.get("title") or content_record.get("aweme_title") or row.get("title") or row.get("aweme_title") or ""
                    )
                if not source["content_url"]:
                    source["content_url"] = str(
                        content_record.get("url") or content_record.get("aweme_url") or row.get("aweme_url") or row.get("url") or ""
                    )
                if not source["author_short_id"]:
                    source["author_short_id"] = str(content_record.get("author_short_id") or row.get("short_id") or "")

        for source in sources.values():
            source["latest_comment_at"] = self._to_iso(source["latest_comment_at"])

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
            for row in self._iter_comment_rows(file_path)
            if str(row.get("aweme_id") or row.get("platform_content_id") or "") == content_id
        ]

        if keyword:
            lowered_keyword = keyword.lower()
            rows = [row for row in rows if lowered_keyword in row.comment_text.lower()]
        if comment_level is not None:
            rows = [row for row in rows if row.comment_level == comment_level]
        if location:
            lowered_location = location.lower()
            rows = [row for row in rows if lowered_location in row.ip_location.lower()]

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
        for row in self._iter_comment_rows(file_path):
            normalized = self._normalize_row(row, content_id=content_id)
            if normalized.comment_id == comment_id:
                payload = self._serialize_row(normalized)
                payload["raw_payload"] = normalized.raw_payload
                payload["metadata"] = normalized.metadata
                payload["first_seen_run_id"] = None
                payload["last_seen_run_id"] = None
                return payload
        raise FileNotFoundError(comment_id)

    def _resolve_source_id(self, source_id: str) -> tuple[Path, str]:
        platform_code, content_id, rel_path = source_id.split(":", 2)
        if platform_code != "dy":
            raise FileNotFoundError(source_id)
        file_path = self.data_base_dir / rel_path
        if not file_path.exists():
            raise FileNotFoundError(source_id)
        return file_path, content_id

    def _normalize_row(self, row: dict[str, Any], *, content_id: str) -> CommentViewRow:
        platform_comment_id = str(row.get("cid") or row.get("comment_id") or row.get("platform_comment_id") or "")
        parent_comment_id = str(row.get("reply_id") or row.get("parent_comment_id") or "") or None
        root_comment_id = str(row.get("root_comment_id") or parent_comment_id or platform_comment_id)
        published_at = self._to_iso(row.get("create_time") or row.get("published_at"))
        user_payload = row.get("user") if isinstance(row.get("user"), dict) else {}
        avatar_thumb = user_payload.get("avatar_thumb") if isinstance(user_payload.get("avatar_thumb"), dict) else {}
        avatar_urls = avatar_thumb.get("url_list") if isinstance(avatar_thumb.get("url_list"), list) else []
        return CommentViewRow(
            comment_id=f"dy:{content_id}:{platform_comment_id}",
            platform_comment_id=platform_comment_id,
            platform_content_id=content_id,
            parent_comment_id=parent_comment_id,
            root_comment_id=root_comment_id,
            comment_level=2 if parent_comment_id else 1,
            comment_text=str(row.get("text") or row.get("content") or ""),
            author_platform_id=str(row.get("user_id") or user_payload.get("uid") or row.get("author_platform_id") or ""),
            author_short_id=str(row.get("short_id") or user_payload.get("short_id") or row.get("author_short_id") or ""),
            author_nickname=str(row.get("nickname") or user_payload.get("nickname") or row.get("author_nickname") or ""),
            author_avatar=str(row.get("avatar") or row.get("author_avatar") or (avatar_urls[0] if avatar_urls else "")),
            ip_location=str(row.get("ip_location") or row.get("ip_label") or row.get("ipLabel") or ""),
            author_home_location=str(row.get("author_home_location") or ""),
            published_at=published_at,
            like_count=int(row.get("digg_count") or row.get("like_count") or 0),
            reply_count=int(row.get("reply_comment_total") or row.get("reply_count") or 0),
            raw_payload=row,
            metadata={},
        )

    def _iter_comment_files(self) -> list[Path]:
        candidates = [
            self.data_base_dir / "dy",
            self.data_base_dir / "douyin" / "jsonl",
            self.data_base_dir / "platform_runtime" / "raw" / "douyin",
        ]
        files: list[Path] = []
        for base_dir in candidates:
            if not base_dir.exists():
                continue
            for file_path in base_dir.rglob("*.jsonl"):
                if "comment" in file_path.name.lower():
                    files.append(file_path)
        return files

    def _iter_comment_rows(self, file_path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for parsed in self._read_jsonl(file_path):
            response_body = parsed.get("response_body") if isinstance(parsed.get("response_body"), dict) else None
            if response_body and isinstance(response_body.get("comments"), list):
                rows.extend([row for row in response_body["comments"] if isinstance(row, dict)])
                continue
            rows.append(parsed)
        return rows

    def _load_content_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for file_path in self._iter_content_files():
            for row in self._read_jsonl(file_path):
                content_id = str(row.get("platform_content_id") or row.get("aweme_id") or row.get("group_id") or "")
                if not content_id:
                    continue
                existing = index.setdefault(content_id, {})
                if not existing.get("title"):
                    existing["title"] = row.get("title") or row.get("aweme_title") or row.get("desc") or row.get("body_text") or ""
                if not existing.get("url"):
                    existing["url"] = row.get("url") or row.get("aweme_url") or row.get("share_url") or ""
                if not existing.get("author_short_id"):
                    raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
                    author_payload = raw_payload.get("author") if isinstance(raw_payload.get("author"), dict) else {}
                    existing["author_short_id"] = row.get("short_id") or author_payload.get("short_id") or ""
        return index

    def _iter_content_files(self) -> list[Path]:
        candidates = [
            self.data_base_dir / "platform_runtime" / "normalized" / "douyin" / "contents.jsonl",
            self.data_base_dir / "platform_runtime" / "normalized" / "douyin",
            self.data_base_dir / "douyin" / "jsonl",
            self.data_base_dir / "dy",
        ]
        files: list[Path] = []
        for candidate in candidates:
            if not candidate.exists():
                continue
            if candidate.is_file():
                files.append(candidate)
                continue
            for file_path in candidate.rglob("*.jsonl"):
                lower_name = file_path.name.lower()
                if "content" in lower_name or "aweme" in lower_name or "detail" in lower_name:
                    files.append(file_path)
        return files

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
            "author_short_id": row.author_short_id,
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
            numeric_value = float(value)
            if numeric_value > 10_000_000_000:
                numeric_value /= 1000
            return datetime.fromtimestamp(numeric_value).isoformat(timespec="seconds")
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
