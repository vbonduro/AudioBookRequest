# pyright: reportUnknownVariableType=false
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    pass


class User(BaseModel, table=True):
    username: str = Field(primary_key=True)
    password: str
