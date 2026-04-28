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
    assert sources[0]["latest_comment_at"] == "2024-04-28T18:30:00"


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

    result = service.list_comments(
        source_id=source_id,
        keyword=None,
        comment_level=None,
        location=None,
        limit=20,
        offset=0,
        sort="published_at_desc",
    )

    assert result["total"] == 1
    row = result["items"][0]
    assert row["platform_comment_id"] == "c1"
    assert row["comment_text"] == "一家三口怎么玩"
    assert row["author_nickname"] == "阿青"
    assert row["author_platform_id"] == "u1"
    assert row["author_short_id"] == ""
    assert row["ip_location"] == "江苏"
    assert row["comment_level"] == 1
    assert row["like_count"] == 8


def test_list_sources_reads_runtime_raw_comment_batches(tmp_path: Path):
    comment_dir = tmp_path / "data" / "platform_runtime" / "raw" / "douyin"
    comment_dir.mkdir(parents=True)
    comment_file = comment_dir / "comments.jsonl"
    comment_file.write_text(
        '{"platform_code":"douyin","record_type":"comments","source_uri":"/aweme/v1/web/comment/list/","fetched_at":"2026-04-28T12:12:01","request_meta":{"aweme_id":"7625693045963028899","cursor":0},"response_body":{"comments":[{"cid":"7630491314572280633","text":"计划5.1去，四大两小","aweme_id":"7625693045963028899","create_time":1776612206,"digg_count":2,"reply_id":"0","reply_comment_total":1,"ip_label":"北京","level":1,"user":{"uid":"3742364239935064","short_id":"42726548286","nickname":"用户4251815222233","avatar_thumb":{"url_list":["https://example.com/avatar.jpeg"]}}}],"cursor":20,"has_more":1},"metadata":{"comment_count":1,"cursor":20,"has_more":true}}\n',
        encoding="utf-8",
    )

    service = CommentReaderService(data_base_dir=tmp_path / "data")

    sources = service.list_sources()

    assert len(sources) == 1
    assert sources[0]["platform_content_id"] == "7625693045963028899"
    assert sources[0]["comment_count"] == 1

    result = service.list_comments(
        source_id=sources[0]["source_id"],
        keyword=None,
        comment_level=None,
        location=None,
        limit=20,
        offset=0,
        sort="published_at_desc",
    )

    assert result["total"] == 1
    row = result["items"][0]
    assert row["platform_comment_id"] == "7630491314572280633"
    assert row["comment_text"] == "计划5.1去，四大两小"
    assert row["author_platform_id"] == "3742364239935064"
    assert row["author_short_id"] == "42726548286"
    assert row["author_nickname"] == "用户4251815222233"
    assert row["author_avatar"] == "https://example.com/avatar.jpeg"
    assert row["ip_location"] == "北京"
    assert row["like_count"] == 2
    assert row["comment_level"] == 1


def test_list_comments_dedupes_repeated_runtime_comment_batches(tmp_path: Path):
    comment_dir = tmp_path / "data" / "platform_runtime" / "raw" / "douyin"
    comment_dir.mkdir(parents=True)
    comment_file = comment_dir / "comments.jsonl"
    comment_file.write_text(
        "\n".join(
            [
                '{"platform_code":"douyin","record_type":"comments","source_uri":"/aweme/v1/web/comment/list/","fetched_at":"2026-04-28T12:12:01","request_meta":{"aweme_id":"7625693045963028899","cursor":0},"response_body":{"comments":[{"cid":"c1","text":"计划5.1去，四大两小","aweme_id":"7625693045963028899","create_time":1776612206,"reply_id":"0","user":{"uid":"u1","nickname":"阿青"}}],"cursor":20,"has_more":1},"metadata":{"comment_count":1,"cursor":20,"has_more":true}}',
                '{"platform_code":"douyin","record_type":"comments","source_uri":"/aweme/v1/web/comment/list/","fetched_at":"2026-04-28T12:13:01","request_meta":{"aweme_id":"7625693045963028899","cursor":0},"response_body":{"comments":[{"cid":"c1","text":"计划5.1去，四大两小","aweme_id":"7625693045963028899","create_time":1776612206,"reply_id":"0","user":{"uid":"u1","nickname":"阿青"}}],"cursor":20,"has_more":1},"metadata":{"comment_count":1,"cursor":20,"has_more":true}}',
            ]
        ),
        encoding="utf-8",
    )

    service = CommentReaderService(data_base_dir=tmp_path / "data")
    source_id = service.list_sources()[0]["source_id"]

    sources = service.list_sources()
    assert sources[0]["comment_count"] == 1

    result = service.list_comments(
        source_id=source_id,
        keyword=None,
        comment_level=None,
        location=None,
        limit=20,
        offset=0,
        sort="published_at_desc",
    )

    assert result["total"] == 1
    assert result["items"][0]["platform_comment_id"] == "c1"


def test_list_sources_uses_normalized_content_title_when_available(tmp_path: Path):
    comment_dir = tmp_path / "data" / "platform_runtime" / "raw" / "douyin"
    comment_dir.mkdir(parents=True)
    comment_file = comment_dir / "comments.jsonl"
    comment_file.write_text(
        '{"platform_code":"douyin","record_type":"comments","source_uri":"/aweme/v1/web/comment/list/","fetched_at":"2026-04-28T12:12:01","request_meta":{"aweme_id":"7625693045963028899","cursor":0},"response_body":{"comments":[{"cid":"7630491314572280633","text":"计划5.1去，四大两小","aweme_id":"7625693045963028899","create_time":1776612206,"digg_count":2,"reply_id":"0","reply_comment_total":1,"ip_label":"北京","level":1,"user":{"uid":"3742364239935064","nickname":"用户4251815222233"}}],"cursor":20,"has_more":1},"metadata":{"comment_count":1,"cursor":20,"has_more":true}}\n',
        encoding="utf-8",
    )
    normalized_dir = tmp_path / "data" / "platform_runtime" / "normalized" / "douyin"
    normalized_dir.mkdir(parents=True)
    normalized_file = normalized_dir / "contents.jsonl"
    normalized_file.write_text(
        '{"platform_code":"douyin","platform_content_id":"7625693045963028899","title":"张家界五一避坑攻略","url":"https://www.douyin.com/video/7625693045963028899","raw_payload":{"author":{"short_id":"61063500080"}}}\n',
        encoding="utf-8",
    )

    service = CommentReaderService(data_base_dir=tmp_path / "data")

    sources = service.list_sources()

    assert len(sources) == 1
    assert sources[0]["content_title"] == "张家界五一避坑攻略"
    assert sources[0]["content_url"] == "https://www.douyin.com/video/7625693045963028899"
    assert sources[0]["author_short_id"] == "61063500080"
