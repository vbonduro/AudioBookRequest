"""The save/restore procedure that keeps the fork's retry columns across the upgrade."""

# The script is loaded by path, so its functions are untyped from here.
# pyright: basic

from __future__ import annotations

import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "fork_db_carryover.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fork_db_carryover", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


carryover = _load()


def _fork_db(path: Path) -> Path:
    """A database shaped like the fork's, at the fork's alembic revision."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR NOT NULL);
            INSERT INTO alembic_version VALUES ('6d620131023f');
            CREATE TABLE bookrequest (
                asin VARCHAR NOT NULL,
                user_username VARCHAR,
                updated_at DATETIME NOT NULL,
                search_attempts INTEGER NOT NULL DEFAULT 0,
                next_search_at DATETIME,
                downloaded_file VARCHAR
            );
            """
        )
        rows = [
            # downloaded, requested by two users with different values
            ("A1", "alice", "2026-01-01 00:00:00", 0, None, "Book A1 [EPUB]"),
            ("A1", "bob", "2026-02-01 00:00:00", 2, "2026-03-01 00:00:00", None),
            # waiting with retry state
            ("A3", "alice", "2026-01-01 00:00:00", 3, "2026-11-20 10:00:00", None),
            # nothing worth keeping
            ("A4", "bob", "2026-01-01 00:00:00", 0, None, None),
            # cache row without a user is ignored even if it has data
            ("C1", None, "2026-01-01 00:00:00", 4, "2026-11-20 10:00:00", "cached"),
        ]
        db.executemany("INSERT INTO bookrequest VALUES (?, ?, ?, ?, ?, ?)", rows)
        db.commit()
    return path


def _upgrade(path: Path) -> None:
    """What `alembic upgrade heads` leaves behind for these tables."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            """
            DROP TABLE bookrequest;
            CREATE TABLE audiobook (
                asin VARCHAR PRIMARY KEY,
                search_attempts INTEGER NOT NULL DEFAULT 0,
                next_search_at DATETIME,
                downloaded_file VARCHAR
            );
            INSERT INTO audiobook (asin) VALUES ('A1'), ('A3'), ('A4');
            UPDATE alembic_version SET version_num = 'a7c3e91b5d24';
            """
        )
        db.commit()


def _audiobooks(path: Path) -> dict[str, tuple[int, str | None, str | None]]:
    with closing(sqlite3.connect(path)) as db:
        return {
            asin: (attempts, next_at, file)
            for asin, attempts, next_at, file in db.execute(
                "SELECT asin, search_attempts, next_search_at, downloaded_file "
                "FROM audiobook"
            )
        }


def _revision(path: Path) -> str:
    with closing(sqlite3.connect(path)) as db:
        return str(db.execute("SELECT version_num FROM alembic_version").fetchone()[0])


def _tables(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as db:
        return {
            name
            for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_save_upgrade_restore(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    carryover.save(db)
    assert _revision(db) == "63489e50e337"
    assert "fork_carryover" in _tables(db)

    _upgrade(db)
    carryover.restore(db)

    assert _revision(db) == "a7c3e91b5d24"
    assert "fork_carryover" not in _tables(db)
    books = _audiobooks(db)
    # one request wins as a whole: the one with a downloaded file
    assert books["A1"] == (0, None, "Book A1 [EPUB]")
    assert books["A3"] == (3, "2026-11-20 10:00:00", None)
    assert books["A4"] == (0, None, None)


def test_save_backs_up_first(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    carryover.save(db)
    (backup,) = tmp_path.glob("db.sqlite.pre-save-*")
    assert _revision(backup) == "6d620131023f"
    assert "bookrequest" in _tables(backup)


def test_restore_backup_does_not_replace_the_pre_save_backup(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    carryover.save(db)
    _upgrade(db)
    carryover.restore(db)
    pre_save = list(tmp_path.glob("db.sqlite.pre-save-*"))
    pre_restore = list(tmp_path.glob("db.sqlite.pre-restore-*"))
    assert len(pre_save) == 1
    assert len(pre_restore) == 1
    assert "bookrequest" in _tables(pre_save[0])


def test_failed_save_leaves_nothing_behind(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "CREATE TRIGGER block BEFORE UPDATE ON alembic_version "
            "BEGIN SELECT RAISE(ABORT, 'no'); END"
        )
        conn.commit()
    with pytest.raises(sqlite3.DatabaseError):
        carryover.save(db)
    assert _revision(db) == "6d620131023f"
    assert "fork_carryover" not in _tables(db)

    # once the problem is gone, running save again just works
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DROP TRIGGER block")
        conn.commit()
    carryover.save(db)
    assert _revision(db) == "63489e50e337"


def test_save_refuses_the_wrong_revision(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    carryover.save(db)
    with pytest.raises(SystemExit):
        carryover.save(db)


def test_restore_refuses_before_the_upgrade(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    carryover.save(db)
    with pytest.raises(SystemExit):
        carryover.restore(db)


def test_restore_runs_once(tmp_path: Path) -> None:
    db = _fork_db(tmp_path / "db.sqlite")
    carryover.save(db)
    _upgrade(db)
    carryover.restore(db)
    with pytest.raises(SystemExit):
        carryover.restore(db)
