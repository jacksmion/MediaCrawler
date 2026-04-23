from abc import ABC, abstractmethod
from typing import Any, List, Optional


class AbstractCache(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: Any, expire_time: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def keys(self, pattern: str) -> List[str]:
        raise NotImplementedError
