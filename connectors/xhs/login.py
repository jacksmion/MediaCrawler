from __future__ import annotations

import asyncio
import functools
import sys
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from runtime.cache import CacheFactory
from connectors.base.login import AbstractLogin
from tools import utils


class XiaoHongShuLogin(AbstractLogin):
    def __init__(self, login_type: str, browser_context: BrowserContext, context_page: Page, login_phone: Optional[str] = "", cookie_str: str = ""):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self, no_logged_in_session: str) -> bool:
        try:
            if await self.context_page.is_visible("xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']", timeout=500):
                return True
        except Exception:
            pass
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        current_web_session = cookie_dict.get("web_session")
        return bool(current_web_session and current_web_session != no_logged_in_session)

    async def begin(self):
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("Invalid XHS login type")

    async def login_by_mobile(self):
        await asyncio.sleep(1)
        try:
            await (await self.context_page.wait_for_selector("xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button", timeout=5000)).click()
            await (await self.context_page.wait_for_selector('xpath=//div[@class="login-container"]//div[@class="other-method"]/div[1]', timeout=5000)).click()
        except Exception:
            pass
        await asyncio.sleep(1)
        login_container_ele = await self.context_page.wait_for_selector("div.login-container")
        await (await login_container_ele.query_selector("label.phone > input")).fill(self.login_phone)
        await asyncio.sleep(0.5)
        await (await login_container_ele.query_selector("label.auth-code > span")).click()
        sms_code_input_ele = await login_container_ele.query_selector("label.auth-code > input")
        submit_btn_ele = await login_container_ele.query_selector("div.input-container > button")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 120
        no_logged_in_session = ""
        while max_get_sms_code_time > 0:
            await asyncio.sleep(1)
            sms_code_value = cache_client.get(f"xhs_{self.login_phone}")
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue
            _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
            no_logged_in_session = cookie_dict.get("web_session")
            await sms_code_input_ele.fill(value=sms_code_value.decode())
            await asyncio.sleep(0.5)
            await self.context_page.locator("xpath=//div[@class='agreements']//*[local-name()='svg']").click()
            await asyncio.sleep(0.5)
            await submit_btn_ele.click()
            break
        try:
            await self.check_login_state(no_logged_in_session)
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    async def login_by_qrcode(self):
        qrcode_img_selector = "xpath=//img[@class='qrcode-img']"
        base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector=qrcode_img_selector)
        if not base64_qrcode_img:
            await asyncio.sleep(0.5)
            await self.context_page.locator("xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button").click()
            base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector=qrcode_img_selector)
            if not base64_qrcode_img:
                sys.exit()
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        asyncio.get_running_loop().run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        try:
            await self.check_login_state(cookie_dict.get("web_session"))
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    async def login_by_cookies(self):
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            if key == "web_session":
                await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".xiaohongshu.com", "path": "/"}])
