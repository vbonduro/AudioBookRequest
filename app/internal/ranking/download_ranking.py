import asyncio
from functools import cmp_to_key
from typing import Callable

import pydantic
from aiohttp import ClientSession
from rapidfuzz import fuzz, utils
from sqlmodel import Session

from app.internal.models import BookRequest, ProwlarrSource
from app.internal.ranking.quality import quality_config
from app.internal.ranking.quality_extract import Quality, extract_qualities
from app.util.log import logger


class RankSource(pydantic.BaseModel):
    source: ProwlarrSource
    quality: Quality


async def rank_sources(
    session: Session,
    client_session: ClientSession,
    sources: list[ProwlarrSource],
    book: BookRequest,
) -> list[RankSource]:
    async def get_qualities(source: ProwlarrSource):
        qualities = await extract_qualities(session, client_session, source, book)
        return [RankSource(source=source, quality=q) for q in qualities]

    coros = [get_qualities(source) for source in sources]
    ranked = [x for y in await asyncio.gather(*coros) for x in y]

    compare = CompareSource(session, book)
    ranked.sort(key=cmp_to_key(compare))

    return ranked


class CompareSource:
    def __init__(self, session: Session, book: BookRequest):
        self.session = session
        self.book = book
        self.compare_order = [
            self._compare_valid,
            self._compare_title,
            self._compare_authors,
            self._compare_narrators,
            self._compare_format,
            self._compare_flags,
            self._compare_indexer,
            self._compare_subtitle,
            self._compare_age,
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

    def is_valid_quality(self, a: RankSource) -> bool:
        allowed_formats = quality_config.get_allowed_formats(self.session)
        if allowed_formats and a.quality.file_format not in allowed_formats:
            logger.debug(
                "Source rejected: format not in allowed formats",
                source_title=a.source.title,
                file_format=a.quality.file_format,
                allowed_formats=allowed_formats,
            )
            return False

        # epub is an ebook format — bitrate is meaningless, skip the kbits check
        if a.quality.file_format == "epub":
            logger.debug(
                "Source quality check",
                source_title=a.source.title,
                file_format=a.quality.file_format,
                kbits_check="skipped (epub)",
                valid=True,
            )
            return True

        match a.quality.file_format:
            case "flac":
                quality_range = quality_config.get_range(self.session, "quality_flac")
            case "m4b":
                quality_range = quality_config.get_range(self.session, "quality_m4b")
            case "mp3":
                quality_range = quality_config.get_range(self.session, "quality_mp3")
            case "unknown-audio":
                quality_range = quality_config.get_range(
                    self.session, "quality_unknown_audio"
                )
            case "unknown":
                quality_range = quality_config.get_range(
                    self.session, "quality_unknown"
                )

        valid = quality_range.from_kbits < a.quality.kbits < quality_range.to_kbits
        logger.debug(
            "Source quality check",
            source_title=a.source.title,
            file_format=a.quality.file_format,
            kbits=a.quality.kbits,
            range_from=quality_range.from_kbits,
            range_to=quality_range.to_kbits,
            valid=valid,
        )
        if a.source.protocol == "torrent":
            min_seeders = quality_config.get_min_seeders(self.session)
            if valid and a.source.seeders < min_seeders:
                logger.debug(
                    "Source rejected: insufficient seeders",
                    source_title=a.source.title,
                    seeders=a.source.seeders,
                    min_seeders=min_seeders,
                )
        return valid

    def _compare_valid(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        """Filter out any reasons that make it not valid"""
        if a.source.protocol == "torrent":
            a_valid = self.is_valid_quality(
                a
            ) and a.source.seeders >= quality_config.get_min_seeders(self.session)
        else:
            a_valid = self.is_valid_quality(a)

        if b.source.protocol == "torrent":
            b_valid = self.is_valid_quality(
                b
            ) and b.source.seeders >= quality_config.get_min_seeders(self.session)
        else:
            b_valid = self.is_valid_quality(b)

        if a_valid == b_valid:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return int(b_valid) - int(a_valid)

    def _compare_format(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if a.quality.file_format == b.quality.file_format:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        a_index = quality_config.calculate_quality_rank(
            self.session, a.quality.file_format
        )
        b_index = quality_config.calculate_quality_rank(
            self.session, b.quality.file_format
        )
        return a_index - b_index

    def _compare_flags(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_score = sum(
            f.score
            for f in quality_config.get_indexer_flags(self.session)
            if f.flag.lower() in a.source.indexer_flags
        )
        b_score = sum(
            f.score
            for f in quality_config.get_indexer_flags(self.session)
            if f.flag.lower() in b.source.indexer_flags
        )
        if a_score == b_score:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b_score - a_score

    def _compare_indexer(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_index = quality_config.calculate_indexer_rank(
            self.session, a.source.indexer_id
        )
        b_index = quality_config.calculate_indexer_rank(
            self.session, b.source.indexer_id
        )
        if a_index == b_index:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return a_index - b_index

    def _compare_title(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_title = exists_in_title(
            self.book.title,
            a.source.title,
            quality_config.get_title_exists_ratio(self.session),
        )
        b_title = exists_in_title(
            self.book.title,
            b.source.title,
            quality_config.get_title_exists_ratio(self.session),
        )
        if a_title == b_title:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return int(b_title) - int(a_title)

    def _compare_subtitle(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if not self.book.subtitle:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        a_title = exists_in_title(
            self.book.subtitle,
            a.source.title,
            quality_config.get_title_exists_ratio(self.session),
        )
        b_title = exists_in_title(
            self.book.subtitle,
            b.source.title,
            quality_config.get_title_exists_ratio(self.session),
        )
        if a_title == b_title:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return int(b_title) - int(a_title)

    def _compare_authors(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        a_score = max(
            vaguely_exist_in_title(
                self.book.authors,
                a.source.title,
                quality_config.get_name_exists_ratio(self.session),
            ),
            fuzzy_author_narrator_match(
                a.source.book_metadata.authors,
                self.book.authors,
                quality_config.get_name_exists_ratio(self.session),
            ),
        )
        b_score = max(
            vaguely_exist_in_title(
                self.book.authors,
                b.source.title,
                quality_config.get_name_exists_ratio(self.session),
            ),
            fuzzy_author_narrator_match(
                b.source.book_metadata.authors,
                self.book.authors,
                quality_config.get_name_exists_ratio(self.session),
            ),
        )
        if a_score == b_score:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b_score - a_score

    def _compare_narrators(
        self, a: RankSource, b: RankSource, next_compare: int
    ) -> int:
        a_score = max(
            vaguely_exist_in_title(
                self.book.narrators,
                a.source.title,
                quality_config.get_name_exists_ratio(self.session),
            ),
            fuzzy_author_narrator_match(
                a.source.book_metadata.narrators,
                self.book.narrators,
                quality_config.get_name_exists_ratio(self.session),
            ),
        )
        b_score = max(
            vaguely_exist_in_title(
                self.book.narrators,
                b.source.title,
                quality_config.get_name_exists_ratio(self.session),
            ),
            fuzzy_author_narrator_match(
                b.source.book_metadata.narrators,
                self.book.narrators,
                quality_config.get_name_exists_ratio(self.session),
            ),
        )
        if a_score == b_score:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b_score - a_score

    def _compare_seeders(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if a.source.protocol == "usenet" or b.source.protocol == "usenet":
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        if a.source.seeders == b.source.seeders:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        return b.source.seeders - a.source.seeders

    def _compare_age(self, a: RankSource, b: RankSource, next_compare: int) -> int:
        if a.source.protocol != b.source.protocol:
            return self._get_next_compare(next_compare)(a, b, next_compare + 1)
        # With both usenet and torrents: newer => better
        return int((a.source.publish_date - b.source.publish_date).total_seconds())


def fuzzy_author_narrator_match(
    source_people: list[str], book_people: list[str], name_exists_ratio: int
) -> int:
    """Calculate a fuzzy matching score between two lists of author/narrator names."""
    if not source_people or not book_people:
        return 0
    score = 0
    for book_person in book_people:
        best_match = 0
        for source_person in source_people:
            match_score = fuzz.token_set_ratio(
                book_person, source_person, processor=utils.default_process
            )
            best_match = max(best_match, match_score)

        # Only count matches above threshold
        if best_match > name_exists_ratio:
            score += 1

    return score


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
