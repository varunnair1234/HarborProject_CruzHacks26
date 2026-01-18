from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import logging

from app.db.session import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/live")
async def liveness_check():
    """
    Simple liveness check without database dependency
    Use this for basic liveness checks that don't require DB
    """
    return {
        "status": "ok",
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint
    
    Returns application status and version
    """
    # Test database connection with timeout handling
    db_status = "healthy"
    try:
        # Use a simple, fast query with timeout protection
        result = db.execute(text("SELECT 1"))
        result.fetchone()  # Actually fetch to ensure connection works
    except Exception as e:
        logger.warning(f"Health check DB test failed: {e}")
        db_status = f"unhealthy: {str(e)}"
    finally:
        # Ensure connection is closed even if there's an error
        try:
            db.close()
        except:
            pass
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "version": settings.app_version,
        "environment": settings.environment,
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status
    }