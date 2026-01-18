from __future__ import annotations

import logging
from typing import Generator
import logging

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
<<<<<<< HEAD
from sqlalchemy.pool import StaticPool, NullPool
=======
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import DisconnectionError, OperationalError
>>>>>>> 3b7e3a8460534a3844a410b909d660cc6bf34784

from app.core.config import settings
from app.db.models import Base

logger = logging.getLogger(__name__)

# Import all models to ensure they're registered with Base
from app.db.models import (  # noqa: F401
    Analysis,
    DailyRevenue,
    FixedCost,
    RentScenario,
    LLMOutput,
    ExternalCache,
    Business,
    BusinessProfile,
)

logger = logging.getLogger(__name__)

DATABASE_URL = (settings.database_url or "").strip()


def _is_production() -> bool:
    """Check if running in production environment."""
    return settings.environment.lower() in ("production", "prod")


def _normalize_database_url(url: str) -> str:
    # Force psycopg3 driver for SQLAlchemy
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

    normalized = _normalize_database_url(database_url)

    # Supabase pooler doesn't support prepared statements properly
    # Disable them completely to avoid "prepared statement does not exist" errors
    connect_args = {
        "sslmode": "require",
        "prepare_threshold": 0,  # Disable prepared statements (0 = never prepare)
    }

    # Use NullPool for production (no connection reuse = no prepared statement collisions)
    # This trades some performance for reliability on Supabase/Render
    return create_engine(
        normalized,
        connect_args=connect_args,
        poolclass=NullPool,
        pool_pre_ping=True,
<<<<<<< HEAD
        # SQLAlchemy: disable compiled statement cache
=======
        pool_recycle=300,  # Recycle connections every 5 minutes
        pool_size=3,  # Smaller pool to reduce connection issues
        max_overflow=5,  # Reduced overflow
        # Disable statement caching to avoid prepared statement issues
>>>>>>> 3b7e3a8460534a3844a410b909d660cc6bf34784
        execution_options={"compiled_cache": None},
        # Use NullPool if using Supabase pooler to avoid double pooling
        # But keep regular pool for now since it's working for some requests
    )


engine: Engine = _make_engine(DATABASE_URL)

# Debug: confirm the dialect is correct (should show postgresql+psycopg://)
logger.info("DB URL (sanitized): %s", engine.url.render_as_string(hide_password=True))


@event.listens_for(engine, "connect")
def set_prepare_threshold(dbapi_conn, connection_record):
    """Ensure prepared statements are disabled on each connection"""
    if hasattr(dbapi_conn, "prepare_threshold"):
        dbapi_conn.prepare_threshold = 0
        logger.debug("Set prepare_threshold=0 on new connection")


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Reset prepare_threshold when checking out a connection from pool"""
    if hasattr(dbapi_conn, "prepare_threshold"):
        dbapi_conn.prepare_threshold = 0
        logger.debug("Reset prepare_threshold=0 on connection checkout")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """
    Initialize database tables.

    In production, this is a no-op. Use Alembic migrations instead.
    In development (SQLite), creates tables automatically.
    """
    if _is_production():
        logger.info("Production environment detected - skipping auto table creation. Use Alembic migrations.")
        return

    # Only auto-create tables in development (SQLite)
    if DATABASE_URL.startswith("sqlite"):
        logger.info("Development environment - creating tables automatically")
        Base.metadata.create_all(bind=engine)
    else:
        logger.info("Non-SQLite database in non-production - skipping auto table creation")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
