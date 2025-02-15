# pyright: reportUnknownVariableType=false
from datetime import datetime
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    pass


class User(BaseModel, table=True):
    username: str = Field(primary_key=True)
    password: str


class BookRequest(BaseModel, table=True):
    guid: str = Field(primary_key=True)
    title: str
    indexerId: int
    download_url: str
    publishDate: datetime
    # TODO: Remove seeders/leechers when we have a way of getting them dynamically
    seeders: int
    leechers: int


class Indexer(BaseModel):
    id: int
    name: str
    enabled: bool
    privacy: str
