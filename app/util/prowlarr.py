import os
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin

import aiohttp
from async_lru import alru_cache

from app.models import Indexer


prowlarr_base_url = os.getenv("PROWLARR_BASE_URL", "")
prowlarr_api_key = os.getenv("PROWLARR_API_KEY", "")


async def start_download(guid: str, indexer_id: int) -> int:
    url = prowlarr_base_url + "/api/v1/search"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={"guid": guid, "indexer_id": indexer_id},
            headers={"X-Api-Key": prowlarr_api_key},
        ) as response:
            return response.status


async def get_indexers() -> dict[int, Indexer]:
    url = prowlarr_base_url + "/api/v1/indexer"

    async with aiohttp.ClientSession() as session:
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
async def query_prowlarr(query: Optional[str]) -> list[dict[Any, Any]]:
    if not query:
        return []
    url = urljoin(
        prowlarr_base_url,
        f"/api/v1/search?query={quote_plus(query)}&categories=3000&type=search&limit=100&offset=0",
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers={"X-Api-Key": prowlarr_api_key},
        ) as response:
            search_results = await response.json()

    for result in search_results:
        result["size"] = round(result["size"] / 1e6, 1)
        result["age"] = round(result["age"] / 24, 1)
    return search_results
