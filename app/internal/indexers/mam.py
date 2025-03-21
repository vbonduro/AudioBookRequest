import json
import logging
from typing import Any
from urllib.parse import urlencode, urljoin

from app.internal.indexers.abstract import (
    AbstractIndexer,
    SessionContainer,
)
from app.internal.indexers.configuration import (
    Configurations,
    IndexerConfiguration,
    ValuedConfigurations,
)
from app.internal.models import (
    BookRequest,
    ProwlarrSource,
)

logger = logging.getLogger(__name__)


class MamConfigurations(Configurations):
    mam_session_id: IndexerConfiguration[str] = IndexerConfiguration(
        type=str,
        dislay_name="MAM Session ID",
        required=True,
    )


class ValuedMamConfigurations(ValuedConfigurations):
    mam_session_id: str


class MamIndexer(AbstractIndexer[MamConfigurations]):
    results: dict[str, dict[str, Any]] = dict()

    @staticmethod
    async def get_configurations(
        container: SessionContainer,
    ) -> MamConfigurations:
        return MamConfigurations()

    async def setup(
        self,
        request: BookRequest,
        container: SessionContainer,
        configurations: ValuedMamConfigurations,
    ):
        query = request.title + " " + " ".join(request.authors)

        params: dict[str, Any] = {
            "tor[text]": query,  # book title + author(s)
            "tor[main_cat]": [13],  # MAM audiobook category
            "tor[searchIn]": "torrents",
            "tor[srchIn][author]": "true",
            "tor[srchIn][title]": "true",
            "tor[searchType]": "active",  # only search for torrents with at least 1 seeder.
            "startNumber": 0,
            "perpage": 100,
        }

        url = urljoin(
            "https://www.myanonamouse.net",
            f"/tor/js/loadSearchJSONbasic.php?{urlencode(params, doseq=True)}",
        )

        session_id = configurations.mam_session_id

        logger.info("Mam: Querying: %s", url)

        async with container.client_session.get(
            url, cookies={"mam_id": session_id}
        ) as response:
            if not response.ok:
                logger.error("Mam: Failed to query: %s", response.text)
                return
            search_results = await response.json()

        for result in search_results["data"]:
            self.results[result["id"]] = search_results["data"]
        logger.info("Mam: Retrieved %d results", len(self.results))

    async def is_matching_source(
        self,
        source: ProwlarrSource,
        container: SessionContainer,
    ):
        return source.info_url is not None and source.info_url.startswith(
            "https://www.myanonamouse.net/t/"
        )

    async def edit_source_metadata(
        self,
        source: ProwlarrSource,
        container: SessionContainer,
    ):
        mam_id = source.guid.split("/")[-1]
        result = self.results.get(mam_id)
        if result is None:
            return

        # response type of authors and narrators is a stringified json object
        source.book_metadata.authors = json.loads(
            result.get("author_info", "[]")
        ).values()
        source.book_metadata.narrators = json.loads(
            result.get("narrator_info", "[]")
        ).values()

        indexer_flags: set[str] = set()
        if result["personal_freeleech"] == 1:
            indexer_flags.add("personal_freeleech")
            indexer_flags.add("freeleech")
        if result["free"] == 1:
            indexer_flags.add("free")
            indexer_flags.add("freeleech")
        if result["fl_vip"] == 1:
            indexer_flags.add("fl_vip")
            indexer_flags.add("freeleech")
        if result["vip"] == 1:
            indexer_flags.add("vip")
        source.indexer_flags = list(indexer_flags)

        source.book_metadata.filetype = result["filetype"]
