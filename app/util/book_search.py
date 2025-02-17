import asyncio
from datetime import datetime
import time
from typing import Literal, Optional
from urllib.parse import urlencode
from aiohttp import ClientSession
from sqlmodel import Session, col, select

from app.models import BookRequest

REFETCH_TTL = 60 * 60 * 24 * 7  # 1 week


async def get_audnexus_book(session: ClientSession, asin: str) -> Optional[BookRequest]:
    """
    https://audnex.us/#tag/Books/operation/getBookById
    """
    async with session.get(f"https://api.audnex.us/books/{asin}") as response:
        if not response.ok:
            return None
        book = await response.json()
    return BookRequest(
        asin=book["asin"],
        title=book["title"],
        subtitle=book.get("subtitle"),
        authors=[author["name"] for author in book["authors"]],
        narrators=[narrator["name"] for narrator in book["narrators"]],
        cover_image=book.get("image"),
        release_date=datetime.fromisoformat(book["releaseDate"]),
        runtime_length_min=book["runtimeLengthMin"],
    )


audible_region_type = Literal[
    "us", "ca", "uk", "au", "fr", "de", "jp", "it", "in", "es"
]
audible_regions: dict[audible_region_type, str] = {
    "us": ".com",
    "ca": ".ca",
    "uk": ".co.uk",
    "au": ".com.au",
    "fr": ".fr",
    "de": ".de",
    "jp": ".co.jp",
    "it": ".it",
    "in": ".in",
    "es": ".es",
}


async def list_audible_books(
    session: Session,
    client_session: ClientSession,
    query: str,
    num_results: int = 20,
    page: int = 0,
    audible_region: audible_region_type = "us",
) -> list[BookRequest]:
    """
    https://audible.readthedocs.io/en/latest/misc/external_api.html#get--1.0-catalog-products
    """
    params = {
        "num_results": num_results,
        "products_sort_by": "Relevance",
        "keywords": query,
        "page": page,
    }
    base_url = (
        f"https://api.audible{audible_regions[audible_region]}/1.0/catalog/products?"
    )
    url = base_url + urlencode(params)

    async with client_session.get(url) as response:
        response.raise_for_status()
        books_json = await response.json()

    # do not fetch book results we already have locally
    asins = set(asin_obj["asin"] for asin_obj in books_json["products"])
    books = get_existing_books(session, asins)
    for key in books.keys():
        asins.remove(key)

    # book ASINs we do not have => fetch and store
    coros = [get_audnexus_book(client_session, asin) for asin in asins]
    new_books = await asyncio.gather(*coros)
    new_books = [b for b in new_books if b]
    store_new_books(session, new_books)
    for b in new_books:
        books[b.asin] = b

    ordered: list[BookRequest] = []
    for asin_obj in books_json["products"]:
        book = books.get(asin_obj["asin"])
        if book:
            ordered.append(book)

    return ordered


def get_existing_books(session: Session, asins: set[str]) -> dict[str, BookRequest]:
    books = list(
        session.exec(
            select(BookRequest).where(
                col(BookRequest.asin).in_(asins),
            )
        ).all()
    )

    ok_books: list[BookRequest] = []
    for b in books:
        if b.updated_at.timestamp() + REFETCH_TTL < time.time():
            continue
        ok_books.append(b)

    return {b.asin: b for b in ok_books}


def store_new_books(session: Session, books: list[BookRequest]):
    assert all(b.user_username is None for b in books)
    asins = {b.asin: b for b in books}

    existing = list(
        session.exec(
            select(BookRequest).where(
                col(BookRequest.asin).in_(asins.keys()),
                col(BookRequest.user_username).is_(None),
            )
        ).all()
    )

    to_update: list[BookRequest] = []
    for b in existing:
        new_book = asins[b.asin]
        if b == new_book:
            continue
        b.title = new_book.title
        b.subtitle = new_book.subtitle
        b.authors = new_book.authors
        b.narrators = new_book.narrators
        b.cover_image = new_book.cover_image
        b.release_date = new_book.release_date
        b.runtime_length_min = new_book.runtime_length_min
        to_update.append(b)

    existing_asins = {b.asin for b in existing}
    to_add = [b for b in books if b.asin not in existing_asins]
    session.add_all(to_add + existing)
    session.commit()
