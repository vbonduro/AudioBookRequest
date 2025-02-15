from os import getenv
from sqlalchemy import create_engine
from sqlmodel import Session

host = getenv("POSTGRES_HOST", "localhost")
password = getenv("POSTGRES_PASSWORD", "docker")
user = getenv("POSTGRES_USER", "docker")
database = getenv("POSTGRES_DATABASE", "docker")
port = getenv("POSTGRES_PORT", "5432")

engine = create_engine(
    f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
)


def get_session():
    with Session(engine) as session:
        yield session
