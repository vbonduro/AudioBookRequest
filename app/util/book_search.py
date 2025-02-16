import asyncio
from typing import Literal, Optional
from urllib.parse import urlencode
from aiohttp import ClientSession
from async_lru import alru_cache
import pydantic


class BookResult(pydantic.BaseModel):
    asin: str
    title: str
    subtitle: Optional[str]
    authors: list[str]
    narrators: list[str]
    cover_image: Optional[str]
    already_requested: bool = False


@alru_cache(ttl=300)
async def get_audnexus_book(session: ClientSession, asin: str) -> Optional[BookResult]:
    """
    https://audnex.us/#tag/Books/operation/getBookById
    """
    async with session.get(f"https://api.audnex.us/books/{asin}") as response:
        if not response.ok:
            return None
        book = await response.json()
    return BookResult(
        asin=book["asin"],
        title=book["title"],
        subtitle=book.get("subtitle"),
        authors=[author["name"] for author in book["authors"]],
        narrators=[narrator["name"] for narrator in book["narrators"]],
        cover_image=book.get("image"),
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


@alru_cache(ttl=300)
async def list_audible_books(
    session: ClientSession,
    query: str,
    num_results: int = 20,
    page: int = 0,
    audible_region: audible_region_type = "us",
) -> list[BookResult]:
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

    async with session.get(url) as response:
        response.raise_for_status()
        books_json = await response.json()

    coros = [
        get_audnexus_book(session, asin_obj["asin"])
        for asin_obj in books_json["products"]
    ]
    books = await asyncio.gather(*coros)
    return [b for b in books if b]
