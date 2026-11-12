"""An Audible outage is reported as such instead of looking like "nothing found"."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import NoReturn, cast

import aiohttp
import pytest
from aiohttp import ClientResponseError, ClientSession, RequestInfo
from fastapi.testclient import TestClient
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from app.internal.audible.search import AudibleUnavailable, search_audible_books
from tests.constants import ASIN
from tests.http import json_object


class _OfflineSession:
    """Stands in for an aiohttp session whose requests never connect."""

    def get(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise aiohttp.ClientConnectionError("offline")


def _search(raise_on_error: bool) -> Sequence[object]:
    return asyncio.run(
        search_audible_books(
            cast(ClientSession, cast(object, _OfflineSession())),
            "dune",
            raise_on_error=raise_on_error,
        )
    )


def test_failed_search_is_empty_by_default() -> None:
    assert _search(raise_on_error=False) == []


def test_failed_search_can_raise() -> None:
    with pytest.raises(AudibleUnavailable):
        _search(raise_on_error=True)


def test_search_endpoint_reports_the_outage(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def offline(*_args: object, **_kwargs: object) -> list[object]:
        raise AudibleUnavailable("offline")

    monkeypatch.setattr("app.routers.api.search.search_audible_books", offline)
    response = admin_client.get("/api/search", params={"q": "dune"})
    assert response.status_code == 502
    assert json_object(response)["detail"] == "Audible is unavailable"


def _status_error(status: int) -> ClientResponseError:
    url = URL("https://api.audible.com/1.0/catalog/products/X")
    info = RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict[str]()), url)
    return ClientResponseError(info, (), status=status)


def _fail_single_book(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    async def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr("app.routers.api.requests.get_single_book", fail)


@pytest.mark.parametrize(
    "error",
    [
        _status_error(404),
        _status_error(400),
        # Audible answers an unknown ASIN with a stub product that fails validation
        ValueError("product.release_date missing"),
    ],
)
def test_request_for_unknown_asin_is_not_found(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _fail_single_book(monkeypatch, error)
    assert admin_client.post("/api/requests/B00UNKNOWN").status_code == 404


@pytest.mark.parametrize(
    "error",
    [
        aiohttp.ClientConnectionError("offline"),
        TimeoutError(),
        _status_error(503),
        _status_error(429),
    ],
)
def test_request_during_an_outage_is_a_bad_gateway(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _fail_single_book(monkeypatch, error)
    response = admin_client.post("/api/requests/B00UNKNOWN")
    assert response.status_code == 502
    assert response.json()["detail"] == "Audible is unavailable"


def test_cached_book_is_requested_without_asking_audible(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_single_book(monkeypatch, aiohttp.ClientConnectionError("offline"))
    # the seed already caches this book, so no Audible request is made
    admin_client.delete(f"/api/requests/{ASIN}")
    assert admin_client.post(f"/api/requests/{ASIN}").status_code == 200
