from typing import Literal
import pydantic


FileFormat = Literal["flac", "m4b", "mp3", "unknown-audio", "unknown"]


class QualityProfile(pydantic.BaseModel):
    FLAC: tuple[float, float] = (20.0, 400.0)
    M4B: tuple[float, float] = (20.0, 400.0)
    MP3: tuple[float, float] = (20.0, 400.0)
    UNKNOWN_AUDIO: tuple[float, float] = (20.0, 400.0)
    UNKNOWN: tuple[float, float] = (20.0, 400.0)

    indexer_flags: list[tuple[str, int]] = []
    format_order: list[FileFormat] = ["flac", "m4b", "mp3", "unknown-audio", "unknown"]
    """Order of file formats from highest to lowest quality"""
    indexer_order: list[int] = []
    """Order of indexers from highest to lowest quality"""
    name_exists_ratio: int = 75
    title_exists_ratio: int = 90

    def calculate_quality_rank(self, file_format: FileFormat) -> int:
        try:
            return self.format_order.index(file_format)
        except ValueError:
            return len(self.format_order)

    def calculate_indexer_rank(self, indexer_id: int) -> int:
        try:
            return self.indexer_order.index(indexer_id)
        except ValueError:
            return len(self.format_order)
