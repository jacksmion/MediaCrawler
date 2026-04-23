import pickle
from typing import Any, List

from redis import Redis
from redis.exceptions import ResponseError

from config import db_config

from .base import AbstractCache


class RedisCache(AbstractCache):
    def __init__(self) -> None:
        self._redis_client = self._connect_redis()

    @staticmethod
    def _connect_redis() -> Redis:
        return Redis(
            host=db_config.REDIS_DB_HOST,
            port=db_config.REDIS_DB_PORT,
            db=db_config.REDIS_DB_NUM,
            password=db_config.REDIS_DB_PWD,
        )

    def get(self, key: str) -> Any:
        value = self._redis_client.get(key)
        if value is None:
            return None
        return pickle.loads(value)

    def set(self, key: str, value: Any, expire_time: int) -> None:
        self._redis_client.set(key, pickle.dumps(value), ex=expire_time)

    def keys(self, pattern: str) -> List[str]:
        try:
            return [key.decode() if isinstance(key, bytes) else key for key in self._redis_client.keys(pattern)]
        except ResponseError as exc:
            if "unknown command" in str(exc).lower() or "keys" in str(exc).lower():
                keys_list: List[str] = []
                cursor = 0
                while True:
                    cursor, keys = self._redis_client.scan(cursor=cursor, match=pattern, count=100)
                    keys_list.extend([key.decode() if isinstance(key, bytes) else key for key in keys])
                    if cursor == 0:
                        break
                return keys_list
            raise
