from contextlib import contextmanager
from os import getenv
from sqlalchemy import create_engine
from sqlmodel import Session, text

sqlite_path = getenv("SQLITE_PATH", "data/db.sqlite")

engine = create_engine(f"sqlite+pysqlite:///{sqlite_path}")


def get_session():
    with Session(engine) as session:
        session.execute(text("PRAGMA foreign_keys=ON"))  # pyright: ignore[reportDeprecated]
        yield session


# TODO: couldn't get a single function to work with FastAPI and allow for session creation wherever
@contextmanager
def open_session():
    with Session(engine) as session:
        session.execute(text("PRAGMA foreign_keys=ON"))  # pyright: ignore[reportDeprecated]
        yield session
