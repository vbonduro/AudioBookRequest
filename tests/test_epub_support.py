"""epub sources are ranked by allowed format instead of by bitrate."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast

import pytest
from aiohttp import ClientSession
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.internal.models import (
    Audiobook,
    BookMetadata,
    ManualBookRequest,
    TorrentSource,
)
from app.internal.prowlarr.util import prowlarr_config
from app.internal.ranking.download_ranking import CompareSource, RankSource
from app.internal.ranking.quality import FileFormat, quality_config
from app.internal.ranking.quality_extract import (
    Quality,
    detect_file_format,
    extract_qualities,
)
from tests.constants import ASIN
from tests.http import json_object


def _source(title: str, filetype: str | None = None) -> TorrentSource:
    return TorrentSource(
        guid="guid",
        indexer_id=1,
        indexer="MAM",
        title=title,
        size=2_000_000,
        publish_date=datetime(2026, 1, 1),
        info_url=None,
        indexer_flags=[],
        seeders=10,
        leechers=0,
        book_metadata=BookMetadata(filetype=filetype),
    )


def _book(db: Session, runtime_min: int = 600) -> Audiobook:
    book = db.get(Audiobook, ASIN)
    assert book is not None
    book.runtime_length_min = runtime_min
    return book


@pytest.mark.parametrize(
    ("title", "filetype", "expected"),
    [
        ("Dune [EPUB]", None, "epub"),
        ("Dune (mp3)", None, "mp3"),
        ("Dune audiobook", None, "unknown-audio"),
        ("Dune", None, "unknown"),
        # the indexer's own filetype wins over a guess from the title
        ("Dune audiobook", "epub", "epub"),
        ("Dune", "EPUB", "epub"),
        ("Dune [EPUB]", "pdf", "epub"),
    ],
)
def test_detect_file_format(
    title: str, filetype: str | None, expected: FileFormat
) -> None:
    assert detect_file_format(_source(title, filetype)) == expected


def test_epub_quality_ignores_runtime(db: Session) -> None:
    prowlarr_config.set_api_key(db, "key")
    book = _book(db, runtime_min=0)
    qualities = asyncio.run(
        extract_qualities(
            db,
            cast(ClientSession, cast(object, None)),
            _source("Dune [EPUB]"),
            book,
        )
    )
    assert qualities == [Quality(kbits=0, file_format="epub")]


def test_manual_request_stays_unknown(db: Session) -> None:
    prowlarr_config.set_api_key(db, "key")
    manual = ManualBookRequest(user_username="root", title="Dune", authors=["Herbert"])
    qualities = asyncio.run(
        extract_qualities(
            db,
            cast(ClientSession, cast(object, None)),
            _source("Dune [EPUB]"),
            manual,
        )
    )
    assert qualities == [Quality(kbits=0, file_format="unknown")]


def test_allowed_formats_default_allows_everything(db: Session) -> None:
    assert quality_config.get_allowed_formats(db) == []


def test_allowed_formats_roundtrip_and_reset(db: Session) -> None:
    quality_config.set_allowed_formats(db, ["epub"])
    assert quality_config.get_allowed_formats(db) == ["epub"]
    quality_config.reset_all(db)
    assert quality_config.get_allowed_formats(db) == []


def test_epub_is_valid_regardless_of_bitrate_when_allowed(db: Session) -> None:
    quality_config.set_allowed_formats(db, ["epub"])
    compare = CompareSource(db, _book(db))
    ranked = RankSource(
        source=_source("Dune [EPUB]"),
        quality=Quality(kbits=0, file_format="epub"),
    )
    assert compare._is_valid_quality(ranked)  # pyright: ignore[reportPrivateUsage]


def test_epub_is_not_accepted_unless_allowed(db: Session) -> None:
    """An audiobook request must not be fulfilled with an ebook by default."""
    compare = CompareSource(db, _book(db))
    ranked = RankSource(
        source=_source("Dune [EPUB]"),
        quality=Quality(kbits=0, file_format="epub"),
    )
    assert not compare._is_valid_quality(ranked)  # pyright: ignore[reportPrivateUsage]
    quality_config.set_allowed_formats(db, ["mp3"])
    assert not compare._is_valid_quality(ranked)  # pyright: ignore[reportPrivateUsage]


def test_allowed_formats_filters_other_formats(db: Session) -> None:
    quality_config.set_allowed_formats(db, ["epub"])
    compare = CompareSource(db, _book(db))
    mp3 = RankSource(
        source=_source("Dune (mp3)"),
        quality=Quality(kbits=128, file_format="mp3"),
    )
    epub = RankSource(
        source=_source("Dune [EPUB]"),
        quality=Quality(kbits=0, file_format="epub"),
    )
    assert not compare._is_valid_quality(mp3)  # pyright: ignore[reportPrivateUsage]
    assert compare._is_valid_quality(epub)  # pyright: ignore[reportPrivateUsage]


def test_audio_still_ranked_by_bitrate_without_allowed_formats(db: Session) -> None:
    compare = CompareSource(db, _book(db))
    in_range = RankSource(
        source=_source("Dune (mp3)"),
        quality=Quality(kbits=128, file_format="mp3"),
    )
    out_of_range = RankSource(
        source=_source("Dune (mp3)"),
        quality=Quality(kbits=100_000, file_format="mp3"),
    )
    assert compare._is_valid_quality(in_range)  # pyright: ignore[reportPrivateUsage]
    assert not compare._is_valid_quality(out_of_range)  # pyright: ignore[reportPrivateUsage]


def test_allowed_formats_api(admin_client: TestClient) -> None:
    body = {
        "auto_download": False,
        "flac_range": {"from_kbits": 1, "to_kbits": 1000},
        "m4b_range": {"from_kbits": 1, "to_kbits": 1000},
        "mp3_range": {"from_kbits": 1, "to_kbits": 1000},
        "unknown_audio_range": {"from_kbits": 1, "to_kbits": 1000},
        "unknown_range": {"from_kbits": 1, "to_kbits": 1000},
        "min_seeders": 2,
        "name_ratio": 75,
        "title_ratio": 90,
    }
    got = json_object(admin_client.get("/api/settings/download"))
    assert got["allowed_formats"] == []

    set_epub = admin_client.patch(
        "/api/settings/download", json={**body, "allowed_formats": ["epub"]}
    )
    assert set_epub.status_code == 204
    got = json_object(admin_client.get("/api/settings/download"))
    assert got["allowed_formats"] == ["epub"]

    # omitting the field leaves the setting alone
    assert admin_client.patch("/api/settings/download", json=body).status_code == 204
    got = json_object(admin_client.get("/api/settings/download"))
    assert got["allowed_formats"] == ["epub"]

    # an empty list means "allow any format"
    cleared = admin_client.patch(
        "/api/settings/download", json={**body, "allowed_formats": []}
    )
    assert cleared.status_code == 204
    got = json_object(admin_client.get("/api/settings/download"))
    assert got["allowed_formats"] == []

    invalid = admin_client.patch(
        "/api/settings/download", json={**body, "allowed_formats": ["docx"]}
    )
    assert invalid.status_code == 422


def test_allowed_formats_settings_page(admin_client: TestClient, db: Session) -> None:
    form = {
        "flac_from": 1,
        "flac_to": 1000,
        "m4b_from": 1,
        "m4b_to": 1000,
        "mp3_from": 1,
        "mp3_to": 1000,
        "unknown_audio_from": 1,
        "unknown_audio_to": 1000,
        "unknown_from": 1,
        "unknown_to": 1000,
        "min_seeders": 2,
        "name_ratio": 75,
        "title_ratio": 90,
    }
    page = admin_client.get("/settings/download")
    assert page.status_code == 200
    assert 'name="allowed_formats"' in page.text

    saved = admin_client.post(
        "/settings/download/hx-sliders", data={**form, "allowed_formats": ["epub"]}
    )
    assert saved.status_code == 200
    assert quality_config.get_allowed_formats(db) == ["epub"]

    # unchecking every box means any format is allowed again
    saved = admin_client.post("/settings/download/hx-sliders", data=form)
    assert saved.status_code == 200
    db.expire_all()
    assert quality_config.get_allowed_formats(db) == []
