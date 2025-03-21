from typing import Any
from app.internal.indexers.abstract import AbstractIndexer
from app.internal.indexers.mam import MamIndexer


indexers: list[type[AbstractIndexer[Any]]] = [
    MamIndexer,
]
