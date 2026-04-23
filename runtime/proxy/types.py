import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProviderNameEnum(Enum):
    KUAI_DAILI_PROVIDER: str = "kuaidaili"
    WANDOU_HTTP_PROVIDER: str = "wandouhttp"


class IpInfoModel(BaseModel):
    ip: str = Field(title="ip")
    port: int = Field(title="port")
    user: str = Field(title="Username for IP proxy authentication")
    protocol: str = Field(default="https://", title="Protocol for proxy IP")
    password: str = Field(title="Password for IP proxy authentication user")
    expired_time_ts: Optional[int] = Field(default=None, title="IP expiration time")

    def is_expired(self, buffer_seconds: int = 30) -> bool:
        if self.expired_time_ts is None:
            return False
        current_ts = int(time.time())
        return current_ts >= (self.expired_time_ts - buffer_seconds)
