# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/weibo/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/23 15:41
# @Desc    : Weibo crawler main workflow code

import asyncio
import os
import uuid
# import random  # Removed as we now use fixed config.CRAWLER_MAX_SLEEP_SEC intervals
from asyncio import Task
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from application.services.crawl_state_service import CrawlStateService
from application.services.event_service import EventService
from application.services.normalized_content_service import NormalizedContentService
from application.services.raw_record_service import RawRecordService
from application.services.weibo_task_executor import WeiboTaskExecutor
from base.base_crawler import AbstractCrawler
from connectors.weibo.errors import WeiboDataFetchError
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import weibo as weibo_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import WeiboClient
from .exception import DataFetchError
from .field import SearchType
from .help import filter_search_result_card
from .login import WeiboLogin
from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import WeiboCrawlRequirement


class WeiboCrawler(AbstractCrawler):
    context_page: Page
    wb_client: WeiboClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self):
        self.index_url = "https://www.weibo.com"
        self.mobile_index_url = "https://m.weibo.cn"
        self.user_agent = utils.get_user_agent()
        self.mobile_user_agent = utils.get_mobile_user_agent()
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh
        self._platform_http_proxy: Optional[str] = None
        self.crawl_state_service = CrawlStateService()
        self.event_service = EventService()
        self.normalized_content_service = NormalizedContentService()
        self.raw_record_service = RawRecordService()
        self.task_executor = WeiboTaskExecutor(
            self,
            crawl_state_service=self.crawl_state_service,
            event_service=self.event_service,
            normalized_content_service=self.normalized_content_service,
            raw_record_service=self.raw_record_service,
        )

    @staticmethod
    def _weibo_task_executor_mode() -> str:
        return str(getattr(config, "WEIBO_PLATFORM_RUNNER_MODE", "legacy")).strip().lower()

    def _use_task_executor_for(self, capability: str) -> bool:
        mode = self._weibo_task_executor_mode()
        if mode == "all":
            return True
        if mode == capability:
            return True
        toggle_map = {
            "search": getattr(config, "ENABLE_WEIBO_CONNECTOR_SEARCH", False),
            "detail": getattr(config, "ENABLE_WEIBO_CONNECTOR_DETAIL", False),
            "comments": getattr(config, "ENABLE_WEIBO_CONNECTOR_COMMENTS", False),
            "creator": getattr(config, "ENABLE_WEIBO_CONNECTOR_CREATOR", False),
        }
        return bool(toggle_map.get(capability, False))

    async def execute_platform_task(self, task: CrawlTask) -> dict[str, Any]:
        """Execute a persisted Weibo crawl task through the platform task executor."""
        return await self.task_executor.execute(task)

    async def execute_platform_requirement(self, requirement: WeiboCrawlRequirement) -> dict[str, Any]:
        """Execute a requirement-driven Weibo crawl plan through the platform task executor."""
        return await self.task_executor.execute_requirement(requirement)

    async def start_with_requirement(self, requirement: WeiboCrawlRequirement) -> dict[str, Any]:
        """Boot runtime resources and execute a requirement-driven Weibo crawl."""
        async with async_playwright() as playwright:
            await self._initialize_runtime(playwright)
            return await self.execute_platform_requirement(requirement)

    async def start(self):
        async with async_playwright() as playwright:
            await self._initialize_runtime(playwright)

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for video and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass
            utils.logger.info("[WeiboCrawler.start] Weibo Crawler finished ...")

    async def _initialize_runtime(self, playwright: Playwright) -> None:
        """Prepare proxy, browser, page, client, and login state for Weibo crawling."""
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)
        self._platform_http_proxy = httpx_proxy_format

        if config.ENABLE_CDP_MODE:
            utils.logger.info("[WeiboCrawler] Launching browser with CDP mode")
            self.browser_context = await self.launch_browser_with_cdp(
                playwright,
                playwright_proxy_format,
                self.mobile_user_agent,
                headless=config.CDP_HEADLESS,
            )
        else:
            utils.logger.info("[WeiboCrawler] Launching browser with standard mode")
            chromium = playwright.chromium
            self.browser_context = await self.launch_browser(chromium, None, self.mobile_user_agent, headless=config.HEADLESS)
            await self.browser_context.add_init_script(path="libs/stealth.min.js")

        self.context_page = await self.browser_context.new_page()
        await self.context_page.goto(self.index_url)
        await asyncio.sleep(2)

        self.wb_client = await self.create_weibo_client(httpx_proxy_format)
        if not await self.wb_client.pong():
            login_obj = WeiboLogin(
                login_type=config.LOGIN_TYPE,
                login_phone="",
                browser_context=self.browser_context,
                context_page=self.context_page,
                cookie_str=config.COOKIES,
            )
            await login_obj.begin()
            utils.logger.info("[WeiboCrawler.start] redirect weibo mobile homepage and update cookies on mobile platform")
            await self.context_page.goto(self.mobile_index_url)
            await asyncio.sleep(3)
            await self.wb_client.update_cookies(
                browser_context=self.browser_context,
                urls=[self.mobile_index_url]
            )

    async def search(self):
        """
        search weibo note with keywords
        :return:
        """
        if self._use_task_executor_for("search"):
            await self.search_with_task_executor()
            return
        utils.logger.info("[WeiboCrawler.search] Begin search weibo keywords")
        weibo_limit_count = 10  # weibo limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < weibo_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = weibo_limit_count
        start_page = config.START_PAGE

        # Set the search type based on the configuration for weibo
        if config.WEIBO_SEARCH_TYPE == "default":
            search_type = SearchType.DEFAULT
        elif config.WEIBO_SEARCH_TYPE == "real_time":
            search_type = SearchType.REAL_TIME
        elif config.WEIBO_SEARCH_TYPE == "popular":
            search_type = SearchType.POPULAR
        elif config.WEIBO_SEARCH_TYPE == "video":
            search_type = SearchType.VIDEO
        else:
            utils.logger.error(f"[WeiboCrawler.search] Invalid WEIBO_SEARCH_TYPE: {config.WEIBO_SEARCH_TYPE}")
            return

        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[WeiboCrawler.search] Current search keyword: {keyword}")
            page = 1
            while (page - start_page + 1) * weibo_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[WeiboCrawler.search] Skip page: {page}")
                    page += 1
                    continue
                utils.logger.info(f"[WeiboCrawler.search] search weibo keyword: {keyword}, page: {page}")
                search_res = await self.wb_client.get_note_by_keyword(keyword=keyword, page=page, search_type=search_type)
                note_id_list: List[str] = []
                note_list = filter_search_result_card(search_res.get("cards"))
                # If full text fetching is enabled, batch get full text of posts
                note_list = await self.batch_get_notes_full_text(note_list)
                for note_item in note_list:
                    if note_item:
                        mblog: Dict = note_item.get("mblog")
                        if mblog:
                            note_id_list.append(mblog.get("id"))
                            await weibo_store.update_weibo_note(note_item)
                            await self.get_note_images(mblog)

                page += 1

                # Sleep after page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                await self.batch_get_notes_comments(note_id_list)

    async def search_with_task_executor(self):
        """Search Weibo through the task executor while keeping legacy storage flow."""
        utils.logger.info("[WeiboCrawler.search_with_task_executor] Begin search weibo keywords via task executor")
        weibo_limit_count = 10
        if config.CRAWLER_MAX_NOTES_COUNT < weibo_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = weibo_limit_count
        start_page = config.START_PAGE
        search_type = SearchType.DEFAULT
        if config.WEIBO_SEARCH_TYPE == "real_time":
            search_type = SearchType.REAL_TIME
        elif config.WEIBO_SEARCH_TYPE == "popular":
            search_type = SearchType.POPULAR
        elif config.WEIBO_SEARCH_TYPE == "video":
            search_type = SearchType.VIDEO
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[WeiboCrawler.search_with_task_executor] Current search keyword: {keyword}")
            page = 1
            while (page - start_page + 1) * weibo_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[WeiboCrawler.search_with_task_executor] Skip page: {page}")
                    page += 1
                    continue
                try:
                    result = await self.execute_platform_task(
                        self._new_platform_task(
                            task_type="search",
                            params={"keyword": keyword, "page": page, "search_type": search_type.value},
                        )
                    )
                except WeiboDataFetchError as exc:
                    utils.logger.error(
                        f"[WeiboCrawler.search_with_task_executor] search weibo keyword: {keyword}, page: {page} failed, err: {exc}"
                    )
                    break
                note_list = result.get("items", [])
                note_id_list: List[str] = []
                note_list = await self.batch_get_notes_full_text(note_list)
                for note_item in note_list:
                    if note_item:
                        mblog: Dict = note_item.get("mblog", {})
                        if mblog:
                            note_id = mblog.get("id")
                            if note_id:
                                note_id_list.append(note_id)
                            await weibo_store.update_weibo_note(note_item)
                            await self.get_note_images(mblog)
                page += 1
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(
                    f"[WeiboCrawler.search_with_task_executor] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}"
                )
                await self.batch_get_notes_comments(note_id_list)

    async def get_specified_notes(self):
        """
        get specified notes info
        :return:
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_note_info_task(note_id=note_id, semaphore=semaphore) for note_id in config.WEIBO_SPECIFIED_ID_LIST]
        video_details = await asyncio.gather(*task_list)
        for note_item in video_details:
            if note_item:
                await weibo_store.update_weibo_note(note_item)
        await self.batch_get_notes_comments(config.WEIBO_SPECIFIED_ID_LIST)

    async def get_note_info_task(self, note_id: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        """
        Get note detail task
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                if self._use_task_executor_for("detail"):
                    return await self.get_note_info_with_task_executor(note_id)
                result = await self.wb_client.get_note_info_by_id(note_id)

                # Sleep after fetching note details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.get_note_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}")

                return result
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None

    async def get_note_info_with_task_executor(self, note_id: str) -> Optional[Dict]:
        """Get note detail through the task executor."""
        try:
            result = await self.execute_platform_task(
                self._new_platform_task(task_type="detail", params={"note_id": note_id})
            )
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(
                f"[WeiboCrawler.get_note_info_with_task_executor] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}"
            )
            return result.get("note")
        except WeiboDataFetchError as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_info_with_task_executor] Get note detail error: {ex}")
            return None

    async def batch_get_notes_comments(self, note_id_list: List[str]):
        """
        batch get notes comments
        :param note_id_list:
        :return:
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[WeiboCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[WeiboCrawler.batch_get_notes_comments] note ids:{note_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_id in note_id_list:
            task = asyncio.create_task(self.get_note_comments(note_id, semaphore), name=note_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_note_comments(self, note_id: str, semaphore: asyncio.Semaphore):
        """
        get comment for note id
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                if self._use_task_executor_for("comments"):
                    await self.get_note_comments_with_task_executor(note_id)
                    return
                utils.logger.info(f"[WeiboCrawler.get_note_comments] begin get note_id: {note_id} comments ...")

                # Sleep before fetching comments
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.get_note_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_id}")

                await self.wb_client.get_note_all_comments(
                    note_id=note_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,  # Use fixed interval instead of random
                    callback=weibo_store.batch_update_weibo_note_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] get note_id: {note_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] may be been blocked, err:{e}")

    async def get_note_comments_with_task_executor(self, note_id: str):
        """Get Weibo comments through the task executor and keep legacy storage."""
        try:
            utils.logger.info(f"[WeiboCrawler.get_note_comments_with_task_executor] begin get note_id: {note_id} comments ...")
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(
                f"[WeiboCrawler.get_note_comments_with_task_executor] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_id}"
            )
            result = await self.execute_platform_task(
                self._new_platform_task(
                    task_type="comments",
                    params={"note_id": note_id, "limit": config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES},
                )
            )
            comments = result.get("comments", [])
            if comments:
                await weibo_store.batch_update_weibo_note_comments(note_id, comments)
        except WeiboDataFetchError as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_comments_with_task_executor] get note_id: {note_id} comment error: {ex}")

    async def get_note_images(self, mblog: Dict):
        """
        get note images
        :param mblog:
        :return:
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[WeiboCrawler.get_note_images] Crawling image mode is not enabled")
            return

        pics: List = mblog.get("pics")
        if not pics:
            return
        for pic in pics:
            if isinstance(pic, str):
                url = pic
                pid = url.split("/")[-1].split(".")[0]
            elif isinstance(pic, dict):
                url = pic.get("url")
                pid = pic.get("pid", "")
            else:
                continue
            if not url:
                continue
            content = await self.wb_client.get_note_image(url)
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(f"[WeiboCrawler.get_note_images] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching image")
            if content != None:
                extension_file_name = url.split(".")[-1]
                await weibo_store.update_weibo_note_image(pid, content, extension_file_name)

    async def get_creators_and_notes(self) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        if self._use_task_executor_for("creator"):
            await self.get_creators_and_notes_with_task_executor()
            return
        utils.logger.info("[WeiboCrawler.get_creators_and_notes] Begin get weibo creators")
        for user_id in config.WEIBO_CREATOR_ID_LIST:
            createor_info_res: Dict = await self.wb_client.get_creator_info_by_id(creator_id=user_id)
            if createor_info_res:
                createor_info: Dict = createor_info_res.get("userInfo", {})
                utils.logger.info(f"[WeiboCrawler.get_creators_and_notes] creator info: {createor_info}")
                if not createor_info:
                    raise DataFetchError("Get creator info error")
                await weibo_store.save_creator(user_id, user_info=createor_info)

                # Create a wrapper callback to get full text before saving data
                async def save_notes_with_full_text(note_list: List[Dict]):
                    # If full text fetching is enabled, batch get full text first
                    updated_note_list = await self.batch_get_notes_full_text(note_list)
                    await weibo_store.batch_update_weibo_notes(updated_note_list)

                # Get all note information of the creator
                all_notes_list = await self.wb_client.get_all_notes_by_creator_id(
                    creator_id=user_id,
                    container_id=f"107603{user_id}",
                    crawl_interval=0,
                    callback=save_notes_with_full_text,
                )

                note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes_list if note_item.get("mblog", {}).get("id")]
                await self.batch_get_notes_comments(note_ids)

            else:
                utils.logger.error(f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_id:{user_id}")

    async def get_creators_and_notes_with_task_executor(self) -> None:
        """Fetch creator info and notes through the Weibo task executor."""
        utils.logger.info("[WeiboCrawler.get_creators_and_notes_with_task_executor] Begin get weibo creators")
        for user_id in config.WEIBO_CREATOR_ID_LIST:
            try:
                creator_result = await self.execute_platform_task(
                    self._new_platform_task(task_type="creator", params={"creator_id": user_id})
                )
            except WeiboDataFetchError as exc:
                utils.logger.error(
                    f"[WeiboCrawler.get_creators_and_notes_with_task_executor] get creator info error, creator_id:{user_id}, err:{exc}"
                )
                continue
            creator_info = creator_result.get("creator", {})
            if creator_info:
                await weibo_store.save_creator(user_id, user_info=creator_info)
            cursor = ""
            all_notes: List[Dict] = []
            while True:
                try:
                    contents_result = await self.execute_platform_task(
                        self._new_platform_task(
                            task_type="creator_contents",
                            params={"creator_id": user_id, "cursor": cursor},
                        )
                    )
                except WeiboDataFetchError as exc:
                    utils.logger.error(
                        f"[WeiboCrawler.get_creators_and_notes_with_task_executor] get creator notes error, creator_id:{user_id}, err:{exc}"
                    )
                    break
                note_list = contents_result.get("items", [])
                if not note_list:
                    break
                updated_note_list = await self.batch_get_notes_full_text(note_list)
                await weibo_store.batch_update_weibo_notes(updated_note_list)
                all_notes.extend(updated_note_list)
                if not contents_result.get("has_more"):
                    break
                cursor = str(contents_result.get("next_cursor") or "")
                if not cursor:
                    break
            note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes if note_item.get("mblog", {}).get("id")]
            await self.batch_get_notes_comments(note_ids)

    async def create_weibo_client(self, httpx_proxy: Optional[str]) -> WeiboClient:
        """Create xhs client"""
        utils.logger.info("[WeiboCrawler.create_weibo_client] Begin create weibo API client ...")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies(urls=[self.mobile_index_url]))
        weibo_client_obj = WeiboClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": utils.get_mobile_user_agent(),
                "Cookie": cookie_str,
                "Origin": "https://m.weibo.cn",
                "Referer": "https://m.weibo.cn",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return weibo_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[WeiboCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
                channel="chrome",  # Use system's Chrome stable version
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        Launch browser with CDP mode
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[WeiboCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[WeiboCrawler] CDP mode startup failed, falling back to standard mode: {e}")
            # Fallback to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def get_note_full_text(self, note_item: Dict) -> Dict:
        """
        Get full text content of a post
        If the post content is truncated (isLongText=True), request the detail API to get complete content
        :param note_item: Post data, contains mblog field
        :return: Updated post data
        """
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_item

        mblog = note_item.get("mblog", {})
        if not mblog:
            return note_item

        # Check if it's a long text
        is_long_text = mblog.get("isLongText", False)
        if not is_long_text:
            return note_item

        note_id = mblog.get("id")
        if not note_id:
            return note_item

        try:
            utils.logger.info(f"[WeiboCrawler.get_note_full_text] Fetching full text for note: {note_id}")
            full_note = await self.wb_client.get_note_info_by_id(note_id)
            if full_note and full_note.get("mblog"):
                # Replace original content with complete content
                note_item["mblog"] = full_note["mblog"]
                utils.logger.info(f"[WeiboCrawler.get_note_full_text] Successfully fetched full text for note: {note_id}")

            # Sleep after request to avoid rate limiting
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
        except DataFetchError as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Failed to fetch full text for note {note_id}: {ex}")
        except Exception as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Unexpected error for note {note_id}: {ex}")

        return note_item

    async def batch_get_notes_full_text(self, note_list: List[Dict]) -> List[Dict]:
        """
        Batch get full text content of posts
        :param note_list: List of posts
        :return: Updated list of posts
        """
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_list

        result = []
        for note_item in note_list:
            updated_note = await self.get_note_full_text(note_item)
            result.append(updated_note)
        return result

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[WeiboCrawler.close] Browser context closed ...")
    def _new_platform_task(self, *, task_type: str, params: Dict[str, Any]) -> CrawlTask:
        return CrawlTask(
            task_id=f"wb-runtime-{task_type}-{uuid.uuid4().hex[:12]}",
            platform_code="weibo",
            task_type=task_type,
            status="planned",
            params=params,
        )
