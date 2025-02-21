import asyncio
from functools import cmp_to_key
from typing import Callable

import pydantic
from aiohttp import ClientSession
from rapidfuzz import fuzz, utils
from sqlmodel import Session

from app.models import BookRequest, ProwlarrSource
from app.util.ranking.quality import QualityProfile
from app.util.ranking.quality_extract import Quality, extract_qualities


class RankSource(pydantic.BaseModel):
    source: ProwlarrSource
    quality: Quality


async def rank_sources(
    session: Session,
    client_session: ClientSession,
    sources: list[ProwlarrSource],
    book: BookRequest,
) -> list[ProwlarrSource]:
    # TODO: quality profile should be fetched from the config/db
    quality_profile = QualityProfile()

    async def get_qualities(source: ProwlarrSource):
        qualities = await extract_qualities(session, client_session, source, book)
        return [RankSource(source=source, quality=q) for q in qualities]

    coros = [get_qualities(source) for source in sources]
    rank_sources = [x for y in await asyncio.gather(*coros) for x in y]

    compare = CompareSource(quality_profile, book)
    rank_sources.sort(key=cmp_to_key(compare))

    return [rs.source for rs in rank_sources]


class CompareSource:
    def __init__(self, quality_profile: QualityProfile, book: BookRequest):
        self.book = book
        self.quality_profile = quality_profile
        self.compare_order = [
            self._compare_valid,
            self._compare_title,
            self._compare_authors,
            self._compare_narrators,
            self._compare_format,
            self._compare_flags,
            self._compare_indexer,
            self._compare_subtitle,
            self._compare_seeders,
        ]

    def __call__(self, a: RankSource, b: RankSource):
        return self.compare(a, b)

    def compare(self, a: RankSource, b: RankSource) -> int:
        return self._get_next_compare(0)(a, b, 1)

    def _get_next_compare(
        self, index: int
    ) -> Callable[[RankSource, RankSource, int], int]:
        def default_compare(a: RankSource, b: RankSource, next_compare: int) -> int:
            return 0

        if index < len(self.compare_order):
            return self.compare_order[index]
        return default_compare

    def _is_valid_quality(self, a: RankSource) -> bool:
        match a.quality.file_format:
            case "flac":
                quality_range = self.quality_profile.FLAC
            case "m4b":
                quality_range = self.quality_profile.M4B
            case "mp3":
                quality_range = self.quality_profile.MP3
            case "unknown-audio":
                quality_range = self.quality_profile.UNKNOWN_AUDIO
            case "unknown":
                quality_range = self.quality_profile.UNKNOWN

        return quality_range[0] < a.quality.kbits < quality_range[1]

    def _compare_valid(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        """Filter out any reasons that make it not valid"""
        a_valid = self._is_valid_quality(a) and a.source.seeders > 0
        b_valid = self._is_valid_quality(b) and b.source.seeders > 0
        if a_valid == b_valid:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return int(b_valid) - int(a_valid)

    def _compare_format(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if a.quality.file_format == b.quality.file_format:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        a_index = self.quality_profile.calculate_quality_rank(a.quality.file_format)
        b_index = self.quality_profile.calculate_quality_rank(b.quality.file_format)
        return a_index - b_index

    def _compare_flags(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_score = sum(
            points
            for flag, points in self.quality_profile.indexer_flags
            if flag.lower() in a.source.indexer_flags
        )
        b_score = sum(
            points
            for flag, points in self.quality_profile.indexer_flags
            if flag.lower() in b.source.indexer_flags
        )
        if a_score == b_score:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b_score - a_score

    def _compare_indexer(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_index = self.quality_profile.calculate_indexer_rank(a.source.indexer_id)
        b_index = self.quality_profile.calculate_indexer_rank(b.source.indexer_id)
        if a_index == b_index:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return a_index - b_index

    def _compare_title(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_title = exists_in_title(
            self.book.title, a.source.title, self.quality_profile.title_exists_ratio
        )
        b_title = exists_in_title(
            self.book.title, b.source.title, self.quality_profile.title_exists_ratio
        )
        if a_title == b_title:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return int(b_title) - int(a_title)

    def _compare_subtitle(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if not self.book.subtitle:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        a_title = exists_in_title(
            self.book.subtitle, a.source.title, self.quality_profile.title_exists_ratio
        )
        b_title = exists_in_title(
            self.book.subtitle, b.source.title, self.quality_profile.title_exists_ratio
        )
        if a_title == b_title:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return int(b_title) - int(a_title)

    def _compare_authors(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_score = vaguely_exist_in_title(
            self.book.authors, a.source.title, self.quality_profile.name_exists_ratio
        )
        b_score = vaguely_exist_in_title(
            self.book.authors, b.source.title, self.quality_profile.name_exists_ratio
        )
        if a_score == b_score:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b_score - a_score

    def _compare_narrators(
        self, a: RankSource, b: RankSource, next_compare: int
    ) -> int:
        a_score = vaguely_exist_in_title(
            self.book.narrators, a.source.title, self.quality_profile.name_exists_ratio
        )
        b_score = vaguely_exist_in_title(
            self.book.narrators, b.source.title, self.quality_profile.name_exists_ratio
        )
        if a_score == b_score:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b_score - a_score

    def _compare_seeders(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if a.source.seeders == b.source.seeders:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b.source.seeders - a.source.seeders


def vaguely_exist_in_title(words: list[str], title: str, name_exists_ratio: int) -> int:
    return sum(
        1
        for w in words
        if fuzz.token_set_ratio(w, title, processor=utils.default_process)
        > name_exists_ratio
    )


def exists_in_title(word: str, title: str, title_exists_ratio: int) -> bool:
    return (
        fuzz.partial_ratio(word, title, processor=utils.default_process)
        > title_exists_ratio
    )
