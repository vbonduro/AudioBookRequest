# pyright: reportUnknownVariableType=false
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    pass


class User(BaseModel, table=True):
    username: bytes = Field(primary_key=True)
    password: bytes
