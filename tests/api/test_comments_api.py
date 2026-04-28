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

    app = create_app()
    comments_router_module.comment_reader = CommentReaderService(data_base_dir=tmp_path / "data")
    client = TestClient(app)

    response = client.get("/api/comments/sources")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["platform_code"] == "dy"


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
