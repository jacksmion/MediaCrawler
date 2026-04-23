# -*- coding: utf-8 -*-
#
# Connector-native crawler entrypoints used by CLI and API runtimes.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, BrowserType, Page, Playwright, async_playwright

import config
from runtime.browser import CDPBrowserManager
from runtime.proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from runtime.storage import init_storage_backends
from tools import utils
from connectors.bilibili.login import BilibiliLogin
from connectors.douyin.login import DouYinLogin
from connectors.kuaishou.login import KuaishouLogin
from connectors.tieba.login import BaiduTieBaLogin
from connectors.weibo.login import WeiboLogin
from connectors.xhs.login import XiaoHongShuLogin
from connectors.zhihu.login import ZhiHuLogin

from .requirement_mapper import build_requirement_from_runtime_config
from .contracts import AbstractCrawler
from .state_store import StateStore
from runtime.storage.persistence import uses_relational_backend
from connectors import build_connector_from_runtime


class ConnectorCrawlerBase(AbstractCrawler):
    platform_name: str
    index_url: str
    user_agent: str
    login_cls: type | None = None
    uses_stealth_script = True
    stealth_script_path = Path(__file__).resolve().parents[2] / "runtime" / "assets" / "scripts" / "stealth.min.js"

    def __init__(self) -> None:
        self.context_page: Page | None = None
        self.browser_context: BrowserContext | None = None
        self.cdp_manager: CDPBrowserManager | None = None
        self.ip_proxy_pool = None
        self._platform_http_proxy: str | None = None
        self.state_store = StateStore()
        self.task_executor = self._build_task_executor()

    def _build_task_executor(self):
        from .task_executor import TaskExecutor

        connector = self._build_runtime_connector()

        return TaskExecutor(
            self,
            platform_code=self.platform_name,
            connector=connector,
            connector_factory=self._build_runtime_connector,
            state_store=self.state_store,
        )

    def _build_requirement_from_runtime_config(self):
        return build_requirement_from_runtime_config(self.platform_name)

    def _build_connector_for_health_check(self):
        return self._build_runtime_connector()

    def _build_runtime_connector(self):
        return build_connector_from_runtime(self.platform_name, self)

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
                await self.browser_context.add_init_script(path=str(self.stealth_script_path))

        self.context_page = await self.browser_context.new_page()
        await self.context_page.goto(self.index_url)
        await self._after_page_ready(httpx_proxy_format)

        if not await self._is_authenticated():
            await self._login()
            await self._after_login()

    async def _ensure_persistence_ready(self) -> None:
        if uses_relational_backend():
            await init_storage_backends(config.SAVE_DATA_OPTION)

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


class DouyinConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "douyin"
    index_url = "https://www.douyin.com"
    user_agent = utils.get_user_agent()
    login_cls = DouYinLogin


class KuaishouConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "kuaishou"
    index_url = "https://www.kuaishou.com"
    user_agent = utils.get_user_agent()
    login_cls = KuaishouLogin


class BilibiliConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "bilibili"
    index_url = "https://www.bilibili.com"
    user_agent = utils.get_user_agent()
    login_cls = BilibiliLogin


class WeiboConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "weibo"
    index_url = "https://www.weibo.com"
    user_agent = utils.get_user_agent()
    login_cls = WeiboLogin


class TiebaConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "tieba"
    index_url = "https://tieba.baidu.com"
    user_agent = utils.get_user_agent()
    login_cls = BaiduTieBaLogin
    uses_stealth_script = False


class ZhihuConnectorCrawler(ConnectorCrawlerBase):
    platform_name = "zhihu"
    index_url = "https://www.zhihu.com"
    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    login_cls = ZhiHuLogin
