from typing import Generic, TypeVar
from abc import ABC, abstractmethod

from aiohttp import ClientSession
from sqlmodel import Session

from app.internal.models import ProwlarrSource
from app.util.cache import StringConfigCache

ConfigKey = TypeVar("ConfigKey", bound=str)


# Maybe rename to something like metadata injector.
class IndexerMissconfigured(ValueError):
    pass


class BaseIndexer(ABC, Generic[ConfigKey]):
    session: Session

    def __init__(self, session: Session):
        self.session = session

    @abstractmethod
    def get_config(self) -> StringConfigCache[ConfigKey]:
        pass

    @abstractmethod
    def is_active(self) -> bool:
        pass

    @abstractmethod
    def set_active(self, state: bool) -> bool:
        pass

    @abstractmethod
    def valid_config(self) -> bool:
        pass

    @abstractmethod
    async def enrichResults(
        self,
        client_session: ClientSession,
        query: str,
        results: list[ProwlarrSource],
        force_refresh: bool = False,
    ) -> list[ProwlarrSource]:
        return results
