import asyncio
from aiohttp import ClientSession
import pydantic
from sqlmodel import Session
from app.models import BookRequest, ProwlarrSource
from app.util.ranking.quality import QualityProfile
from app.util.ranking.quality_extract import Quality, extract_qualities
from functools import cmp_to_key


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
    # TODO: check if the ordering is working as expected
    rank_sources.sort(key=cmp_to_key(compare))

    return [rs.source for rs in rank_sources]


class CompareSource:
    def __init__(self, quality_profile: QualityProfile, book: BookRequest):
        self.book = book
        self.quality_profile = quality_profile

    def __call__(self, a: RankSource, b: RankSource):
        return self.compare(a, b)

    def compare(self, a: RankSource, b: RankSource) -> int:
        # TODO: allow customizing of order
        return self._compare_quality(a, b)

    def _is_valid_quality(self, a: RankSource) -> bool:
        match a.quality.file_format:
            case "flac":
                quality_range = self.quality_profile.FLAC
            case "m4b":
                quality_range = self.quality_profile.M4B
            case "mp3":
                quality_range = self.quality_profile.MP3
            case "unknown":
                quality_range = self.quality_profile.UNKNOWN

        return quality_range[0] < a.quality.kbits < quality_range[1]

    def _compare_quality(self, a: RankSource, b: RankSource) -> int:
        a_valid = self._is_valid_quality(a)
        b_valid = self._is_valid_quality(b)
        if a_valid and not b_valid:
            return -1
        if not a_valid and b_valid:
            return 1
        return self._compare_format(a, b)

    def _compare_format(self, a: RankSource, b: RankSource) -> int:
        if a.quality.file_format == b.quality.file_format:
            return self._compare_flags(a, b)
        a_index = self.quality_profile.get_quality_rank(a.quality.file_format)
        b_index = self.quality_profile.get_quality_rank(b.quality.file_format)
        return a_index - b_index

    def _compare_flags(self, a: RankSource, b: RankSource) -> int:
        a_score = sum(
            points
            for flag, points in self.quality_profile.flags
            if flag.lower() in a.source.indexer_flags
        )
        b_score = sum(
            points
            for flag, points in self.quality_profile.flags
            if flag.lower() in b.source.indexer_flags
        )
        if a_score == b_score:
            return self._compare_indexer(a, b)
        return a_score - b_score

    def _compare_indexer(self, a: RankSource, b: RankSource) -> int:
        a_index = self.quality_profile.get_indexer_rank(a.source.indexer_id)
        b_index = self.quality_profile.get_indexer_rank(b.source.indexer_id)
        if a_index == b_index:
            return self._compare_by_name(a, b)
        return a_index - b_index

    def _compare_by_name(self, a: RankSource, b: RankSource) -> int:
        a_score = add_scores(self.book, a)
        b_score = add_scores(self.book, b)
        if a_score == b_score:
            return self._compare_seeders(a, b)
        return b_score - a_score

    def _compare_seeders(self, a: RankSource, b: RankSource) -> int:
        return b.source.seeders - a.source.seeders


def add_scores(book: BookRequest, a: RankSource) -> int:
    score = 0
    if book.title not in a.source.title:
        score -= 100

    for author in book.authors:
        if author in a.source.title:
            score += 10

    for narrator in book.narrators:
        if narrator not in book.authors and narrator in a.source.title:
            score += 20

    return score
