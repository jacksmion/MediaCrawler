# -*- coding: utf-8 -*-
#
# App factory for MediaCrawler WebUI API.

from __future__ import annotations

import asyncio
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import account_router, comments_router, config_router, crawler_router, data_router, websocket_router
from .settings import get_api_settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_api_settings()
    app = FastAPI(
        title="MediaCrawler WebUI API",
        description="API for controlling MediaCrawler from WebUI",
        version="1.0.0",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(crawler_router, prefix="/api")
    app.include_router(comments_router, prefix="/api")
    app.include_router(data_router, prefix="/api")
    app.include_router(websocket_router, prefix="/api")
    app.include_router(account_router, prefix="/api")
    app.include_router(config_router, prefix="/api")

    @app.get("/")
    async def root():
        """Return API service metadata."""
        return {
            "message": "MediaCrawler API service",
            "version": "1.0.0",
            "docs": "/docs",
            "frontend_dev": "http://localhost:5173",
            "frontend_source": str(settings.project_root / "webui-react"),
        }

    @app.get("/api/health")
    async def health_check():
        return {
            "status": "ok",
            "frontend_mode": "separated",
            "frontend_source": str(settings.project_root / "webui-react"),
        }

    @app.get("/api/env/check")
    async def check_environment():
        """Check if MediaCrawler environment is configured correctly."""
        try:
            process = await asyncio.create_subprocess_exec(
                "uv",
                "run",
                "python",
                "cli.py",
                "--help",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(settings.project_root),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0,
            )

            if process.returncode == 0:
                return {
                    "success": True,
                    "message": "MediaCrawler environment configured correctly",
                    "output": stdout.decode("utf-8", errors="ignore")[:500],
                }
            error_msg = stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")
            return {
                "success": False,
                "message": "Environment check failed",
                "error": error_msg[:500],
            }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "message": "Environment check timeout",
                "error": "Command execution exceeded 30 seconds",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "message": "uv command not found",
                "error": "Please ensure uv is installed and configured in system PATH",
            }
        except Exception as e:
            return {
                "success": False,
                "message": "Environment check error",
                "error": str(e),
            }

    @app.get("/api/config/platforms")
    async def get_platforms():
        """Get list of supported platforms."""
        return {
            "platforms": [
                {"value": "xhs", "label": "Xiaohongshu", "icon": "book-open"},
                {"value": "dy", "label": "Douyin", "icon": "music"},
                {"value": "ks", "label": "Kuaishou", "icon": "video"},
                {"value": "bili", "label": "Bilibili", "icon": "tv"},
                {"value": "wb", "label": "Weibo", "icon": "message-circle"},
                {"value": "tieba", "label": "Baidu Tieba", "icon": "messages-square"},
                {"value": "zhihu", "label": "Zhihu", "icon": "help-circle"},
            ]
        }

    @app.get("/api/config/options")
    async def get_config_options():
        """Get all configuration options."""
        return {
            "login_types": [
                {"value": "qrcode", "label": "QR Code Login"},
                {"value": "cookie", "label": "Cookie Login"},
            ],
            "crawler_types": [
                {"value": "search", "label": "Search Mode"},
                {"value": "detail", "label": "Detail Mode"},
                {"value": "creator", "label": "Creator Mode"},
            ],
            "save_options": [
                {"value": "jsonl", "label": "JSONL File"},
                {"value": "json", "label": "JSON File"},
                {"value": "csv", "label": "CSV File"},
                {"value": "excel", "label": "Excel File"},
                {"value": "sqlite", "label": "SQLite Database"},
                {"value": "db", "label": "MySQL Database"},
                {"value": "mongodb", "label": "MongoDB Database"},
            ],
        }
    return app
