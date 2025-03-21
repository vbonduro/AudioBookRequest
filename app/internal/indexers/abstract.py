from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from aiohttp import ClientSession
from pydantic import BaseModel
from sqlmodel import Session

from app.internal.indexers.configuration import Configurations
from app.internal.models import BookRequest, ProwlarrSource


class SessionContainer(BaseModel, arbitrary_types_allowed=True):
    session: Session
    client_session: ClientSession


T = TypeVar("T", bound=Configurations)


class AbstractIndexer(ABC, Generic[T]):
    @abstractmethod
    async def setup(
        self,
        request: BookRequest,
        container: SessionContainer,
        configurations: Any,
    ) -> None:
        """
        Called initially when a book request is made.
        Can be used to set up initial settings required
        for the indexer or if the indexer only supports
        a general search feature, it can be executed in
        this step.
        """
        pass

    @staticmethod
    @abstractmethod
    async def get_configurations(
        container: SessionContainer,
    ) -> T:
        """
        Returns a list of configuration options that will be configurable on the frontend.
        """
        pass

    @abstractmethod
    async def is_matching_source(
        self, source: ProwlarrSource, container: SessionContainer
    ) -> bool:
        pass

    @abstractmethod
    async def edit_source_metadata(
        self, source: ProwlarrSource, container: SessionContainer
    ) -> None:
        pass
