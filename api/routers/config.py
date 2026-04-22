# -*- coding: utf-8 -*-
from fastapi import APIRouter
from typing import Dict, Any

from ..services import RuntimeConfigService

router = APIRouter(prefix="/config", tags=["config"])
runtime_config_service = RuntimeConfigService()

@router.get("/")
async def get_all_config():
    """Read merged configuration from defaults and runtime overrides."""
    payload = await runtime_config_service.get_all()
    return {"config": payload["merged"], "defaults": payload["defaults"], "overrides": payload["overrides"]}

@router.post("/update")
async def update_config(config_data: Dict[str, Any]):
    """Persist runtime configuration overrides without mutating Python source files."""
    return await runtime_config_service.update(config_data)
