from os import getenv
from sqlalchemy import create_engine
from sqlmodel import Session

sqlite_path = getenv("SQLITE_PATH", "data/db.sqlite")

engine = create_engine(f"sqlite+pysqlite:///{sqlite_path}")


def get_session():
    with Session(engine) as session:
        yield session
