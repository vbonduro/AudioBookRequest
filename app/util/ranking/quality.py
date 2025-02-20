import math
from typing import Literal
import pydantic

FileFormat = Literal["flac", "m4b", "mp3", "unknown"]


class QualityProfile(pydantic.BaseModel):
    FLAC: tuple[float, float] = (0, math.inf)
    M4B: tuple[float, float] = (0, math.inf)
    MP3: tuple[float, float] = (0, math.inf)
    UNKNOWN: tuple[float, float] = (0, math.inf)

    flags: list[tuple[str, int]] = []

    format_order: list[FileFormat] = ["flac", "m4b", "mp3", "unknown"]
    """Order of file formats from highest to lowest quality"""

    indexer_order: list[int] = []
    """Order of indexers from highest to lowest quality"""

    def get_quality_rank(self, file_format: FileFormat) -> int:
        try:
            return self.format_order.index(file_format)
        except ValueError:
            return len(self.format_order)

    def get_indexer_rank(self, indexer_id: int) -> int:
        try:
            return self.indexer_order.index(indexer_id)
        except ValueError:
            return len(self.format_order)
