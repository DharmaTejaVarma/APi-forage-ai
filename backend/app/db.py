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
    """Seed demo and admin accounts with Mock Store API endpoints if they do not already exist."""
    import json
    from pathlib import Path
    from app.models import User, APIConnection, Endpoint
    from app.security import get_password_hash
    from app.services.openapi_parser import parse_openapi_spec

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
            db.commit()
            db.refresh(demo_user)

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

        # Seed Mock Store API connection and endpoints for demo user
        mock_conn = db.query(APIConnection).filter_by(user_id=demo_user.id, name="Mock Store API").first()
        if not mock_conn:
            mock_conn = APIConnection(
                user_id=demo_user.id,
                name="Mock Store API",
                description="Mock E-Commerce API for testing automated DAG workflows, discounts, customers, notifications, and orders.",
                base_url="http://127.0.0.1:8000/mock/api/v1",
                auth_type="none",
            )
            db.add(mock_conn)
            db.commit()
            db.refresh(mock_conn)

        # Normalize any previously seeded duplicated prefix paths
        existing_eps = db.query(Endpoint).filter_by(connection_id=mock_conn.id).all()
        existing_by_key = {}
        for ep in existing_eps:
            if ep.path.startswith("/mock/api/v1"):
                ep.path = ep.path[len("/mock/api/v1"):] or "/"
            existing_by_key[(ep.method.upper(), ep.path)] = ep

        backend_dir = Path(__file__).resolve().parent.parent
        ext_spec_path = backend_dir / "samples" / "extended_mock_openapi.json"
        std_spec_path = backend_dir / "samples" / "mock_openapi.json"
        spec_path = ext_spec_path if ext_spec_path.exists() else std_spec_path
        if spec_path.exists():
            with open(spec_path, "r", encoding="utf-8") as f:
                parsed = parse_openapi_spec(json.load(f))
            missing_eps = []
            for pe in parsed.endpoints:
                key = (pe.method.upper(), pe.path)
                existing_ep = existing_by_key.get(key)
                if existing_ep:
                    existing_ep.summary = pe.summary or existing_ep.summary
                    existing_ep.description = pe.description or existing_ep.description
                    existing_ep.parameters = pe.parameters or existing_ep.parameters
                    existing_ep.request_body_schema = pe.request_body_schema or existing_ep.request_body_schema
                    existing_ep.response_schema = pe.response_schema or existing_ep.response_schema
                    existing_ep.security = pe.security if pe.security is not None else existing_ep.security
                else:
                    missing_eps.append(
                        Endpoint(
                            connection_id=mock_conn.id,
                            path=pe.path,
                            method=pe.method,
                            summary=pe.summary,
                            description=pe.description,
                            operation_id=pe.operation_id,
                            parameters=pe.parameters,
                            request_body_schema=pe.request_body_schema,
                            response_schema=pe.response_schema,
                            security=pe.security,
                        )
                    )
            if missing_eps:
                db.add_all(missing_eps)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Notice: Demo user seeding skipped or existing: {e}")
    finally:
        db.close()


def _migrate_sqlite_columns() -> None:
    """Safely add newly introduced columns on existing SQLite databases."""
    if not settings.resolved_database_url.startswith("sqlite"):
        return

    migrations = {
        "endpoints": [("security", "JSON")],
        "workflow_executions": [
            ("approved_steps", "JSON"),
            ("pending_approval_details", "JSON"),
            ("final_output", "JSON"),
        ],
    }
    with engine.connect() as conn:
        for table, cols in migrations.items():
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            }
            for col_name, col_type in cols:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
        conn.commit()


def init_db() -> None:
    """Create all tables registered with Base metadata and seed demo accounts."""
    import app.models  # Ensure all models are imported so metadata is populated
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
    seed_demo_users()


def drop_db() -> None:
    """Drop all tables registered with Base metadata."""
    import app.models
    Base.metadata.drop_all(bind=engine)
