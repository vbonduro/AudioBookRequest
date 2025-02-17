import logging
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

from aiohttp import ClientResponse, ClientSession
from sqlmodel import Session, select

from app.models import Config, Indexer, ProwlarrSource
from app.util.cache import SimpleCache

logger = logging.getLogger(__name__)


class ProwlarrMisconfigured(ValueError):
    pass


# TODO: Find an elegant solution for handling the prowlarr config
# Some way to make storing and retrieving values less error-prone
# and also not completely inefficient
class ProwlarrConfig:
    _base_url: Optional[str] = None
    _api_key: Optional[str] = None
    _source_ttl: Optional[int] = None

    def raise_if_invalid(self, session: Session):
        if not self.get_base_url(session):
            raise ProwlarrMisconfigured("Prowlarr base url not set")
        if not self.get_api_key(session):
            raise ProwlarrMisconfigured("Prowlarr base url not set")

    def _get(self, session: Session, key: str) -> Optional[str]:
        return session.exec(select(Config.value).where(Config.key == key)).one_or_none()

    def _set(self, session: Session, key: str, value: str):
        old = session.exec(select(Config).where(Config.key == key)).one_or_none()
        if old:
            old.value = value
        else:
            old = Config(key=key, value=value)
        session.add(old)

    def get_api_key(self, session: Session) -> Optional[str]:
        if not self._api_key:
            api_key = self._get(session, "prowlarr_api_key")
            if api_key:
                self._api_key = api_key
        return self._api_key

    def set_api_key(self, session: Session, api_key: str):
        self._api_key = api_key
        self._set(session, "prowlarr_api_key", api_key)

    def get_base_url(self, session: Session) -> Optional[str]:
        if not self._base_url:
            base_url = self._get(session, "prowlarr_base_url")
            if base_url:
                self._base_url = base_url
        return self._base_url

    def set_base_url(self, session: Session, base_url: str):
        self._base_url = base_url
        self._set(session, "prowlarr_base_url", base_url)

    def get_source_ttl(self, session: Session) -> int:
        if not self._source_ttl:
            source_ttl = self._get(session, "prowlarr_source_ttl")
            if source_ttl:
                self._source_ttl = int(source_ttl)
            else:
                self._source_ttl = 24 * 60 * 60  # default 1 day TTL
        return self._source_ttl

    def set_source_ttl(self, session: Session, source_ttl: int):
        self._source_ttl = source_ttl
        self._set(session, "prowlarr_source_ttl", str(source_ttl))


prowlarr_config = ProwlarrConfig()
prowlarr_source_cache = SimpleCache[list[ProwlarrSource]]()
prowlarr_indexer_cache = SimpleCache[dict[int, Indexer]]()


async def start_download(
    session: Session,
    client_session: ClientSession,
    guid: str,
    indexer_id: int,
) -> ClientResponse:
    prowlarr_config.raise_if_invalid(session)
    base_url = prowlarr_config.get_base_url(session)
    api_key = prowlarr_config.get_api_key(session)
    assert base_url is not None and api_key is not None

    url = base_url + "/api/v1/search"
    logger.debug("Starting download for %s", guid)
    async with client_session.post(
        url,
        json={"guid": guid, "indexerId": indexer_id},
        headers={"X-Api-Key": api_key},
    ) as response:
        if not response.ok:
            print(response)
            logger.error("Failed to start download for %s: %s", guid, response)
        else:
            logger.debug("Download successfully started for %s", guid)
        return response


async def get_indexers(
    session: Session,
    client_session: ClientSession,
) -> dict[int, Indexer]:
    base_url = prowlarr_config.get_base_url(session)
    api_key = prowlarr_config.get_api_key(session)
    assert base_url is not None and api_key is not None

    source_ttl = prowlarr_config.get_source_ttl(session)
    cached_sources = prowlarr_indexer_cache.get(source_ttl)
    if cached_sources:
        return cached_sources

    url = base_url + "/api/v1/indexer"
    async with client_session.get(
        url,
        headers={"X-Api-Key": api_key},
    ) as response:
        indexers = await response.json()

    indexer_mapping = {
        i["id"]: Indexer(
            id=i["id"],
            name=i["name"],
            enabled=i["enable"],
            privacy=i["privacy"],
        )
        for i in indexers
    }
    prowlarr_indexer_cache.set(indexer_mapping)
    return indexer_mapping


async def query_prowlarr(
    session: Session,
    client_session: ClientSession,
    query: Optional[str],
    indexer_ids: Optional[list[int]] = None,
    force_refresh: bool = False,
) -> list[ProwlarrSource]:
    if not query:
        return []

    base_url = prowlarr_config.get_base_url(session)
    api_key = prowlarr_config.get_api_key(session)
    assert base_url is not None and api_key is not None

    if not force_refresh:
        source_ttl = prowlarr_config.get_source_ttl(session)
        cached_sources = prowlarr_source_cache.get(source_ttl, query)
        if cached_sources:
            return cached_sources

    params: dict[str, Any] = {
        "query": query,
        "categories": 3000,
        "type": "search",
        "limit": 100,
        "offset": 0,
    }
    if indexer_ids is not None:
        params["indexerIds"] = indexer_ids

    url = urljoin(base_url, f"/api/v1/search?{urlencode(params, doseq=True)}")

    logger.info("Querying prowlarr: %s", url)

    async with client_session.get(
        url,
        headers={"X-Api-Key": api_key},
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
                size=result["size"],
                publish_date=datetime.fromisoformat(result["publishDate"]),
            )
        )

    prowlarr_source_cache.set(sources, query)

    return sources
