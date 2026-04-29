# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/websocket.py
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

import asyncio
import logging
from typing import Set, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.task_manager import task_manager as crawler_manager

router = APIRouter(tags=["websocket"])
logger = logging.getLogger("MediaCrawler.API")


class ConnectionManager:
    """WebSocket connection manager"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connections"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected connections
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


class BroadcastRuntime:
    def __init__(self) -> None:
        self.task: Optional[asyncio.Task] = None

    def ensure_started(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(log_broadcaster())


broadcast_runtime = BroadcastRuntime()


async def log_broadcaster():
    """Background task: read logs from all active task queues and broadcast"""
    while True:
        try:
            got_entry = False
            for log_service in crawler_manager._log_services.values():
                queue = log_service.get_log_queue()
                try:
                    entry = queue.get_nowait()
                    await manager.broadcast(entry.model_dump())
                    got_entry = True
                except asyncio.QueueEmpty:
                    pass
            if not got_entry:
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Log broadcaster error: %s", e)
            await asyncio.sleep(0.1)


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket log stream"""
    try:
        broadcast_runtime.ensure_started()

        await manager.connect(websocket)
        logger.debug("WebSocket connected, active connections: %s", len(manager.active_connections))

        for log in crawler_manager.logs:
            try:
                await websocket.send_json(log.model_dump())
            except Exception as e:
                logger.warning("Error sending existing log: %s", e)
                break

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception as e:
                    logger.debug("Error sending ping: %s", e)
                    break

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as e:
        logger.warning("WebSocket error: %s: %s", type(e).__name__, e)
    finally:
        manager.disconnect(websocket)
        logger.debug("WebSocket cleanup done, active connections: %s", len(manager.active_connections))


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket status stream"""
    await websocket.accept()

    try:
        while True:
            # Send status every second
            status = crawler_manager.get_status()
            await websocket.send_json(status)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
