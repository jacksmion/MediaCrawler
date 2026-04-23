# -*- coding: utf-8 -*-
#
# Storage helpers for runtime-managed output targets.

from database.db import close as close_storage_backends
from database.db import init_db as init_storage_backends

from .excel_store import ExcelStoreBase

__all__ = ["ExcelStoreBase", "init_storage_backends", "close_storage_backends"]
