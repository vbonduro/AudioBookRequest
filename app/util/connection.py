import aiohttp


async def get_connection():
    async with aiohttp.ClientSession() as session:
        yield session
