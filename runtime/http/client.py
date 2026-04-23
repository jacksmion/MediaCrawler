# -*- coding: utf-8 -*-
import httpx

import config


def make_async_client(**kwargs) -> httpx.AsyncClient:
    """Create a project-standard AsyncClient with shared SSL config."""
    kwargs.setdefault("verify", not getattr(config, "DISABLE_SSL_VERIFY", False))
    return httpx.AsyncClient(**kwargs)
