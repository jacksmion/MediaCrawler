from .base import BasePlatformHooks, ExecutionServices
from .bilibili import BilibiliPlatformHooks
from .douyin import DouyinPlatformHooks
from .kuaishou import KuaishouPlatformHooks
from .tieba import TiebaPlatformHooks
from .weibo import WeiboPlatformHooks
from .xhs import XhsPlatformHooks
from .zhihu import ZhihuPlatformHooks

__all__ = [
    "BasePlatformHooks",
    "ExecutionServices",
    "BilibiliPlatformHooks",
    "DouyinPlatformHooks",
    "KuaishouPlatformHooks",
    "TiebaPlatformHooks",
    "WeiboPlatformHooks",
    "XhsPlatformHooks",
    "ZhihuPlatformHooks",
]
