from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.models import Base

# Import all models to ensure they're registered with Base
from app.db.models import (  # noqa: F401
    Analysis,
    DailyRevenue,
    FixedCost,
    RentScenario,
    LLMOutput,
    ExternalCache,
    Business,
)

DATABASE_URL = (settings.database_url or "").strip()


def _normalize_database_url(url: str) -> str:
    """
    Ensure Postgres URLs use psycopg v3 driver.
    Supabase often provides: postgresql://...
    We want: postgresql+psycopg://...
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def _make_engine(database_url: str) -> Engine:
    # SQLite (local dev)
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    # Postgres / Supabase
    normalized = _normalize_database_url(database_url)

    # psycopg3 fix:
    # - prepare_threshold=0 disables server-side prepared statements (prevents ProtocolViolation)
    # - sslmode=require for Supabase
    # - pool_pre_ping + pool_recycle reduces stale-connection issues on hosted Postgres
    connect_args = {"sslmode": "require", "prepare_threshold": 0}

    return create_engine(
        normalized,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,         # keep modest on Render
        max_overflow=10,
    )


engine: Engine = _make_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for getting a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
