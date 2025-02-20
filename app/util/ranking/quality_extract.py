# pyright: basic

from collections import defaultdict
from aiohttp import ClientSession
import aiohttp
import pydantic
from sqlmodel import Session
from app.util.prowlarr import prowlarr_config
import torrent_parser as tp
import os

from app.models import BookRequest, ProwlarrSource
from app.util.ranking.quality import FileFormat


class Quality(pydantic.BaseModel):
    kbits: float
    file_format: FileFormat


audio_file_formats = [
    ".3gp",
    ".aa",
    ".aac",
    ".aax",
    ".act",
    ".aiff",
    ".alac",
    ".amr",
    ".ape",
    ".au",
    ".awb",
    ".dss",
    ".dvf",
    ".flac",
    ".gsm",
    ".iklax",
    ".ivs",
    ".m4a",
    ".m4b",
    ".m4p",
    ".mmf",
    ".movpkg",
    ".mp3",
    ".mpc",
    ".msv",
    ".nmf",
    ".ogg",
    ".oga",
    ".mogg",
    ".opus",
    ".ra",
    ".rm",
    ".raw",
    ".rf64",
    ".sln",
    ".tta",
    ".voc",
    ".vox",
    ".wav",
    ".wma",
    ".wv",
    ".webm",
    ".8svx",
    ".cda",
]


async def extract_qualities(
    session: Session,
    client_session: ClientSession,
    source: ProwlarrSource,
    book: BookRequest,
) -> list[Quality]:
    api_key = prowlarr_config.get_api_key(session)
    if not api_key:
        raise ValueError("Prowlarr API key not set")

    book_seconds = book.runtime_length_min * 60

    data = None
    if source.download_url:
        try:
            for _ in range(3):
                async with client_session.get(
                    source.download_url,
                    headers={"X-Api-Key": api_key},
                ) as response:
                    if response.status == 500:
                        continue
                    data = await response.read()
                    break
            else:
                return []
        except aiohttp.NonHttpUrlRedirectClientError as e:
            print(e.args)  # tuple. first element is a magnet link
            return []

        if not data:
            return []
        # TODO: correctly fix wrong torrent parsing
        parsed = tp.decode(data, hash_fields={"pieces": (1, False)})
        actual_sizes: dict[FileFormat, int] = defaultdict(int)
        file_formats = set()
        if "info" not in parsed or "files" not in parsed["info"]:
            return []
        for f in parsed["info"]["files"]:
            size: int = f["length"]
            path: str = f["path"][-1]
            _, ext = os.path.splitext(path)
            ext = ext.lower()
            if ext == ".flac":
                file_formats.add("flac")
                actual_sizes["flac"] += size
            elif ext == ".m4b":
                file_formats.add("m4b")
                actual_sizes["m4b"] += size
            elif ext == ".mp3":
                file_formats.add("mp3")
                actual_sizes["mp3"] += size
            elif ext in audio_file_formats:
                file_formats.add("unknown")
                actual_sizes["unknown"] += size

        qualities = []
        for k, v in actual_sizes.items():
            qualities.append(
                Quality(
                    kbits=v / (book_seconds * 60) / 1024 * 8,
                    file_format=k,
                )
            )
        return qualities

    # TODO: use the magnet url to fetch the file information

    return []
