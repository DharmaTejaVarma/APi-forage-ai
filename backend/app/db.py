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
connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}

# Create SQLAlchemy engine
engine = create_engine(
    settings.resolved_database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=settings.DEBUG and False,
)


# SQLite PRAGMA event listeners for foreign keys and WAL journal mode
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.resolved_database_url.startswith("sqlite"):
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


def seed_demo_users() -> None:
    """Seed demo and admin accounts if they do not already exist."""
    from app.models import User
    from app.security import get_password_hash

    db = SessionLocal()
    try:
        # Demo regular user
        demo_user = db.query(User).filter(User.email == "demo@apiforge.ai").first()
        if not demo_user:
            demo_user = User(
                email="demo@apiforge.ai",
                hashed_password=get_password_hash("DemoSecurePass123!"),
                role="user",
                is_active=True,
            )
            db.add(demo_user)

        # Admin user
        admin_user = db.query(User).filter(User.email == "admin@apiforge.ai").first()
        if not admin_user:
            admin_user = User(
                email="admin@apiforge.ai",
                hashed_password=get_password_hash("AdminMasterPass123!"),
                role="admin",
                is_active=True,
            )
            db.add(admin_user)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Notice: Demo user seeding skipped or existing: {e}")
    finally:
        db.close()


def init_db() -> None:
    """Create all tables registered with Base metadata and seed demo accounts."""
    import app.models  # Ensure all models are imported so metadata is populated
    Base.metadata.create_all(bind=engine)
    seed_demo_users()


def drop_db() -> None:
    """Drop all tables registered with Base metadata."""
    import app.models
    Base.metadata.drop_all(bind=engine)
