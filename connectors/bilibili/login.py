from __future__ import annotations

import asyncio
import functools
import sys
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractLogin
from tools import utils


class BilibiliLogin(AbstractLogin):
    def __init__(self, login_type: str, browser_context: BrowserContext, context_page: Page, login_phone: Optional[str] = "", cookie_str: str = ""):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    async def begin(self):
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("Invalid Bilibili login type")

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self) -> bool:
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        return bool(cookie_dict.get("SESSDATA", "") or cookie_dict.get("DedeUserID"))

    async def login_by_qrcode(self):
        await self.context_page.locator("xpath=//div[@class='right-entry__outside go-login-btn']//div").click()
        await asyncio.sleep(1)
        base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector="//div[@class='login-scan-box']//img")
        if not base64_qrcode_img:
            sys.exit()
        asyncio.get_running_loop().run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        try:
            await self.check_login_state()
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    async def login_by_mobile(self):
        return None

    async def login_by_cookies(self):
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".bilibili.com", "path": "/"}])
