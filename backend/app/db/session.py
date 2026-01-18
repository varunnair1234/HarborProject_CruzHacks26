from __future__ import annotations

import logging
from typing import Generator
import logging
import time
from functools import wraps

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool, NullPool
from sqlalchemy.exc import OperationalError, DisconnectionError

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
    # Add connection and query timeouts to prevent hanging
    connect_args = {
        "sslmode": "require",
        "prepare_threshold": 0,  # Disable prepared statements (0 = never prepare)
        "connect_timeout": 15,  # 15 second connection timeout (increased from 10)
        "options": "-c statement_timeout=30000",  # 30 second query timeout (in milliseconds)
    }

    # Use NullPool for Supabase pooler to avoid double pooling issues
    # This prevents connection pool exhaustion and hanging connections
    return create_engine(
        normalized,
        connect_args=connect_args,
        poolclass=NullPool,
        pool_pre_ping=True,
        # SQLAlchemy: disable compiled statement cache
        execution_options={"compiled_cache": None},
    )


engine: Engine = _make_engine(DATABASE_URL)

# Debug: confirm the dialect is correct (should show postgresql+psycopg://)
#logger.info("DB URL (sanitized): %s", engine.url.render_as_string(hide_password=True))


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
    """
    Database session dependency with proper cleanup and retry logic.
    Ensures connections are always closed even on errors.
    Retries connection on timeout errors.
    """
    max_retries = 3
    retry_delay = 0.5  # Start with 0.5 seconds
    
    for attempt in range(max_retries):
        db = None
        try:
            db = SessionLocal()
            yield db
            db.commit()
            return
        except (OperationalError, DisconnectionError) as e:
            if db:
                try:
                    db.rollback()
                    db.close()
                except Exception:
                    pass
            
            # Check if it's a connection timeout error
            error_str = str(e).lower()
            is_timeout = "timeout" in error_str or "connection" in error_str
            
            if is_timeout and attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(
                    f"Database connection timeout (attempt {attempt + 1}/{max_retries}). "
                    f"Retrying in {wait_time:.2f}s..."
                )
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"Database connection error after {attempt + 1} attempts: {e}", exc_info=True)
                raise
        except Exception as e:
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.error(f"Database session error: {e}", exc_info=True)
            raise
        finally:
            # Always close the session, even if there was an error
            if db:
                try:
                    db.close()
                except Exception as close_error:
                    logger.error(f"Error closing database session: {close_error}")
