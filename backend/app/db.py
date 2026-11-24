"""
APIForge AI Database Module
Configures SQLite engine with WAL mode, foreign key enforcement, and table initialization.
"""
from typing import Generator
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import get_settings

settings = get_settings()

# SQLite connect args
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

# Create SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=settings.DEBUG and False,
)


# SQLite PRAGMA event listeners for foreign keys and WAL journal mode
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Base
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session and closes it after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connectivity() -> bool:
    """
    Verify database connectivity using 'SELECT 1;' query.
    Returns True if database is reachable and query evaluates to 1.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            return result == 1
    except Exception:
        return False


def init_db() -> None:
    """Create all tables registered with Base metadata."""
    import app.models  # Ensure all models are imported so metadata is populated
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all tables registered with Base metadata."""
    import app.models
    Base.metadata.drop_all(bind=engine)
