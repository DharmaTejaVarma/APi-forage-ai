"""
Database Connectivity and SQLite Configuration Tests
Verifies that the SQLite database engine connects, executes 'SELECT 1;',
and enforces WAL mode and foreign key constraints.
"""
import pytest
from sqlalchemy import text
from app.db import engine, SessionLocal, get_db, check_db_connectivity


def test_db_connectivity_helper():
    """Verify check_db_connectivity returns True for SELECT 1."""
    assert check_db_connectivity() is True


def test_sqlite_pragmas():
    """Verify that foreign keys are ON and journal_mode is WAL."""
    with engine.connect() as conn:
        # Check foreign keys
        fk_result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk_result == 1, f"Expected foreign_keys=1, got {fk_result}"

        # Check WAL journal mode
        wal_result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert str(wal_result).lower() == "wal", f"Expected journal_mode=wal, got {wal_result}"


def test_session_generator():
    """Verify get_db session generator yields a valid working session."""
    db_gen = get_db()
    session = next(db_gen)
    try:
        val = session.execute(text("SELECT 42")).scalar()
        assert val == 42
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass
