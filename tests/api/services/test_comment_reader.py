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
    assert row["ip_location"] == "江苏"
    assert row["comment_level"] == 1
    assert row["like_count"] == 8
