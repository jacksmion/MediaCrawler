# -*- coding: utf-8 -*-
#
# Structured runtime config service for API-driven updates.

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any


class RuntimeConfigService:
    """Reads default config from Python files and persists overrides as JSON."""

    def __init__(
        self,
        *,
        base_config_path: Path | None = None,
        runtime_config_path: Path | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parent.parent.parent
        self.base_config_path = base_config_path or project_root / "config" / "base_config.py"
        self.runtime_config_path = runtime_config_path or project_root / "config" / "runtime" / "api_config.json"
        self._lock = asyncio.Lock()

    async def get_all(self) -> dict[str, Any]:
        """Return merged config values from defaults and runtime overrides."""
        defaults = self._read_python_defaults()
        overrides = self._read_runtime_overrides()
        merged = {**defaults, **overrides}
        return {
            "defaults": defaults,
            "overrides": overrides,
            "merged": merged,
            "runtime_config_path": str(self.runtime_config_path),
        }

    async def update(self, config_data: dict[str, Any]) -> dict[str, Any]:
        """Persist uppercase runtime config overrides into JSON storage."""
        valid_updates = {
            key: value
            for key, value in config_data.items()
            if isinstance(key, str) and key.isupper()
        }
        if not valid_updates:
            return {"status": "no_change", "message": "No valid keys found for update", "updated_keys": []}

        async with self._lock:
            runtime_overrides = self._read_runtime_overrides()
            runtime_overrides.update(valid_updates)
            self.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
            self.runtime_config_path.write_text(
                json.dumps(runtime_overrides, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return {
            "status": "ok",
            "message": f"Updated {len(valid_updates)} runtime keys successfully",
            "updated_keys": sorted(valid_updates.keys()),
            "runtime_config_path": str(self.runtime_config_path),
        }

    def _read_runtime_overrides(self) -> dict[str, Any]:
        """Read persisted runtime overrides from JSON, if present."""
        if not self.runtime_config_path.exists():
            return {}
        try:
            payload = json.loads(self.runtime_config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: value for key, value in payload.items() if isinstance(key, str) and key.isupper()}

    def _read_python_defaults(self) -> dict[str, Any]:
        """Read simple uppercase assignment defaults from base_config.py."""
        if not self.base_config_path.exists():
            return {}

        content = self.base_config_path.read_text(encoding="utf-8")
        config_data: dict[str, Any] = {}
        pattern = re.compile(r'^([A-Z_]+)\s*=\s*([^#\n]+)(?:\s*#.*)?$', re.MULTILINE)

        for match in pattern.finditer(content):
            key = match.group(1)
            value_raw = match.group(2).strip()
            config_data[key] = self._parse_value(value_raw)
        return config_data

    @staticmethod
    def _parse_value(value_raw: str) -> Any:
        """Parse a basic Python config literal into a JSON-compatible value."""
        try:
            json_compatible = value_raw.replace("'", '"')
            if json_compatible in ("True", "False"):
                return json_compatible == "True"
            return json.loads(json_compatible)
        except Exception:
            if (value_raw.startswith('"') and value_raw.endswith('"')) or (
                value_raw.startswith("'") and value_raw.endswith("'")
            ):
                return value_raw[1:-1]
            return value_raw
