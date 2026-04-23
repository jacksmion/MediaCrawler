from __future__ import annotations

import asyncio
import functools
import sys
from typing import Optional

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractLogin
from cache.cache_factory import CacheFactory
from tools import utils


class DouYinLogin(AbstractLogin):
    def __init__(self, login_type: str, browser_context: BrowserContext, context_page: Page, login_phone: Optional[str] = "", cookie_str: Optional[str] = ""):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    async def begin(self):
        await self.popup_login_dialog()
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("Invalid Douyin login type")
        await asyncio.sleep(6)
        if "验证码中间页" in await self.context_page.title():
            await self.check_page_display_slider(move_step=3, slider_level="hard")
        try:
            await self.check_login_state()
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self):
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        for page in self.browser_context.pages:
            try:
                local_storage = await page.evaluate("() => window.localStorage")
                if local_storage.get("HasUserLogin", "") == "1":
                    return True
            except Exception:
                await asyncio.sleep(0.1)
        return cookie_dict.get("LOGIN_STATUS") == "1"

    async def popup_login_dialog(self):
        try:
            await self.context_page.wait_for_selector("xpath=//div[@id='login-panel-new']", timeout=10000)
        except Exception:
            await self.context_page.locator("xpath=//p[text() = '登录']").click()
            await asyncio.sleep(0.5)

    async def login_by_qrcode(self):
        base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector="xpath=//div[@id='animate_qrcode_container']//img")
        if not base64_qrcode_img:
            sys.exit()
        asyncio.get_running_loop().run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        await asyncio.sleep(2)

    async def login_by_mobile(self):
        await self.context_page.locator("xpath=//li[text() = '验证码登录']").click()
        await self.context_page.wait_for_selector("xpath=//article[@class='web-login-mobile-code']")
        await self.context_page.locator("xpath=//input[@placeholder='手机号']").fill(self.login_phone)
        await asyncio.sleep(0.5)
        await self.context_page.locator("xpath=//span[text() = '获取验证码']").click()
        await self.check_page_display_slider(move_step=10, slider_level="easy")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 120
        while max_get_sms_code_time > 0:
            await asyncio.sleep(1)
            sms_code_value = cache_client.get(f"dy_{self.login_phone}")
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue
            await self.context_page.locator("xpath=//input[@placeholder='请输入验证码']").fill(value=sms_code_value.decode())
            await asyncio.sleep(0.5)
            await self.context_page.locator("xpath=//button[@class='web-login-button']").click()
            break

    async def check_page_display_slider(self, move_step: int = 10, slider_level: str = "easy"):
        back_selector = "#captcha-verify-image"
        try:
            await self.context_page.wait_for_selector(selector=back_selector, state="visible", timeout=30000)
        except PlaywrightTimeoutError:
            return
        gap_selector = 'xpath=//*[@id="captcha_container"]/div/div[2]/img[2]'
        max_slider_try_times = 20
        while max_slider_try_times > 0:
            try:
                await self.move_slider(back_selector, gap_selector, move_step, slider_level)
                await asyncio.sleep(1)
                page_content = await self.context_page.content()
                if "操作过慢" in page_content or "提示重新操作" in page_content:
                    await self.context_page.click(selector="//a[contains(@class, 'secsdk_captcha_refresh')]")
                    continue
                await self.context_page.wait_for_selector(selector=back_selector, state="hidden", timeout=1000)
                return
            except Exception:
                await asyncio.sleep(1)
                max_slider_try_times -= 1
        sys.exit()

    async def move_slider(self, back_selector: str, gap_selector: str, move_step: int = 10, slider_level: str = "easy"):
        slide_back = str(await (await self.context_page.wait_for_selector(selector=back_selector, timeout=10000)).get_property("src"))
        gap_src = str(await (await self.context_page.wait_for_selector(selector=gap_selector, timeout=10000)).get_property("src"))
        distance = utils.Slide(gap=gap_src, bg=slide_back).discern()
        tracks = utils.get_tracks(distance, slider_level)
        tracks[-1] = tracks[-1] - (sum(tracks) - distance)
        element = await self.context_page.query_selector(gap_selector)
        bounding_box = await element.bounding_box()
        await self.context_page.mouse.move(bounding_box["x"] + bounding_box["width"] / 2, bounding_box["y"] + bounding_box["height"] / 2)
        x = bounding_box["x"] + bounding_box["width"] / 2
        await element.hover()
        await self.context_page.mouse.down()
        for track in tracks:
            await self.context_page.mouse.move(x + track, 0, steps=move_step)
            x += track
        await self.context_page.mouse.up()

    async def login_by_cookies(self):
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".douyin.com", "path": "/"}])
