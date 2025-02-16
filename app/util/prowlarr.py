import logging
from datetime import datetime
from typing import Annotated, Any, Optional
from urllib.parse import urlencode, urljoin

from aiohttp import ClientResponse, ClientSession
from async_lru import alru_cache
from fastapi import Depends, HTTPException
import pydantic
from sqlmodel import Session, select

from app.db import get_session
from app.models import Config, Indexer, ProwlarrSource

logger = logging.getLogger(__name__)


class ProwlarrConfig(pydantic.BaseModel):
    base_url: str
    api_key: str

    def __hash__(self) -> int:
        return hash((self.base_url, self.api_key))


def get_prowlarr_config(
    session: Annotated[Session, Depends(get_session)],
) -> ProwlarrConfig:
    api_key = session.exec(
        select(Config.value).where(Config.key == "prowlarr_api_key")
    ).one_or_none()
    base_url = session.exec(
        select(Config.value).where(Config.key == "prowlarr_base_url")
    ).one_or_none()

    if not api_key or not base_url:
        raise HTTPException(500, "Prowlarr configuration missing")

    return ProwlarrConfig(base_url=base_url, api_key=api_key)


async def start_download(
    config: ProwlarrConfig,
    session: ClientSession,
    guid: str,
    indexer_id: int,
) -> ClientResponse:
    url = config.base_url + "/api/v1/search"

    logger.debug("Starting download for %s", guid)
    async with session.post(
        url,
        json={"guid": guid, "indexerId": indexer_id},
        headers={"X-Api-Key": config.api_key},
    ) as response:
        if not response.ok:
            print(response)
            logger.error("Failed to start download for %s: %s", guid, response)
        else:
            logger.debug("Download successfully started for %s", guid)
        return response


async def get_indexers(
    config: ProwlarrConfig,
    session: ClientSession,
) -> dict[int, Indexer]:
    url = config.base_url + "/api/v1/indexer"

    async with session.get(
        url,
        headers={"X-Api-Key": config.api_key},
    ) as response:
        indexers = await response.json()

    return {
        i["id"]: Indexer(
            id=i["id"],
            name=i["name"],
            enabled=i["enable"],
            privacy=i["privacy"],
        )
        for i in indexers
    }


@alru_cache(ttl=300)
async def query_prowlarr(
    config: ProwlarrConfig,
    query: Optional[str],
    indexer_ids: Optional[list[int]] = None,
) -> list[ProwlarrSource]:
    if not query:
        return []
    params: dict[str, Any] = {
        "query": query,
        "categories": 3000,
        "type": "search",
        "limit": 100,
        "offset": 0,
    }
    if indexer_ids is not None:
        params["indexerIds"] = indexer_ids

    url = urljoin(config.base_url, f"/api/v1/search?{urlencode(params, doseq=True)}")

    logger.info("Querying prowlarr: %s", url)

    async with ClientSession() as session:
        async with session.get(
            url,
            headers={"X-Api-Key": config.api_key},
        ) as response:
            search_results = await response.json()

    sources: list[ProwlarrSource] = []
    for result in search_results:
        sources.append(
            ProwlarrSource(
                guid=result["guid"],
                indexer_id=result["indexerId"],
                title=result["title"],
                seeders=result["seeders"],
                leechers=result["leechers"],
                size=round(result["size"] / 1e6, 1),
                publish_date=datetime.fromisoformat(result["publishDate"]),
            )
        )
    return sources
