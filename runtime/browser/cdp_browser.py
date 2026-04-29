# -*- coding: utf-8 -*-

import atexit
import asyncio
import os
import signal
import socket
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from playwright.async_api import Browser, BrowserContext, Playwright

import config
from tools import utils

from .browser_launcher import BrowserLauncher


class CDPBrowserManager:
    """Launch and manage a browser connected through CDP."""

    def __init__(self):
        self.launcher = BrowserLauncher()
        self.browser: Optional[Browser] = None
        self.browser_context: Optional[BrowserContext] = None
        self.debug_port: Optional[int] = None
        self._cleanup_registered = False

    def _register_cleanup_handlers(self):
        if self._cleanup_registered:
            return

        def sync_cleanup():
            if self.launcher and self.launcher.browser_process:
                utils.logger.info("[CDPBrowserManager] atexit: Cleaning up browser process")
                self.launcher.cleanup()

        atexit.register(sync_cleanup)

        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)

        def signal_handler(signum, frame):
            utils.logger.info(f"[CDPBrowserManager] Received signal {signum}, cleaning up browser process")
            if self.launcher and self.launcher.browser_process:
                self.launcher.cleanup()

            if signum == signal.SIGINT:
                if prev_sigint == signal.default_int_handler:
                    return prev_sigint(signum, frame)
                raise KeyboardInterrupt

            raise SystemExit(0)

        install_sigint = prev_sigint in (signal.default_int_handler, signal.SIG_DFL)
        install_sigterm = prev_sigterm == signal.SIG_DFL

        if install_sigint:
            signal.signal(signal.SIGINT, signal_handler)
        else:
            utils.logger.info("[CDPBrowserManager] SIGINT handler already exists, skipping registration to avoid override")

        if install_sigterm:
            signal.signal(signal.SIGTERM, signal_handler)
        else:
            utils.logger.info("[CDPBrowserManager] SIGTERM handler already exists, skipping registration to avoid override")

        self._cleanup_registered = True
        utils.logger.info("[CDPBrowserManager] Cleanup handlers registered")

    async def launch_and_connect(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict] = None,
        user_agent: Optional[str] = None,
        headless: bool = False,
        account_id: str = "",
    ) -> BrowserContext:
        try:
            browser_path = await self._get_browser_path()
            self.debug_port = self.launcher.find_available_port(config.CDP_DEBUG_PORT)
            await self._launch_browser(browser_path, headless, account_id=account_id)
            self._register_cleanup_handlers()
            await self._connect_via_cdp(playwright)
            browser_context = await self._create_browser_context(playwright_proxy, user_agent)
            self.browser_context = browser_context
            return browser_context
        except Exception as exc:
            utils.logger.error(f"[CDPBrowserManager] CDP browser launch failed: {exc}")
            await self.cleanup()
            raise

    async def _get_browser_path(self) -> str:
        if config.CUSTOM_BROWSER_PATH and os.path.isfile(config.CUSTOM_BROWSER_PATH):
            utils.logger.info(f"[CDPBrowserManager] Using custom browser path: {config.CUSTOM_BROWSER_PATH}")
            return config.CUSTOM_BROWSER_PATH

        browser_paths = self.launcher.detect_browser_paths()
        if not browser_paths:
            raise RuntimeError(
                "No available browser found. Please ensure Chrome or Edge browser is installed, "
                "or set CUSTOM_BROWSER_PATH in config file to specify browser path."
            )

        browser_path = browser_paths[0]
        browser_name, browser_version = self.launcher.get_browser_info(browser_path)
        utils.logger.info(f"[CDPBrowserManager] Detected browser: {browser_name} ({browser_version})")
        utils.logger.info(f"[CDPBrowserManager] Browser path: {browser_path}")
        return browser_path

    async def _test_cdp_connection(self, debug_port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                result = sock.connect_ex(("localhost", debug_port))
                if result == 0:
                    utils.logger.info(f"[CDPBrowserManager] CDP port {debug_port} is accessible")
                    return True
                utils.logger.warning(f"[CDPBrowserManager] CDP port {debug_port} is not accessible")
                return False
        except Exception as exc:
            utils.logger.warning(f"[CDPBrowserManager] CDP connection test failed: {exc}")
            return False

    async def _launch_browser(self, browser_path: str, headless: bool, account_id: str = ""):
        user_data_dir = None
        if config.SAVE_LOGIN_STATE:
            if account_id:
                profile_name = f"cdp_{account_id}"
            else:
                profile_name = f"cdp_{config.USER_DATA_DIR % config.PLATFORM}"  # type: ignore[arg-type]
            user_data_dir = os.path.join(os.getcwd(), "browser_data", profile_name)
            os.makedirs(user_data_dir, exist_ok=True)
            utils.logger.info(f"[CDPBrowserManager] User data directory: {user_data_dir}")

        self.launcher.browser_process = self.launcher.launch_browser(
            browser_path=browser_path,
            debug_port=self.debug_port,
            headless=headless,
            user_data_dir=user_data_dir,
        )

        if not self.launcher.wait_for_browser_ready(self.debug_port, config.BROWSER_LAUNCH_TIMEOUT):
            raise RuntimeError(f"Browser failed to start within {config.BROWSER_LAUNCH_TIMEOUT} seconds")

        await asyncio.sleep(1)

        if not await self._test_cdp_connection(self.debug_port):
            utils.logger.warning("[CDPBrowserManager] CDP connection test failed, but will continue to try connecting")

    async def _get_browser_websocket_url(self, debug_port: int) -> str:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://localhost:{debug_port}/json/version", timeout=10)
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
                data = response.json()
                ws_url = data.get("webSocketDebuggerUrl")
                if not ws_url:
                    raise RuntimeError("webSocketDebuggerUrl not found")
                utils.logger.info(f"[CDPBrowserManager] Got browser WebSocket URL: {ws_url}")
                return ws_url
        except Exception as exc:
            utils.logger.error(f"[CDPBrowserManager] Failed to get WebSocket URL: {exc}")
            raise

    async def _connect_via_cdp(self, playwright: Playwright):
        try:
            ws_url = await self._get_browser_websocket_url(self.debug_port)
            utils.logger.info(f"[CDPBrowserManager] Connecting to browser via CDP: {ws_url}")
            self.browser = await playwright.chromium.connect_over_cdp(ws_url)

            if self.browser.is_connected():
                utils.logger.info("[CDPBrowserManager] Successfully connected to browser")
                utils.logger.info(f"[CDPBrowserManager] Browser contexts count: {len(self.browser.contexts)}")
            else:
                raise RuntimeError("CDP connection failed")
        except Exception as exc:
            utils.logger.error(f"[CDPBrowserManager] CDP connection failed: {exc}")
            raise

    async def _create_browser_context(
        self,
        playwright_proxy: Optional[Dict] = None,
        user_agent: Optional[str] = None,
    ) -> BrowserContext:
        if not self.browser:
            raise RuntimeError("Browser not connected")

        contexts = self.browser.contexts
        if contexts:
            browser_context = contexts[0]
            utils.logger.info("[CDPBrowserManager] Using existing browser context")
        else:
            context_options: dict[str, Any] = {
                "viewport": {"width": 1920, "height": 1080},
                "accept_downloads": True,
            }
            if user_agent:
                context_options["user_agent"] = user_agent
                utils.logger.info(f"[CDPBrowserManager] Setting user agent: {user_agent}")
            if playwright_proxy:
                utils.logger.warning(
                    "[CDPBrowserManager] Warning: Proxy settings may not work in CDP mode, "
                    "recommend configuring system proxy or browser proxy extension before launching browser"
                )
            browser_context = await self.browser.new_context(**context_options)
            utils.logger.info("[CDPBrowserManager] Created new browser context")

        return browser_context

    async def add_stealth_script(self, script_path: str | None = None):
        if script_path is None:
            script_path = str(Path(__file__).resolve().parents[1] / "assets" / "scripts" / "stealth.min.js")
        if self.browser_context and os.path.exists(script_path):
            try:
                await self.browser_context.add_init_script(path=script_path)
                utils.logger.info(f"[CDPBrowserManager] Added anti-detection script: {script_path}")
            except Exception as exc:
                utils.logger.warning(f"[CDPBrowserManager] Failed to add anti-detection script: {exc}")

    async def add_cookies(self, cookies: list):
        if self.browser_context:
            try:
                await self.browser_context.add_cookies(cookies)
                utils.logger.info(f"[CDPBrowserManager] Added {len(cookies)} cookies")
            except Exception as exc:
                utils.logger.warning(f"[CDPBrowserManager] Failed to add cookies: {exc}")

    async def get_cookies(self) -> list:
        if self.browser_context:
            try:
                return await self.browser_context.cookies()
            except Exception as exc:
                utils.logger.warning(f"[CDPBrowserManager] Failed to get cookies: {exc}")
                return []
        return []

    async def cleanup(self, force: bool = False):
        try:
            if self.browser_context:
                try:
                    try:
                        pages = self.browser_context.pages
                        if pages is not None:
                            await self.browser_context.close()
                            utils.logger.info("[CDPBrowserManager] Browser context closed")
                    except Exception:
                        utils.logger.debug("[CDPBrowserManager] Browser context already closed")
                except Exception as context_error:
                    error_msg = str(context_error).lower()
                    if "closed" not in error_msg and "disconnected" not in error_msg:
                        utils.logger.warning(f"[CDPBrowserManager] Failed to close browser context: {context_error}")
                    else:
                        utils.logger.debug(f"[CDPBrowserManager] Browser context already closed: {context_error}")
                finally:
                    self.browser_context = None

            if self.browser:
                try:
                    if self.browser.is_connected():
                        await self.browser.close()
                        utils.logger.info("[CDPBrowserManager] Browser connection disconnected")
                    else:
                        utils.logger.debug("[CDPBrowserManager] Browser connection already disconnected")
                except Exception as browser_error:
                    error_msg = str(browser_error).lower()
                    if "closed" not in error_msg and "disconnected" not in error_msg:
                        utils.logger.warning(f"[CDPBrowserManager] Failed to close browser connection: {browser_error}")
                    else:
                        utils.logger.debug(f"[CDPBrowserManager] Browser connection already closed: {browser_error}")
                finally:
                    self.browser = None

            if force or config.AUTO_CLOSE_BROWSER:
                if self.launcher and self.launcher.browser_process:
                    self.launcher.cleanup()
                else:
                    utils.logger.debug("[CDPBrowserManager] No browser process to cleanup")
            else:
                utils.logger.info("[CDPBrowserManager] Browser process kept running (AUTO_CLOSE_BROWSER=False)")

        except Exception as exc:
            utils.logger.error(f"[CDPBrowserManager] Error during resource cleanup: {exc}")

    def is_connected(self) -> bool:
        return self.browser is not None and self.browser.is_connected()

    async def get_browser_info(self) -> Dict[str, Any]:
        if not self.browser:
            return {}

        try:
            return {
                "version": self.browser.version,
                "contexts_count": len(self.browser.contexts),
                "debug_port": self.debug_port,
                "is_connected": self.is_connected(),
            }
        except Exception as exc:
            utils.logger.warning(f"[CDPBrowserManager] Failed to get browser info: {exc}")
            return {}
