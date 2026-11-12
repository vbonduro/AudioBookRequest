"""Carry the fork's per-request retry columns across the upgrade to upstream's schema.

The fork stored `search_attempts`, `next_search_at` and `downloaded_file` on the
`bookrequest` table. Upstream's migration `d0fac85afd0f` drops that table, and
`a7c3e91b5d24` re-adds the three columns on `audiobook`. STOP THE APP FIRST, then run:

    1. python scripts/fork_db_carryover.py save    /config/db.sqlite
    2. alembic upgrade heads        (the container does this on start)
    3. python scripts/fork_db_carryover.py restore /config/db.sqlite

`save` must run before the new image starts, because the upgrade drops `bookrequest`,
and anything written to it after `save` is lost. `save` makes a backup copy, stashes
the values in `fork_carryover` and points alembic at the last revision both histories
share. `restore` copies the values onto `audiobook` and removes the stash.

When several users requested the same book, the values come from one request: the one
with a downloaded file, then the most failed attempts, then the most recent. Stored
timestamps are copied as written; the fork wrote naive local time and the new code reads
them as UTC, so on a host that is not on UTC, retry times shift by the offset.

Only the standard library is needed.
"""

import argparse
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

FORK_REVISION = "6d620131023f"
SHARED_REVISION = "63489e50e337"
FINAL_REVISION = "a7c3e91b5d24"
STASH = "fork_carryover"


def _backup(path: Path, label: str) -> Path:
    stamp = f"{datetime.now():%Y%m%d%H%M%S%f}"
    target = path.with_name(f"{path.name}.{label}-{stamp}")
    if target.exists():
        sys.exit(f"{target} already exists; refusing to overwrite a backup")
    # sqlite3's backup API gives a consistent copy even if the file is being written
    with closing(sqlite3.connect(path)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target


def _connect(path: Path) -> sqlite3.Connection:
    # autocommit, so transactions are only ever the explicit ones in `_transaction`
    return sqlite3.connect(path, isolation_level=None)


@contextmanager
def _transaction(db: sqlite3.Connection) -> Iterator[None]:
    """One atomic unit, DDL included (Python's implicit transactions skip DDL)."""
    db.execute("BEGIN")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


def _revision(db: sqlite3.Connection) -> str | None:
    row = db.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else str(row[0])


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def save(path: Path) -> None:
    with closing(_connect(path)) as probe:
        revision = _revision(probe)
        if revision != FORK_REVISION:
            sys.exit(f"expected alembic revision {FORK_REVISION}, found {revision}")
        if _has_table(probe, STASH):
            sys.exit(f"{STASH} already exists; refusing to overwrite a previous save")

    backup = _backup(path, "pre-save")
    print(f"backup written to {backup}")

    with closing(_connect(path)) as db:
        with _transaction(db):
            db.execute(
                f"""CREATE TABLE {STASH} AS
                    SELECT asin, downloaded_file, search_attempts, next_search_at
                    FROM (
                        SELECT asin, downloaded_file, search_attempts, next_search_at,
                               ROW_NUMBER() OVER (
                                   PARTITION BY asin
                                   ORDER BY downloaded_file IS NOT NULL DESC,
                                            search_attempts DESC,
                                            updated_at DESC
                               ) AS rank
                        FROM bookrequest
                        WHERE user_username IS NOT NULL
                    )
                    WHERE rank = 1
                      AND (downloaded_file IS NOT NULL
                           OR search_attempts > 0
                           OR next_search_at IS NOT NULL)"""
            )
            db.execute("UPDATE alembic_version SET version_num = ?", (SHARED_REVISION,))
        (count,) = db.execute(f"SELECT COUNT(*) FROM {STASH}").fetchone()
    print(f"saved {count} books; alembic now at {SHARED_REVISION}")


def restore(path: Path) -> None:
    with closing(_connect(path)) as db:
        revision = _revision(db)
        if revision != FINAL_REVISION:
            sys.exit(
                f"expected alembic revision {FINAL_REVISION}, found {revision}; "
                "run `alembic upgrade heads` first"
            )
        if not _has_table(db, STASH):
            sys.exit(f"no {STASH} table; was `save` run before the upgrade?")

        backup = _backup(path, "pre-restore")
        print(f"backup written to {backup}")
        with _transaction(db):
            db.execute(
                f"""UPDATE audiobook SET
                        downloaded_file = (SELECT c.downloaded_file FROM {STASH} c
                                           WHERE c.asin = audiobook.asin),
                        search_attempts = COALESCE((SELECT c.search_attempts FROM {STASH} c
                                           WHERE c.asin = audiobook.asin), 0),
                        next_search_at = (SELECT c.next_search_at FROM {STASH} c
                                          WHERE c.asin = audiobook.asin)
                    WHERE asin IN (SELECT asin FROM {STASH})"""
            )
            (restored,) = db.execute(
                f"SELECT COUNT(*) FROM audiobook WHERE asin IN (SELECT asin FROM {STASH})"
            ).fetchone()
            (stashed,) = db.execute(f"SELECT COUNT(*) FROM {STASH}").fetchone()
            db.execute(f"DROP TABLE {STASH}")
    print(f"restored {restored} of {stashed} saved books")
    if restored != stashed:
        print(
            f"note: {stashed - restored} saved books no longer exist in the audiobook table"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["save", "restore"])
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        sys.exit(f"{args.database} does not exist")
    if args.action == "save":
        save(args.database)
    else:
        restore(args.database)


if __name__ == "__main__":
    main()
