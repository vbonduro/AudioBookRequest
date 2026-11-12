"""Search query building, valid-only auto-download, retry backoff and the scheduler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.internal.models import Audiobook, AudiobookRequest
from app.internal.query import BACKOFF_MAX_MINUTES, backoff_delay, build_search_query
from app.internal.ranking.quality import quality_config
from app.internal.scheduler import get_due_books, retry_due_books
from tests.constants import ASIN
from tests.http import json_object
from tests.mock_services import MockServer


def _book(db: Session, asin: str = ASIN) -> Audiobook:
    db.expire_all()
    book = db.get(Audiobook, asin)
    assert book is not None
    return book


def _requested_only_by(db: Session, *usernames: str, asin: str = ASIN) -> None:
    """The seed has `trusted` requesting every book; replace that with these users."""
    for existing in db.exec(
        select(AudiobookRequest).where(AudiobookRequest.asin == asin)
    ).all():
        db.delete(existing)
    db.commit()
    for username in usernames:
        db.add(AudiobookRequest(asin=asin, user_username=username))
    db.commit()


def _grabs(prowlarr: MockServer) -> list[object]:
    return [r for r in prowlarr.requests if r["method"] == "POST"]


def _searched_for(prowlarr: MockServer) -> list[str]:
    return [
        r["query"]["query"]
        for r in prowlarr.requests
        if r["method"] == "GET" and r["path"].endswith("/api/v1/search")
    ]


# -- query ------------------------------------------------------------------
def test_query_is_title_and_first_author(db: Session) -> None:
    assert build_search_query(_book(db)) == "Test Book Mock Author"


def test_query_without_authors_is_title_only(db: Session) -> None:
    book = _book(db)
    book.authors = []
    assert build_search_query(book) == "Test Book"


def test_custom_query_wins_and_is_trimmed(db: Session) -> None:
    assert build_search_query(_book(db), "  something else ") == "something else"
    assert build_search_query(_book(db), "   ") == "Test Book Mock Author"


def test_sources_use_default_and_custom_query(
    admin_client: TestClient, prowlarr: MockServer
) -> None:
    default = json_object(admin_client.get(f"/api/requests/{ASIN}/sources"))
    assert default["query_used"] == "Test Book Mock Author"
    custom = json_object(
        admin_client.get(f"/api/requests/{ASIN}/sources", params={"query": "dune"})
    )
    assert custom["query_used"] == "dune"
    assert _searched_for(prowlarr) == ["Test Book Mock Author", "dune"]


# -- backoff ----------------------------------------------------------------
def test_backoff_doubles_and_is_capped() -> None:
    assert backoff_delay(1) == timedelta(minutes=30)
    assert backoff_delay(2) == timedelta(minutes=60)
    assert backoff_delay(30) == timedelta(minutes=BACKOFF_MAX_MINUTES)


# -- auto download ----------------------------------------------------------
def test_auto_download_grabs_a_valid_source(
    admin_client: TestClient, prowlarr: MockServer, db: Session
) -> None:
    response = admin_client.post(f"/api/requests/{ASIN}/auto-download")
    assert response.status_code == 204
    assert len(_grabs(prowlarr)) == 1
    book = _book(db)
    assert book.fulfilled
    assert book.downloaded_file == "Test Book m4b"
    assert book.search_attempts == 0


def test_auto_download_ignores_sources_in_other_formats(
    admin_client: TestClient, prowlarr: MockServer, db: Session
) -> None:
    quality_config.set_allowed_formats(db, ["epub"])
    response = admin_client.post(f"/api/requests/{ASIN}/auto-download")
    assert response.status_code == 204
    assert _grabs(prowlarr) == []
    book = _book(db)
    assert not book.fulfilled
    assert book.downloaded_file is None
    assert book.search_attempts == 1
    assert book.next_search_at is not None
    assert book.next_search_at > datetime.now(UTC) + timedelta(minutes=25)


def test_manual_auto_download_resets_the_backoff(
    admin_client: TestClient, prowlarr: MockServer, db: Session
) -> None:
    book = _book(db)
    book.search_attempts = 5
    book.next_search_at = datetime.now(UTC) + timedelta(hours=10)
    db.add(book)
    db.commit()

    assert admin_client.post(f"/api/requests/{ASIN}/auto-download").status_code == 204
    assert len(_grabs(prowlarr)) == 1
    book = _book(db)
    assert book.fulfilled
    assert book.search_attempts == 0
    assert book.next_search_at is None


# -- scheduler --------------------------------------------------------------
def test_due_books_need_a_trusted_requester(db: Session) -> None:
    _requested_only_by(db, "untrusted")
    assert get_due_books(db, datetime.now(UTC)) == []
    _requested_only_by(db, "untrusted", "trusted")
    assert [b.asin for b in get_due_books(db, datetime.now(UTC))] == [ASIN]


def test_due_books_skip_fulfilled_and_not_yet_due(db: Session) -> None:
    # the seed has a trusted request for both the open and the fulfilled book
    now = datetime.now(UTC)

    book = _book(db)
    book.next_search_at = now + timedelta(hours=1)
    db.add(book)
    db.commit()
    assert get_due_books(db, now) == []

    book = _book(db)
    book.next_search_at = now - timedelta(minutes=1)
    db.add(book)
    db.commit()
    assert [b.asin for b in get_due_books(db, now)] == [ASIN]


def test_due_books_list_a_book_once(db: Session) -> None:
    _requested_only_by(db, "trusted", "root")
    assert [b.asin for b in get_due_books(db, datetime.now(UTC))] == [ASIN]


def test_scheduler_does_nothing_when_auto_download_is_off(
    prowlarr: MockServer, db: Session
) -> None:
    asyncio.run(retry_due_books())
    assert prowlarr.requests == []
    assert not _book(db).fulfilled


def test_scheduler_downloads_due_books(prowlarr: MockServer, db: Session) -> None:
    quality_config.set_auto_download(db, True)
    asyncio.run(retry_due_books())
    assert len(_grabs(prowlarr)) == 1
    assert _book(db).fulfilled


def test_scheduler_backs_off_when_nothing_suitable(
    prowlarr: MockServer, db: Session
) -> None:
    quality_config.set_auto_download(db, True)
    quality_config.set_allowed_formats(db, ["epub"])

    asyncio.run(retry_due_books())
    assert _grabs(prowlarr) == []
    assert _book(db).search_attempts == 1

    # not due again yet, so a second run leaves it alone
    prowlarr.requests.clear()
    asyncio.run(retry_due_books())
    assert prowlarr.requests == []
    assert _book(db).search_attempts == 1


def test_scheduler_backs_off_when_the_grab_fails(
    prowlarr: MockServer, db: Session
) -> None:
    quality_config.set_auto_download(db, True)
    prowlarr.state["grab_status"] = 500

    asyncio.run(retry_due_books())
    book = _book(db)
    assert not book.fulfilled
    assert book.search_attempts == 1
    assert book.next_search_at is not None


# -- status API -------------------------------------------------------------
def test_request_status_endpoint(
    admin_client: TestClient, trusted_client: TestClient, db: Session
) -> None:
    assert trusted_client.get("/api/requests/NOSUCHASIN").status_code == 404

    book = _book(db)
    book.search_attempts = 2
    book.next_search_at = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    db.add(book)
    db.commit()

    got = json_object(trusted_client.get(f"/api/requests/{ASIN}"))
    book_json = got["book"]
    assert isinstance(book_json, dict)
    assert book_json["fulfilled"] is False
    assert book_json["search_attempts"] == 2
    assert book_json["next_search_at"] == "2030-01-01T12:00:00Z"
    assert book_json["release_date"]
    assert book_json["downloaded_file"] is None

    assert admin_client.get(f"/api/requests/{ASIN}").status_code == 200
    assert admin_client.get("/api/requests/NOSUCHASIN").status_code == 404


def test_request_status_hidden_from_other_users(
    trusted_client: TestClient, db: Session
) -> None:
    _requested_only_by(db, "root")
    assert trusted_client.get(f"/api/requests/{ASIN}").status_code == 404


def test_sources_page_escapes_the_query(
    admin_client: TestClient, prowlarr: MockServer
) -> None:
    _ = prowlarr
    hostile = '"><script>alert(1)</script>'
    response = admin_client.get(
        f"/wishlist/sources/{ASIN}", params={"only_body": "true", "query": hostile}
    )
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
