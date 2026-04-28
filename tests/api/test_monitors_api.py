from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.routers import monitors as monitors_router_module
from api.services.douyin_monitor_manager import DouyinMonitorManager


class StubMonitorExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def refresh_once(self, item: dict) -> dict:
        self.calls.append(item)
        return {
            "last_cursor": "cursor-1",
            "last_success_at": "2026-04-28T22:10:00",
            "last_error": "",
            "last_run_comment_count": 5,
        }


def create_test_manager(tmp_path: Path) -> DouyinMonitorManager:
    return DouyinMonitorManager(
        data_base_dir=tmp_path / "data",
        executor=StubMonitorExecutor(),
    )


def test_monitor_item_crud_and_control(tmp_path: Path):
    app = create_app()
    monitors_router_module.monitor_manager = create_test_manager(tmp_path)
    client = TestClient(app)

    create_response = client.post(
        "/api/monitors",
        json={
            "content_url": "https://www.douyin.com/video/7625693045963028899",
            "refresh_interval_seconds": 60,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["platform_code"] == "dy"
    assert created["content_id"] == "7625693045963028899"
    assert created["status"] == "idle"

    list_response = client.get("/api/monitors")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["monitor_item_id"] == created["monitor_item_id"]

    update_response = client.patch(
        f"/api/monitors/{created['monitor_item_id']}",
        json={"title": "张家界评论监控", "refresh_interval_seconds": 120},
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["title"] == "张家界评论监控"
    assert updated["refresh_interval_seconds"] == 120

    start_response = client.post(f"/api/monitors/{created['monitor_item_id']}/start")

    assert start_response.status_code == 200
    started = start_response.json()
    assert started["status"] == "running"

    logs_response = client.get(f"/api/monitors/{created['monitor_item_id']}/logs")

    assert logs_response.status_code == 200
    assert logs_response.json()["items"]

    stop_response = client.post(f"/api/monitors/{created['monitor_item_id']}/stop")

    assert stop_response.status_code == 200
    stopped = stop_response.json()
    assert stopped["status"] == "paused"
