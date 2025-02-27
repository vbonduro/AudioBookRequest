from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlmodel import Session, text

from app.internal.env_settings import Settings

sqlite_path = Settings().get_sqlite_path()
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
