import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError

from app.internal import book_search


class BookMetadataFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_audnexus_when_audimeta_connection_fails(self):
        book = object()
        with (
            patch.object(
                book_search, "_get_audimeta_book", new_callable=AsyncMock) as audimeta,
            patch.object(
                book_search, "_get_audnexus_book", new_callable=AsyncMock) as audnexus,
        ):
            audimeta.side_effect = ClientError("DNS lookup failed")
            audnexus.return_value = book

            result = await book_search.get_book_by_asin(None, "B000TEST", "ca")

        self.assertIs(result, book)
        audnexus.assert_awaited_once_with(None, "B000TEST", "ca")

    async def test_returns_none_when_both_providers_are_unavailable(self):
        with (
            patch.object(
                book_search, "_get_audimeta_book", new_callable=AsyncMock) as audimeta,
            patch.object(
                book_search, "_get_audnexus_book", new_callable=AsyncMock) as audnexus,
        ):
            audimeta.side_effect = ClientError("DNS lookup failed")
            audnexus.side_effect = asyncio.TimeoutError()

            result = await book_search.get_book_by_asin(None, "B000TEST", "ca")

        self.assertIsNone(result)
