# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/data.py
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

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from application.services.state_store import StateStore

router = APIRouter(prefix="/data", tags=["data"])
state_store = StateStore()


@router.get("/files")
async def list_data_files(platform: Optional[str] = None, file_type: Optional[str] = None):
    """Get data file list"""
    return {"files": state_store.list_data_files(platform=platform, file_type=file_type)}


@router.get("/files/{file_path:path}")
async def get_file_content(file_path: str, preview: bool = True, limit: int = 100):
    """Get file content or preview"""
    if preview:
        try:
            return state_store.preview_data_file(file_path, limit=limit)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except IsADirectoryError:
            raise HTTPException(status_code=400, detail="Not a file")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Access denied")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return await download_file(file_path)


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download file"""
    try:
        full_path = state_store.resolve_data_file(file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except IsADirectoryError:
        raise HTTPException(status_code=400, detail="Not a file")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )


@router.get("/stats")
async def get_data_stats():
    """Get data statistics"""
    return state_store.get_data_stats()

@router.get("/stats/trends")
async def get_data_trends(days: int = 7):
    """Get weekly data trends based on modification time"""
    return state_store.get_data_trends(days=days)
