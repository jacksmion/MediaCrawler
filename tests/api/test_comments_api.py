from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.services.comment_reader import CommentReaderService
from api.routers import comments as comments_router_module


def test_comment_sources_endpoint_returns_douyin_sources(tmp_path: Path):
    data_dir = tmp_path / "data" / "dy"
    data_dir.mkdir(parents=True)
    (data_dir / "aweme_comments.jsonl").write_text(
        '{"aweme_id":"735001","cid":"c1","text":"想去玩","nickname":"阿青","create_time":1714300000,"ip_location":"江苏"}\n',
        encoding="utf-8",
    )
    normalized_dir = tmp_path / "data" / "platform_runtime" / "normalized" / "douyin"
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "contents.jsonl").write_text(
        '{"platform_code":"douyin","platform_content_id":"735001","title":"张家界五一避坑攻略","raw_payload":{"author":{"short_id":"61063500080"}}}\n',
        encoding="utf-8",
    )

    app = create_app()
    comments_router_module.comment_reader = CommentReaderService(data_base_dir=tmp_path / "data")
    client = TestClient(app)

    response = client.get("/api/comments/sources")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["platform_code"] == "dy"
    assert body["items"][0]["author_short_id"] == "61063500080"


def test_comments_endpoint_filters_by_keyword(tmp_path: Path):
    data_dir = tmp_path / "data" / "dy"
    data_dir.mkdir(parents=True)
    (data_dir / "aweme_comments.jsonl").write_text(
        "\n".join(
            [
                '{"aweme_id":"735001","cid":"c1","text":"一家三口怎么玩","nickname":"阿青","create_time":1714300000,"ip_location":"江苏"}',
                '{"aweme_id":"735001","cid":"c2","text":"预算多少","nickname":"小雨","create_time":1714300200,"ip_location":"浙江"}',
            ]
        ),
        encoding="utf-8",
    )

    app = create_app()
    comments_router_module.comment_reader = CommentReaderService(data_base_dir=tmp_path / "data")
    client = TestClient(app)
    source_id = client.get("/api/comments/sources").json()["items"][0]["source_id"]

    response = client.get("/api/comments", params={"source_id": source_id, "keyword": "预算"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["comment_text"] == "预算多少"


def test_comment_detail_returns_author_short_id(tmp_path: Path):
    comment_dir = tmp_path / "data" / "platform_runtime" / "raw" / "douyin"
    comment_dir.mkdir(parents=True)
    (comment_dir / "comments.jsonl").write_text(
        '{"platform_code":"douyin","record_type":"comments","source_uri":"/aweme/v1/web/comment/list/","request_meta":{"aweme_id":"7625693045963028899"},"response_body":{"comments":[{"cid":"7630491314572280633","text":"计划5.1去，四大两小","aweme_id":"7625693045963028899","create_time":1776612206,"ip_label":"北京","user":{"uid":"3742364239935064","short_id":"42726548286","nickname":"用户4251815222233"}}]}}\n',
        encoding="utf-8",
    )

    app = create_app()
    comments_router_module.comment_reader = CommentReaderService(data_base_dir=tmp_path / "data")
    client = TestClient(app)
    source_id = client.get("/api/comments/sources").json()["items"][0]["source_id"]

    list_response = client.get("/api/comments", params={"source_id": source_id})

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["author_short_id"] == "42726548286"

    comment_id = list_response.json()["items"][0]["comment_id"]
    detail_response = client.get(f"/api/comments/{comment_id}", params={"source_id": source_id})

    assert detail_response.status_code == 200
    assert detail_response.json()["author_short_id"] == "42726548286"
