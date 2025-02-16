# pyright: reportUnknownVariableType=false
from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    pass


class GroupEnum(str, Enum):
    untrusted = "untrusted"
    trusted = "trusted"
    admin = "admin"


class User(BaseModel, table=True):
    username: str = Field(primary_key=True)
    password: str
    group: GroupEnum = Field(
        default=GroupEnum.untrusted,
        sa_column_kwargs={"server_default": "untrusted"},
    )
    """
    untrusted: Requests need to be manually reviewed
    trusted: Requests are automatically downloaded if possible
    admin: Can approve or deny requests, change settings, etc.
    """

    def is_admin(self):
        return self.group == GroupEnum.admin


class BookRequest(BaseModel, table=True):
    asin: str = Field(primary_key=True)
    user_username: str = Field(
        foreign_key="user.username", nullable=False, ondelete="CASCADE"
    )


# TODO: do we even need this?
class ProwlarrSource(BaseModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    """
    ProwlarrSources are not unique by their guid. We could have multiple books all in the same source.
    https://sqlmodel.tiangolo.com/tutorial/automatic-id-none-refresh/
    """
    guid: str
    indexer_id: int = Field(
        foreign_key="indexer.id", nullable=False, ondelete="CASCADE"
    )
    title: str
    seeders: int
    leechers: int
    size: int  # in bytes
    publish_date: datetime = Field(default_factory=datetime.now)


class Indexer(BaseModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    enabled: bool
    privacy: str


class Config(BaseModel, table=True):
    key: str = Field(primary_key=True)
    value: str
