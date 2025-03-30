import logging
from typing import Any, cast

from pydantic import BaseModel
from app.internal.indexers.indexers import indexers
from app.internal.indexers.abstract import AbstractIndexer, SessionContainer
from app.internal.indexers.configuration import (
    ConfigurationException,
    IndexerConfiguration,
    ValuedConfigurations,
    create_valued_configuration,
)

logger = logging.getLogger(__name__)


class IndexerContext(BaseModel, arbitrary_types_allowed=True):
    indexer: AbstractIndexer[Any]
    configuration: dict[str, IndexerConfiguration[Any]]
    valued: ValuedConfigurations


async def get_indexer_contexts(
    container: SessionContainer,
    *,
    check_required: bool = True,
    return_disabled: bool = False,
) -> list[IndexerContext]:
    contexts: list[IndexerContext] = []
    for Indexer in indexers:
        try:
            configuration = await Indexer.get_configurations(container)
            filtered_configuration: dict[str, IndexerConfiguration[Any]] = dict()
            for k, v in cast(dict[str, Any], vars(configuration)).items():
                if isinstance(v, IndexerConfiguration):
                    filtered_configuration[k] = v

            valued_configuration = create_valued_configuration(
                configuration,
                container.session,
                check_required=check_required,
            )

            indexer = Indexer()

            if not return_disabled and not await indexer.is_active(
                container, valued_configuration
            ):
                logger.debug("Indexer %s is disabled", Indexer.name)
                continue

            contexts.append(
                IndexerContext(
                    indexer=indexer,
                    configuration=filtered_configuration,
                    valued=valued_configuration,
                )
            )
        except ConfigurationException as e:
            logger.error("Failed to get configurations for %s: %s", Indexer.name, e)

    return contexts
