from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
import logging

from app.db.session import get_db
from app.db.models import Business
from app.core.security import verify_token

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_business(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Business:
    """Get the current authenticated business from JWT token"""
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        business = db.query(Business).filter(Business.email == email).first()
    except (OperationalError, DisconnectionError) as e:
        error_msg = str(e).lower()
        if "timeout" in error_msg or "connection" in error_msg:
            logger.error(f"Database connection timeout in get_current_business: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection timeout. Please try again in a moment."
            )
        raise
    
    if business is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Business not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not business.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Business account is inactive",
        )
    
    return business
