# pyright: reportUnknownVariableType=false
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    pass


class User(BaseModel, table=True):
    username: str = Field(primary_key=True)
    password: str
    group: str = Field(
        default="untrusted", sa_column_kwargs={"server_default": "untrusted"}
    )
    """
    untrusted: Requests need to be manually reviewed
    trusted: Requests are automatically downloaded if possible
    admin: Can approve or deny requests, change settings, etc.
    """


class BookRequest(BaseModel, table=True):
    asin: str = Field(primary_key=True)
    user_username: str = Field(
        foreign_key="user.username", nullable=False, ondelete="CASCADE"
    )


class Indexer(BaseModel):
    id: int
    name: str
    enabled: bool
    privacy: str
