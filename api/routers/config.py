# -*- coding: utf-8 -*-
from fastapi import APIRouter, HTTPException
import re
import asyncio
import json
from pathlib import Path
from typing import Dict, Any

router = APIRouter(prefix="/config", tags=["config"])

# Config file path
CONFIG_FILE = Path(__file__).parent.parent.parent / "config" / "base_config.py"
# Lock to ensure atomic file writes
config_file_lock = asyncio.Lock()

@router.get("/")
async def get_all_config():
    """Read all configuration from config/base_config.py"""
    if not CONFIG_FILE.exists():
        raise HTTPException(status_code=404, detail="Config file not found")
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Simple regex to get variables like PLATFORM = "dy"
    # Matches KEY = VALUE, capturing VALUE up to the first comment or newline
    config_data = {}
    pattern = re.compile(r'^([A-Z_]+)\s*=\s*([^#\n]+)(?:\s*#.*)?$', re.MULTILINE)
    
    for match in pattern.finditer(content):
        key = match.group(1)
        value_raw = match.group(2).strip()
        
        try:
            # Handle standard Python types using plastic evaluation
            # 1. Try JSON (handles numbers, bools, strings with double quotes, lists, dicts)
            json_compatible = value_raw.replace("'", '"')
            if json_compatible in ("True", "False"):
                value = json_compatible == "True"
            else:
                value = json.loads(json_compatible)
        except Exception:
            # Fallback: keep as raw string but strip quotes if it's a string literal
            if (value_raw.startswith('"') and value_raw.endswith('"')) or \
               (value_raw.startswith("'") and value_raw.endswith("'")):
                value = value_raw[1:-1]
            else:
                value = value_raw
            
        config_data[key] = value

    return {"config": config_data}

@router.post("/update")
async def update_config(config_data: Dict[str, Any]):
    """Update configuration to config/base_config.py"""
    if not CONFIG_FILE.exists():
        raise HTTPException(status_code=404, detail="Config file not found")
    
    async with config_file_lock:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        new_content = content
        keys_updated = []
        
        for key, value in config_data.items():
            # Only support uppercase keys (standard variables in base_config)
            if not key.isupper():
                continue
                
            # Format values for Python
            if isinstance(value, bool):
                formatted_value = "True" if value else "False"
            elif isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float, list, dict)):
                formatted_value = json.dumps(value, ensure_ascii=False)
            else:
                continue
                
            # Improved regex: Group 1 = KEY, Group 2 = WHITESPACE_AND_COMMENT
            # It finds the line starting with KEY = ..., capturing the tail (comments)
            pattern = rf'^({key})\s*=\s*(?:[^#\n]*)(\s*#.*)?$'
            replacement = rf'\1 = {formatted_value}\2'
            
            if re.search(pattern, new_content, re.MULTILINE):
                new_content = re.sub(pattern, replacement, new_content, flags=re.MULTILINE)
                keys_updated.append(key)
                
        if not keys_updated:
            return {"status": "no_change", "message": "No valid keys found for update"}

        # Write back to file safely
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)

    return {
        "status": "ok", 
        "message": f"Updated {len(keys_updated)} keys successfully", 
        "updated_keys": keys_updated
    }
