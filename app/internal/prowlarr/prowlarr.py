import json
import posixpath
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlencode

from aiohttp import ClientResponse, ClientSession
from pydantic import BaseModel
from sqlmodel import Session

from app.internal.indexers.abstract import SessionContainer
from app.internal.models import (
    BookRequest,
    EventEnum,
    Indexer,
    ProwlarrSource,
    TorrentSource,
    UsenetSource,
)
from app.internal.notifications import send_all_notifications
from app.internal.prowlarr.source_metadata import edit_source_metadata
from app.util.cache import SimpleCache, StringConfigCache
from app.util.log import logger


class ProwlarrMisconfigured(ValueError):
    pass


ProwlarrConfigKey = Literal[
    "prowlarr_api_key",
    "prowlarr_base_url",
    "prowlarr_source_ttl",
    "prowlarr_categories",
    "prowlarr_indexers",
]


class ProwlarrConfig(StringConfigCache[ProwlarrConfigKey]):
    def raise_if_invalid(self, session: Session):
        if not self.get_base_url(session):
            raise ProwlarrMisconfigured("Prowlarr base url not set")
        if not self.get_api_key(session):
            raise ProwlarrMisconfigured("Prowlarr base url not set")

    def is_valid(self, session: Session) -> bool:
        return (
            self.get_base_url(session) is not None
            and self.get_api_key(session) is not None
        )

    def get_api_key(self, session: Session) -> Optional[str]:
        return self.get(session, "prowlarr_api_key")

    def set_api_key(self, session: Session, api_key: str):
        self.set(session, "prowlarr_api_key", api_key)

    def get_base_url(self, session: Session) -> Optional[str]:
        path = self.get(session, "prowlarr_base_url")
        if path:
            return path.rstrip("/")
        return None

    def set_base_url(self, session: Session, base_url: str):
        self.set(session, "prowlarr_base_url", base_url)

    def get_source_ttl(self, session: Session) -> int:
        return self.get_int(session, "prowlarr_source_ttl", 24 * 60 * 60)

    def set_source_ttl(self, session: Session, source_ttl: int):
        self.set_int(session, "prowlarr_source_ttl", source_ttl)

    def get_categories(self, session: Session) -> list[int]:
        categories = self.get(session, "prowlarr_categories")
        if categories is None:
            return [3030]
        return json.loads(categories)

    def set_categories(self, session: Session, categories: list[int]):
        self.set(session, "prowlarr_categories", json.dumps(categories))

    def get_indexers(self, session: Session) -> list[int]:
        indexers = self.get(session, "prowlarr_indexers")
        if indexers is None:
            return []
        return json.loads(indexers)

    def set_indexers(self, session: Session, indexers: list[int]):
        self.set(session, "prowlarr_indexers", json.dumps(indexers))


prowlarr_config = ProwlarrConfig()
prowlarr_source_cache = SimpleCache[list[ProwlarrSource], str]()
prowlarr_indexer_cache = SimpleCache[Indexer, str]()


def flush_prowlarr_cache():
    prowlarr_source_cache.flush()
    prowlarr_indexer_cache.flush()


async def start_download(
    session: Session,
    client_session: ClientSession,
    guid: str,
    indexer_id: int,
    requester_username: str,
    book_asin: str,
) -> ClientResponse:
    prowlarr_config.raise_if_invalid(session)
    base_url = prowlarr_config.get_base_url(session)
    api_key = prowlarr_config.get_api_key(session)
    assert base_url is not None and api_key is not None

    url = posixpath.join(base_url, "api/v1/search")
    logger.debug("Starting download", guid=guid)
    async with client_session.post(
        url,
        json={"guid": guid, "indexerId": indexer_id},
        headers={"X-Api-Key": api_key},
    ) as response:
        if not response.ok:
            logger.error("Failed to start download", guid=guid, response=response)
            await send_all_notifications(
                EventEnum.on_failed_download,
                requester_username,
                book_asin,
                {
                    "errorStatus": str(response.status),
                    "errorReason": response.reason or "<unknown>",
                },
            )
        else:
            logger.debug("Download successfully started", guid=guid)
            await send_all_notifications(
                EventEnum.on_successful_download, requester_username, book_asin
            )

        return response


