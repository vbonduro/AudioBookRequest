import asyncio
import logging
from types import CoroutineType
from typing import Any

from app.internal.indexers.configuration import (
    ConfigurationException,
    ValuedConfigurations,
    create_valued_configuration,
)
from app.internal.indexers.indexers import indexers
from app.internal.indexers.abstract import AbstractIndexer, SessionContainer
from app.internal.models import BookRequest, ProwlarrSource

logger = logging.getLogger(__name__)


async def edit_source_metadata(
    book_request: BookRequest,
    sources: list[ProwlarrSource],
    container: SessionContainer,
):
    valued: list[tuple[AbstractIndexer[Any], ValuedConfigurations]] = []
    for Indexer in indexers:
        try:
            valued_configuration = create_valued_configuration(
                await Indexer.get_configurations(container),
                container.session,
            )
            valued.append((Indexer(), valued_configuration))
        except ConfigurationException as e:
            logger.error("Failed to get configurations for %s: %s", Indexer, e)

    coros = [
        indexer.setup(book_request, container, valued) for indexer, valued in valued
    ]
    await asyncio.gather(*coros, return_exceptions=True)

    coros: list[CoroutineType[Any, Any, None]] = []
    for source in sources:
        for indexer, _ in valued:
            if await indexer.is_matching_source(source, container):
                coros.append(indexer.edit_source_metadata(source, container))
                break
    await asyncio.gather(*coros, return_exceptions=True)
