"""SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings

settings = get_settings()

connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # Required for SQLite when used across FastAPI request threads.
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call on every startup."""
    # Import models so metadata is populated before create_all.
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _sqlite_add_missing_columns()


def _sqlite_add_missing_columns() -> None:
    """Lightweight SQLite migrations for columns added after first create."""
    if not settings.database_url.startswith("sqlite"):
        return
    from sqlalchemy import text

    alters = [
        "ALTER TABLE paper_trades ADD COLUMN signal_snapshot_json TEXT",
    ]
    with engine.begin() as conn:
        for stmt in alters:
            try:
                conn.execute(text(stmt))
            except Exception:
                # Column already exists (or table missing — create_all handles tables).
                pass