async def query_prowlarr(
    session: Session,
    client_session: ClientSession,
    book_request: BookRequest,
    query: str,
    indexer_ids: Optional[list[int]] = None,
    force_refresh: bool = False,
    only_return_if_cached: bool = False,
) -> Optional[list[ProwlarrSource]]:
    base_url = prowlarr_config.get_base_url(session)
    api_key = prowlarr_config.get_api_key(session)
    assert base_url is not None and api_key is not None
    source_ttl = prowlarr_config.get_source_ttl(session)

    if only_return_if_cached:
        cached_sources = prowlarr_source_cache.get(source_ttl, query)
        return cached_sources

    if not force_refresh:
        cached_sources = prowlarr_source_cache.get(source_ttl, query)
        if cached_sources:
            return cached_sources

    params: dict[str, Any] = {
        "query": query,
        "type": "search",
        "limit": 100,
        "offset": 0,
    }

    if len(x := prowlarr_config.get_categories(session)) > 0:
        params["categories"] = x

    if indexer_ids is not None:
        params["indexerIds"] = indexer_ids

    url = posixpath.join(base_url, f"api/v1/search?{urlencode(params, doseq=True)}")

    logger.info("Querying prowlarr", url=url)

    async with client_session.get(
        url,
        headers={"X-Api-Key": api_key},
    ) as response:
        search_results = await response.json()

    sources: list[ProwlarrSource] = []
    for result in search_results:
        try:
            if result["protocol"] not in ["torrent", "usenet"]:
                logger.info(
                    "Skipping source with unknown protocol", protocol=result["protocol"]
                )
                continue
            if result["protocol"] == "torrent":
                sources.append(
                    TorrentSource(
                        protocol="torrent",
                        guid=result["guid"],
                        indexer_id=result["indexerId"],
                        indexer=result["indexer"],
                        title=result["title"],
                        seeders=result.get("seeders", 0),
                        leechers=result.get("leechers", 0),
                        size=result.get("size", 0),
                        info_url=result.get("infoUrl"),
                        indexer_flags=[
                            x.lower() for x in result.get("indexerFlags", [])
                        ],
                        download_url=result.get("downloadUrl"),
                        magnet_url=result.get("magnetUrl"),
                        publish_date=datetime.fromisoformat(result["publishDate"]),
                    )
                )
            else:
                sources.append(
                    UsenetSource(
                        protocol="usenet",
                        guid=result["guid"],
                        indexer_id=result["indexerId"],
                        indexer=result["indexer"],
                        title=result["title"],
                        grabs=result.get("grabs"),
                        size=result.get("size", 0),
                        info_url=result.get("infoUrl"),
                        indexer_flags=[
                            x.lower() for x in result.get("indexerFlags", [])
                        ],
                        download_url=result.get("downloadUrl"),
                        magnet_url=result.get("magnetUrl"),
                        publish_date=datetime.fromisoformat(result["publishDate"]),
                    )
                )
        except KeyError as e:
            logger.error("Failed to parse source", source=result, keyerror=str(e))

    # add additional metadata using any available indexers
    container = SessionContainer(session=session, client_session=client_session)
    await edit_source_metadata(book_request, sources, container)

    prowlarr_source_cache.set(sources, query)

    return sources


class IndexerResponse(BaseModel):
    indexers: dict[int, Indexer] = {}
    state: Literal["ok", "missingUrlKey", "failedFetch"]
    error: Optional[str] = None

    @property
    def json_string(self) -> str:
        return json.dumps(
            {id: indexer.model_dump() for id, indexer in self.indexers.items()}
        )

    @property
    def ok(self) -> bool:
        return self.state == "ok"


async def get_indexers(
    session: Session, client_session: ClientSession
) -> IndexerResponse:
    """Fetch the list of all indexers from Prowlarr."""
    base_url = prowlarr_config.get_base_url(session)
    api_key = prowlarr_config.get_api_key(session)
    source_ttl = prowlarr_config.get_source_ttl(session)

    if not base_url or not api_key:
        logger.warning("Prowlarr base url or api key not set, skipping indexer fetch")
        return IndexerResponse(
            state="failedFetch",
            error="Missing Prowlarr base url or api key",
        )

    indexers = list(prowlarr_indexer_cache.get_all(source_ttl).values())
    try:
        if len(indexers) > 0:
            return IndexerResponse(
                indexers={indexer.id: indexer for indexer in indexers},
                state="ok",
            )

        url = posixpath.join(base_url, "api/v1/indexer")
        logger.info("Fetching indexers from Prowlarr", url=url)

        async with client_session.get(
            url,
            headers={"X-Api-Key": api_key},
        ) as response:
            if not response.ok:
                logger.error("Failed to fetch indexers", response=response)
                return IndexerResponse(
                    state="failedFetch",
                    error=f"{response.status}: {response.reason}",
                )

            json_response = await response.json()

            for indexer in json_response:
                indexer_obj = Indexer.model_validate(indexer)
                prowlarr_indexer_cache.set(indexer_obj, str(indexer_obj.id))

        return IndexerResponse(
            indexers={
                indexer.id: indexer
                for indexer in prowlarr_indexer_cache.get_all(source_ttl).values()
            },
            state="ok",
        )
    except Exception as e:
        logger.error("Failed to access Prowlarr to fetch indexers", error=str(e))
        return IndexerResponse(
            state="failedFetch",
            error=str(e),
        )
