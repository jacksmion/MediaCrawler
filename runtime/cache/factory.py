class CacheFactory:
    @staticmethod
    def create_cache(cache_type: str, *args, **kwargs):
        if cache_type == "memory":
            from .local import ExpiringLocalCache

            return ExpiringLocalCache(*args, **kwargs)
        if cache_type == "redis":
            from .redis import RedisCache

            return RedisCache()
        raise ValueError(f"Unknown cache type: {cache_type}")
