from os import getenv
from sqlalchemy import create_engine
from sqlmodel import Session, text

sqlite_path = getenv("SQLITE_PATH", "data/db.sqlite")

engine = create_engine(f"sqlite+pysqlite:///{sqlite_path}")


def get_session():
    with Session(engine) as session:
        session.execute(text("PRAGMA foreign_keys=ON"))  # pyright: ignore[reportDeprecated]
        yield session
