# -*- coding: utf-8 -*-
#
# Connector-native crawler entrypoints used by CLI and API runtimes.

from __future__ import annotations

import os
from typing import Any

from playwright.async_api import BrowserContext, BrowserType, Page, Playwright, async_playwright

import config
from base.base_crawler import AbstractCrawler
from database import db
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from schemas.tasks.requirements import (
    BilibiliCrawlRequirement,
    DouyinCrawlRequirement,
    KuaishouCrawlRequirement,
    TiebaCrawlRequirement,
    WeiboCrawlRequirement,
    XhsCrawlRequirement,
    ZhihuCrawlRequirement,
)
from tools import utils
from tools.cdp_browser import CDPBrowserManager

from connectors.xhs.client import XiaoHongShuClient

from .platform_logins import BilibiliLogin, DouYinLogin, KuaishouLogin, BaiduTieBaLogin, WeiboLogin, XiaoHongShuLogin, ZhiHuLogin

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .raw_record_service import RawRecordService
from runtime.storage.persistence import uses_relational_backend


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class ConnectorCrawlerBase(AbstractCrawler):
    platform_name: str
    index_url: str
    user_agent: str
    login_cls: type | None = None
    uses_stealth_script = True

    def __init__(self) -> None:
        self.context_page: Page | None = None
        self.browser_context: BrowserContext | None = None
        self.cdp_manager: CDPBrowserManager | None = None
        self.ip_proxy_pool = None
        self._platform_http_proxy: str | None = None
        self.crawl_state_service = CrawlStateService()
        self.event_service = EventService()
        self.normalized_content_service = NormalizedContentService()
        self.raw_record_service = RawRecordService()
        self.task_executor = self._build_task_executor()

    def _build_task_executor(self):
        raise NotImplementedError

    def _build_requirement_from_runtime_config(self):
        raise NotImplementedError

    def _build_connector_for_health_check(self):
        raise NotImplementedError

    async def _initialize_runtime(self, playwright: Playwright) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)
        self._platform_http_proxy = httpx_proxy_format

        if config.ENABLE_CDP_MODE:
            self.browser_context = await self.launch_browser_with_cdp(
                playwright,
                playwright_proxy_format,
                self.user_agent,
                headless=config.CDP_HEADLESS,
            )
        else:
            self.browser_context = await self.launch_browser(
                playwright.chromium,
                playwright_proxy_format,
                self.user_agent,
                headless=config.HEADLESS,
            )
            if self.uses_stealth_script:
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

        self.context_page = await self.browser_context.new_page()
        await self.context_page.goto(self.index_url)
        await self._after_page_ready(httpx_proxy_format)

        if not await self._is_authenticated():
            await self._login()
            await self._after_login()

    async def _ensure_persistence_ready(self) -> None:
        if uses_relational_backend():
            await db.init_db(config.SAVE_DATA_OPTION)

    async def _after_page_ready(self, httpx_proxy: str | None) -> None:
        return None

    async def _after_login(self) -> None:
        return None

    async def _is_authenticated(self) -> bool:
        connector = self._build_connector_for_health_check()
        if connector is None:
            return True
        await connector.prepare(self._build_connector_context("runtime-auth", "runtime-auth"))
        try:
            status = await connector.health_check()
            return bool(status.ok)
        finally:
            await connector.close()

    async def _login(self) -> None:
        if self.login_cls is None:
            return
        if self.browser_context is None or self.context_page is None:
            raise RuntimeError(f"{self.platform_name} runtime is not initialized")
        login = self.login_cls(
            login_type=config.LOGIN_TYPE,
            browser_context=self.browser_context,
            context_page=self.context_page,
            login_phone="",
            cookie_str=config.COOKIES,
        )
        await login.begin()

    async def start(self) -> None:
        async with async_playwright() as playwright:
            await self._initialize_runtime(playwright)
            if config.CRAWLER_TYPE == "login":
                return
            await self._ensure_persistence_ready()
            await self.task_executor.execute_requirement(self._build_requirement_from_runtime_config())

    async def search(self) -> None:
        """Backward-compatible entry required by AbstractCrawler."""
        await self.start()

    async def start_with_requirement(self, requirement) -> dict[str, Any]:
        async with async_playwright() as playwright:
            await self._initialize_runtime(playwright)
            await self._ensure_persistence_ready()
            return await self.task_executor.execute_requirement(requirement)

    async def execute_platform_task(self, task) -> dict[str, Any]:
        await self._ensure_persistence_ready()
        return await self.task_executor.execute(task)

    async def execute_platform_requirement(self, requirement) -> dict[str, Any]:
        await self._ensure_persistence_ready()
        return await self.task_executor.execute_requirement(requirement)

    def _build_connector_context(self, job_id: str, task_id: str):
        from connectors.base.models import ConnectorContext

        return ConnectorContext(
            account_id=None,
            proxy=self._platform_http_proxy,
            metadata={"source": f"{self.platform_name}_connector_crawler", "job_id": job_id, "task_id": task_id},
        )

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: dict[str, Any] | None,
        user_agent: str | None,
        headless: bool = True,
    ) -> BrowserContext:
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore[arg-type]
            return await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore[arg-type]
                channel="chrome",
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
            )
        browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")  # type: ignore[arg-type]
        return await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: dict[str, Any] | None,
        user_agent: str | None,
        headless: bool = True,
    ) -> BrowserContext:
        self.cdp_manager = CDPBrowserManager()
        try:
            return await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )
        except Exception:
            self.cdp_manager = None
            return await self.launch_browser(playwright.chromium, playwright_proxy, user_agent, headless)

    async def close(self) -> None:
        if self.cdp_manager:
            try:
                await self.cdp_manager.cleanup(force=True)
            except TypeError:
                await self.cdp_manager.cleanup()
            self.cdp_manager = None
            return
        if self.browser_context:
            try:
                await self.browser_context.close()
            except Exception:
                pass


class XhsConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "xhs"
    index_url = "https://www.xiaohongshu.com"
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    login_cls = XiaoHongShuLogin

    def __init__(self) -> None:
        self.xhs_client: XiaoHongShuClient | None = None
        super().__init__()

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.xhs import build_xhs_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_xhs_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="xhs",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_xhs_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    async def _after_page_ready(self, httpx_proxy: str | None) -> None:
        if self.browser_context is None or self.context_page is None:
            raise RuntimeError("XHS runtime is not initialized")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        self.xhs_client = XiaoHongShuClient(
            proxy=httpx_proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": "https://www.xiaohongshu.com",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": "https://www.xiaohongshu.com/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,
        )

    async def _after_login(self) -> None:
        if self.xhs_client is not None and self.browser_context is not None:
            await self.xhs_client.update_cookies(browser_context=self.browser_context)

    def _build_connector_for_health_check(self):
        from connectors.xhs import build_xhs_connector_from_legacy

        return build_xhs_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> XhsCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return XhsCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                sort_type=str(config.SORT_TYPE or "general"),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return XhsCrawlRequirement(
                mode="detail",
                note_urls=list(getattr(config, "XHS_SPECIFIED_NOTE_URL_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return XhsCrawlRequirement(
            mode="creator",
            creator_urls=list(getattr(config, "XHS_CREATOR_ID_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )


class DouyinConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "douyin"
    index_url = "https://www.douyin.com"
    user_agent = utils.get_user_agent()
    login_cls = DouYinLogin

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.douyin import build_douyin_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_douyin_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="douyin",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_douyin_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    def _build_connector_for_health_check(self):
        from connectors.douyin import build_douyin_connector_from_legacy

        return build_douyin_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> DouyinCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return DouyinCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 15),
                sort_type=str(config.SEARCH_SORT_TYPE),
                publish_time=str(config.PUBLISH_TIME_TYPE),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return DouyinCrawlRequirement(
                mode="detail",
                aweme_ids=list(getattr(config, "DY_SPECIFIED_ID_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return DouyinCrawlRequirement(
            mode="creator",
            creator_ids=list(getattr(config, "DY_CREATOR_ID_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )


class KuaishouConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "kuaishou"
    index_url = "https://www.kuaishou.com"
    user_agent = utils.get_user_agent()
    login_cls = KuaishouLogin

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.kuaishou import build_kuaishou_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_kuaishou_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="kuaishou",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_kuaishou_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    def _build_connector_for_health_check(self):
        from connectors.kuaishou import build_kuaishou_connector_from_legacy

        return build_kuaishou_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> KuaishouCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return KuaishouCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return KuaishouCrawlRequirement(
                mode="detail",
                video_ids=list(getattr(config, "KS_SPECIFIED_ID_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return KuaishouCrawlRequirement(
            mode="creator",
            creator_ids=list(getattr(config, "KS_CREATOR_ID_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )


class BilibiliConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "bilibili"
    index_url = "https://www.bilibili.com"
    user_agent = utils.get_user_agent()
    login_cls = BilibiliLogin

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.bilibili import build_bilibili_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_bilibili_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="bilibili",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_bilibili_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    def _build_connector_for_health_check(self):
        from connectors.bilibili import build_bilibili_connector_from_legacy

        return build_bilibili_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> BilibiliCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return BilibiliCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return BilibiliCrawlRequirement(
                mode="detail",
                video_ids=list(getattr(config, "BILI_SPECIFIED_ID_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return BilibiliCrawlRequirement(
            mode="creator",
            creator_ids=list(getattr(config, "BILI_CREATOR_ID_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )


class WeiboConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "weibo"
    index_url = "https://www.weibo.com"
    user_agent = utils.get_user_agent()
    login_cls = WeiboLogin

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.weibo import build_weibo_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_weibo_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="weibo",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_weibo_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    def _build_connector_for_health_check(self):
        from connectors.weibo import build_weibo_connector_from_legacy

        return build_weibo_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> WeiboCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return WeiboCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 10),
                search_type=str(config.WEIBO_SEARCH_TYPE or "default"),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return WeiboCrawlRequirement(
                mode="detail",
                note_ids=list(getattr(config, "WEIBO_SPECIFIED_ID_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return WeiboCrawlRequirement(
            mode="creator",
            creator_ids=list(getattr(config, "WEIBO_CREATOR_ID_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )


class TiebaConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "tieba"
    index_url = "https://tieba.baidu.com"
    user_agent = utils.get_user_agent()
    login_cls = BaiduTieBaLogin
    uses_stealth_script = False

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.tieba import build_tieba_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_tieba_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="tieba",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_tieba_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    def _build_connector_for_health_check(self):
        from connectors.tieba import build_tieba_connector_from_legacy

        return build_tieba_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> TiebaCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return TiebaCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 10),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return TiebaCrawlRequirement(
                mode="detail",
                note_ids=list(getattr(config, "TIEBA_SPECIFIED_ID_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return TiebaCrawlRequirement(
            mode="creator",
            creator_urls=list(getattr(config, "TIEBA_CREATOR_URL_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )


class ZhihuConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "zhihu"
    index_url = "https://www.zhihu.com"
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    login_cls = ZhiHuLogin

    def _build_task_executor(self):
        from .task_executor import ExecutionServices
        from connectors.zhihu import build_zhihu_connector_from_legacy

        from .task_planner import TaskPlanner
        from .task_executor import TaskExecutor
        connector = build_zhihu_connector_from_legacy(self)

        return TaskExecutor(
            self,
            platform_code="zhihu",
            planner=TaskPlanner(connector),
            connector=connector,
            connector_factory=lambda: build_zhihu_connector_from_legacy(self),
            services=ExecutionServices(
                crawl_state_service=self.crawl_state_service,
                event_service=self.event_service,
                normalized_content_service=self.normalized_content_service,
                raw_record_service=self.raw_record_service,
            ),
        )

    def _build_connector_for_health_check(self):
        from connectors.zhihu import build_zhihu_connector_from_legacy

        return build_zhihu_connector_from_legacy(self)

    def _build_requirement_from_runtime_config(self) -> ZhihuCrawlRequirement:
        mode = str(config.CRAWLER_TYPE)
        if mode == "search":
            return ZhihuCrawlRequirement(
                mode="search",
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        if mode == "detail":
            return ZhihuCrawlRequirement(
                mode="detail",
                note_urls=list(getattr(config, "ZHIHU_SPECIFIED_ID_LIST", [])),
                include_comments=bool(config.ENABLE_GET_COMMENTS),
                comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
            )
        return ZhihuCrawlRequirement(
            mode="creator",
            creator_urls=list(getattr(config, "ZHIHU_CREATOR_URL_LIST", [])),
            include_comments=bool(config.ENABLE_GET_COMMENTS),
            comment_limit=int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
        )
