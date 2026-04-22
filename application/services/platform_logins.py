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


class KuaishouLogin(AbstractLogin):
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
            raise ValueError("Invalid Kuaishou login type")

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self) -> bool:
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        return bool(cookie_dict.get("passToken"))

    async def login_by_qrcode(self):
        await self.context_page.locator("xpath=//p[text()='登录']").click()
        base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector="//div[@class='qrcode-img']//img")
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
            await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".kuaishou.com", "path": "/"}])


class WeiboLogin(AbstractLogin):
    def __init__(self, login_type: str, browser_context: BrowserContext, context_page: Page, login_phone: Optional[str] = "", cookie_str: str = ""):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str
        self.weibo_sso_login_url = "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog"

    async def begin(self):
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("Invalid Weibo login type")

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self, no_logged_in_session: str) -> bool:
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        return bool(cookie_dict.get("SSOLoginState") or cookie_dict.get("WBPSESS") != no_logged_in_session)

    async def login_by_qrcode(self):
        await self.context_page.goto(self.weibo_sso_login_url)
        base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector="xpath=//img[@class='w-full h-full']")
        if not base64_qrcode_img:
            sys.exit()
        asyncio.get_running_loop().run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        try:
            await self.check_login_state(cookie_dict.get("WBPSESS"))
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    async def login_by_mobile(self):
        return None

    async def login_by_cookies(self):
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".weibo.cn", "path": "/"}])


class BaiduTieBaLogin(AbstractLogin):
    def __init__(self, login_type: str, browser_context: BrowserContext, context_page: Page, login_phone: Optional[str] = "", cookie_str: str = ""):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self) -> bool:
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        return bool(cookie_dict.get("STOKEN") or cookie_dict.get("PTOKEN"))

    async def begin(self):
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("Invalid Tieba login type")

    async def login_by_mobile(self):
        return None

    async def login_by_qrcode(self):
        qrcode_img_selector = "xpath=//img[@class='tang-pass-qrcode-img']"
        base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector=qrcode_img_selector)
        if not base64_qrcode_img:
            await asyncio.sleep(0.5)
            await self.context_page.locator("xpath=//li[@class='u_login']").click()
            base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector=qrcode_img_selector)
            if not base64_qrcode_img:
                sys.exit()
        asyncio.get_running_loop().run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        try:
            await self.check_login_state()
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    async def login_by_cookies(self):
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".baidu.com", "path": "/"}])


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


class ZhiHuLogin(AbstractLogin):
    def __init__(self, login_type: str, browser_context: BrowserContext, context_page: Page, login_phone: Optional[str] = "", cookie_str: str = ""):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self) -> bool:
        _, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        return bool(cookie_dict.get("z_c0"))

    async def begin(self):
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("Invalid Zhihu login type")

    async def login_by_mobile(self):
        return None

    async def login_by_qrcode(self):
        base64_qrcode_img = await utils.find_qrcode_img_from_canvas(self.context_page, canvas_selector="canvas.Qrcode-qrcode")
        if not base64_qrcode_img:
            sys.exit()
        asyncio.get_running_loop().run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        try:
            await self.check_login_state()
        except RetryError:
            sys.exit()
        await asyncio.sleep(5)

    async def login_by_cookies(self):
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{"name": key, "value": value, "domain": ".zhihu.com", "path": "/"}])
