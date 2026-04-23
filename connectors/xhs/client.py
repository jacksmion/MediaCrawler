from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

import config
from connectors.base.client import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils
from tools.httpx_util import make_async_client

from .client_exceptions import DataFetchError, IPBlockError, NoteNotFoundError
from .extractor import XiaoHongShuExtractor
from .fields import SearchNoteType, SearchSortType
from .helpers import get_search_id
from .playwright_sign import sign_with_playwright

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool


class XiaoHongShuClient(AbstractApiClient, ProxyRefreshMixin):
    def __init__(
        self,
        timeout: int = 60,
        proxy: str | None = None,
        *,
        headers: dict[str, str],
        playwright_page: Page,
        cookie_dict: dict[str, str],
        proxy_ip_pool: ProxyIpPool | None = None,
    ) -> None:
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://edith.xiaohongshu.com"
        self._domain = "https://www.xiaohongshu.com"
        self.IP_ERROR_STR = "Network connection error, please check network settings or restart"
        self.IP_ERROR_CODE = 300012
        self.NOTE_NOT_FOUND_CODE = -510000
        self.NOTE_ABNORMAL_CODE = -510001
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._extractor = XiaoHongShuExtractor()
        self.init_proxy_pool(proxy_ip_pool)

    async def _pre_headers(self, url: str, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, str]:
        a1_value = self.cookie_dict.get("a1", "")
        if params is not None:
            data = params
            method = "GET"
        elif payload is not None:
            data = payload
            method = "POST"
        else:
            raise ValueError("params or payload is required")
        signs = await sign_with_playwright(page=self.playwright_page, uri=url, data=data, a1=a1_value, method=method)
        self.headers.update(
            {
                "X-S": signs["x-s"],
                "X-T": signs["x-t"],
                "x-S-Common": signs["x-s-common"],
                "X-B3-Traceid": signs["x-b3-traceid"],
            }
        )
        return self.headers

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1), retry=retry_if_not_exception_type(NoteNotFoundError))
    async def request(self, method: str, url: str, **kwargs) -> str | Any:
        await self._refresh_proxy_if_expired()
        return_response = kwargs.pop("return_response", False)
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)
        if response.status_code in (471, 461):
            verify_type = response.headers.get("Verifytype", "Unknown")
            verify_uuid = response.headers.get("Verifyuuid", "Unknown")
            raise Exception(f"CAPTCHA appeared, request failed, Verifytype: {verify_type}, Verifyuuid: {verify_uuid}, Response: {response.text}")
        if return_response:
            return response.text
        data = response.json()
        if data["success"]:
            return data.get("data", data.get("success", {}))
        if data["code"] == self.IP_ERROR_CODE:
            raise IPBlockError(self.IP_ERROR_STR)
        if data["code"] in (self.NOTE_NOT_FOUND_CODE, self.NOTE_ABNORMAL_CODE):
            raise NoteNotFoundError(f"Note not found or abnormal, code: {data['code']}")
        raise DataFetchError(data.get("msg", None) or response.text)

    async def get(self, uri: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request(method="GET", url=f"{self._host}{uri}", headers=await self._pre_headers(uri, params), params=params)

    async def post(self, uri: str, data: dict[str, Any], **kwargs) -> dict[str, Any]:
        return await self.request(
            method="POST",
            url=f"{self._host}{uri}",
            data=json.dumps(data, separators=(",", ":"), ensure_ascii=False),
            headers=await self._pre_headers(uri, payload=data),
            **kwargs,
        )

    async def get_note_media(self, url: str) -> bytes | None:
        await self._refresh_proxy_if_expired()
        async with make_async_client(proxy=self.proxy) as client:
            try:
                response = await client.request("GET", url, timeout=self.timeout)
                response.raise_for_status()
                return response.content if response.reason_phrase == "OK" else None
            except httpx.HTTPError as exc:
                utils.logger.error(f"[XiaoHongShuClient.get_aweme_media] {exc.__class__.__name__} for {exc.request.url} - {exc}")
                return None

    async def query_self(self) -> dict[str, Any] | None:
        uri = "/api/sns/web/v1/user/selfinfo"
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.get(f"{self._host}{uri}", headers=await self._pre_headers(uri, params={}))
            return response.json() if response.status_code == 200 else None

    async def pong(self) -> bool:
        try:
            self_info = await self.query_self()
            return bool(self_info and self_info.get("data", {}).get("result", {}).get("success"))
        except Exception as exc:
            utils.logger.error(f"[XiaoHongShuClient.pong] Check login state failed: {exc}, and try to login again...")
            return False

    async def update_cookies(self, browser_context: BrowserContext) -> None:
        cookie_str, cookie_dict = utils.convert_cookies(await browser_context.cookies())
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def get_note_by_keyword(
        self,
        keyword: str,
        search_id: str = get_search_id(),
        page: int = 1,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
    ) -> dict[str, Any]:
        return await self.post(
            "/api/sns/web/v1/search/notes",
            {
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
                "search_id": search_id,
                "sort": sort.value,
                "note_type": note_type.value,
            },
        )

    async def get_note_by_id(self, note_id: str, xsec_source: str, xsec_token: str) -> dict[str, Any]:
        if xsec_source == "":
            xsec_source = "pc_search"
        res = await self.post(
            "/api/sns/web/v1/feed",
            {
                "source_note_id": note_id,
                "image_formats": ["jpg", "webp", "avif"],
                "extra": {"need_body_topic": 1},
                "xsec_source": xsec_source,
                "xsec_token": xsec_token,
            },
        )
        if res and res.get("items"):
            return res["items"][0]["note_card"]
        return {}

    async def get_note_comments(self, note_id: str, xsec_token: str, cursor: str = "") -> dict[str, Any]:
        return await self.get(
            "/api/sns/web/v2/comment/page",
            {
                "note_id": note_id,
                "cursor": cursor,
                "top_comment_id": "",
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token,
            },
        )

    async def get_note_sub_comments(self, note_id: str, root_comment_id: str, xsec_token: str, num: int = 10, cursor: str = "") -> dict[str, Any]:
        return await self.get(
            "/api/sns/web/v2/comment/sub/page",
            {
                "note_id": note_id,
                "root_comment_id": root_comment_id,
                "num": str(num),
                "cursor": cursor,
                "image_formats": "jpg,webp,avif",
                "top_comment_id": "",
                "xsec_token": xsec_token,
            },
        )

    async def get_note_all_comments(
        self,
        note_id: str,
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback=None,
        max_count: int = 10,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        comments_has_more = True
        comments_cursor = ""
        while comments_has_more and len(result) < max_count:
            comments_res = await self.get_note_comments(note_id=note_id, xsec_token=xsec_token, cursor=comments_cursor)
            comments_has_more = comments_res.get("has_more", False)
            comments_cursor = comments_res.get("cursor", "")
            comments = comments_res.get("comments", [])
            if config.COMMENT_TIME_FILTER_H > 0:
                now_ts_ms = utils.get_current_timestamp()
                threshold_ts_ms = now_ts_ms - (config.COMMENT_TIME_FILTER_H * 3600 * 1000)
                comments = [comment for comment in comments if comment.get("create_time", 0) >= threshold_ts_ms]
                if not comments:
                    continue
            if len(result) + len(comments) > max_count:
                comments = comments[: max_count - len(result)]
            if callback:
                await callback(note_id, comments)
            await asyncio.sleep(crawl_interval)
            result.extend(comments)
            result.extend(
                await self.get_comments_all_sub_comments(
                    comments=comments,
                    xsec_token=xsec_token,
                    crawl_interval=crawl_interval,
                    callback=callback,
                )
            )
        return result

    async def get_comments_all_sub_comments(
        self,
        comments: list[dict[str, Any]],
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback=None,
    ) -> list[dict[str, Any]]:
        if not config.ENABLE_GET_SUB_COMMENTS:
            return []
        result: list[dict[str, Any]] = []
        for comment in comments:
            try:
                note_id = comment.get("note_id")
                sub_comments = comment.get("sub_comments")
                if sub_comments and callback:
                    await callback(note_id, sub_comments)
                if not comment.get("sub_comment_has_more"):
                    continue
                root_comment_id = comment.get("id")
                sub_comment_cursor = comment.get("sub_comment_cursor")
                while comment.get("sub_comment_has_more"):
                    try:
                        comments_res = await self.get_note_sub_comments(
                            note_id=note_id,
                            root_comment_id=root_comment_id,
                            xsec_token=xsec_token,
                            num=10,
                            cursor=sub_comment_cursor,
                        )
                        if comments_res is None or "comments" not in comments_res:
                            break
                        comment["sub_comment_has_more"] = comments_res.get("has_more", False)
                        sub_comment_cursor = comments_res.get("cursor", "")
                        page_comments = comments_res["comments"]
                        if callback:
                            await callback(note_id, page_comments)
                        await asyncio.sleep(crawl_interval)
                        result.extend(page_comments)
                    except DataFetchError:
                        break
            except Exception:
                continue
        return result

    async def get_creator_info(self, user_id: str, xsec_token: str = "", xsec_source: str = "") -> dict[str, Any]:
        uri = f"/user/profile/{user_id}"
        if xsec_token and xsec_source:
            uri = f"{uri}?xsec_token={xsec_token}&xsec_source={xsec_source}"
        html_content = await self.request("GET", self._domain + uri, return_response=True, headers=self.headers)
        return self._extractor.extract_creator_info_from_html(html_content)

    async def get_notes_by_creator(
        self,
        creator: str,
        cursor: str,
        page_size: int = 30,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> dict[str, Any]:
        return await self.get(
            "/api/sns/web/v1/user_posted",
            {
                "num": page_size,
                "cursor": cursor,
                "user_id": creator,
                "xsec_token": xsec_token,
                "xsec_source": xsec_source,
            },
        )

    async def get_all_notes_by_creator(
        self,
        user_id: str,
        crawl_interval: float = 1.0,
        callback=None,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        notes_has_more = True
        notes_cursor = ""
        while notes_has_more and len(result) < config.CRAWLER_MAX_NOTES_COUNT:
            notes_res = await self.get_notes_by_creator(user_id, notes_cursor, xsec_token=xsec_token, xsec_source=xsec_source)
            if not notes_res or "notes" not in notes_res:
                break
            notes_has_more = notes_res.get("has_more", False)
            notes_cursor = notes_res.get("cursor", "")
            notes = notes_res["notes"]
            remaining = config.CRAWLER_MAX_NOTES_COUNT - len(result)
            if remaining <= 0:
                break
            notes_to_add = notes[:remaining]
            if callback:
                await callback(notes_to_add)
            result.extend(notes_to_add)
            await asyncio.sleep(crawl_interval)
        return result

    async def get_note_short_url(self, note_id: str) -> str:
        return await self.post("/api/sns/web/short_url", {"original_url": f"{self._domain}/discovery/item/{note_id}"}, return_response=True)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def get_note_by_id_from_html(self, note_id: str, xsec_source: str, xsec_token: str, enable_cookie: bool = False) -> dict[str, Any] | None:
        url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source={xsec_source}"
        copy_headers = self.headers.copy()
        if not enable_cookie:
            del copy_headers["Cookie"]
        html = await self.request(method="GET", url=url, return_response=True, headers=copy_headers)
        return self._extractor.extract_note_detail_from_html(note_id, html)
