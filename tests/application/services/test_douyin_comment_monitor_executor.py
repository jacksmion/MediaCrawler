from application.services.douyin_comment_monitor_executor import DouyinCommentMonitorExecutor


class _FakeCrawler:
    async def start_with_requirement(self, requirement):
        return {
            "derived_results": [
                {
                    "task_kind": "comments",
                    "comments": [{"cid": "c1"}, {"cid": "c2"}],
                    "cursor": 100,
                    "has_more": True,
                }
            ]
        }


async def _noop_cleanup(_crawler):
    return None


def test_refresh_once_reads_comments_from_derived_result_payload(monkeypatch):
    monkeypatch.setattr(
        "application.services.douyin_comment_monitor_executor.build_requirement_from_request_payload",
        lambda payload, source, max_pages_default: {"payload": payload, "source": source, "max_pages_default": max_pages_default},
    )
    monkeypatch.setattr(
        "application.services.douyin_comment_monitor_executor.CrawlerFactory.create_crawler",
        lambda platform: _FakeCrawler(),
    )
    monkeypatch.setattr(
        "application.services.douyin_comment_monitor_executor.cleanup_runtime",
        _noop_cleanup,
    )

    executor = DouyinCommentMonitorExecutor()
    result = __import__("asyncio").run(
        executor.refresh_once(
            {
                "content_id": "7625693045963028899",
                "last_cursor": "",
            }
        )
    )

    assert result["last_cursor"] == "100"
    assert result["last_run_comment_count"] == 2
