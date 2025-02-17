import time
from typing import Generic, Optional, TypeVar


T = TypeVar("T")


# TODO: determine if we want to use the DB as well or not
class SimpleCache(Generic[T]):
    _cache: dict[tuple[str, ...], tuple[int, T]] = {}

    def get(self, source_ttl: int, *query: str) -> Optional[T]:
        hit = self._cache.get(query)
        if not hit:
            return None
        cached_at, sources = hit
        if cached_at + source_ttl < time.time():
            return None
        return sources

    def set(self, sources: T, *query: str):
        self._cache[query] = (int(time.time()), sources)
