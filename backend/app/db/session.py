from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
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

DATABASE_URL = settings.database_url.strip()

# ---------- Engine ----------
def _make_engine(database_url: str):
    # SQLite (local dev)
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    # Postgres / Supabase
    connect_args = {}
    if database_url.startswith("postgresql"):
        # Supabase requires SSL
        connect_args = {"sslmode": "require"}

    return create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


engine = _make_engine(DATABASE_URL)

# ---------- Session factory ----------
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
