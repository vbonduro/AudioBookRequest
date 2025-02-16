import logging
import os
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

from aiohttp import ClientResponse, ClientSession
from async_lru import alru_cache

from app.models import Indexer, ProwlarrSource

logger = logging.getLogger(__name__)

prowlarr_base_url = os.getenv("PROWLARR_BASE_URL", "")
prowlarr_api_key = os.getenv("PROWLARR_API_KEY", "")


async def start_download(
    session: ClientSession, guid: str, indexer_id: int
) -> ClientResponse:
    url = prowlarr_base_url + "/api/v1/search"

    logger.debug("Starting download for %s", guid)
    async with session.post(
        url,
        json={"guid": guid, "indexerId": indexer_id},
        headers={"X-Api-Key": prowlarr_api_key},
    ) as response:
        if not response.ok:
            print(response)
            logger.error("Failed to start download for %s: %s", guid, response)
        else:
            logger.debug("Download successfully started for %s", guid)
        return response


async def get_indexers(session: ClientSession) -> dict[int, Indexer]:
    url = prowlarr_base_url + "/api/v1/indexer"

    async with session.get(
        url,
        headers={"X-Api-Key": prowlarr_api_key},
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
    query: Optional[str], indexer_ids: Optional[list[int]] = None
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

    url = urljoin(prowlarr_base_url, f"/api/v1/search?{urlencode(params, doseq=True)}")

    logger.info("Querying prowlarr: %s", url)

    async with ClientSession() as session:
        async with session.get(
            url,
            headers={"X-Api-Key": prowlarr_api_key},
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
