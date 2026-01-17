from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import timedelta
import logging

from app.db.session import get_db
from app.db.models import Business
from app.schemas.auth import BusinessSignup, BusinessLogin, Token, BusinessInfo
from app.core.security import (
    get_password_hash,
    authenticate_business,
    create_access_token,
    get_business_by_email,
)
from app.core.dependencies import get_current_business
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=BusinessInfo, status_code=status.HTTP_201_CREATED)
async def signup(
    signup_data: BusinessSignup,
    db: Session = Depends(get_db)
):
    """Register a new business account"""
    try:
        # Check if email already exists
        existing_business = get_business_by_email(db, signup_data.email)
        if existing_business:
            logger.warning(f"Signup attempted with existing email: {signup_data.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Create new business
        logger.info(f"Creating new business account for: {signup_data.email}")
        business = Business(
            email=signup_data.email,
            business_name=signup_data.business_name,
            address=signup_data.address,
            business_type=signup_data.business_type,
            password_hash=get_password_hash(signup_data.password),
            is_active=True
        )
        
        db.add(business)
        logger.info(f"Business added to session, committing to database...")
        
        try:
            db.commit()
            logger.info(f"Database commit successful for business: {business.email}")
        except SQLAlchemyError as e:
            logger.error(f"Database commit failed: {str(e)}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create account: {str(e)}"
            )
        
        db.refresh(business)
        logger.info(f"Business account created successfully with ID: {business.id}")
        
        return BusinessInfo(
            id=business.id,
            email=business.email,
            business_name=business.business_name,
            address=business.address,
            business_type=business.business_type
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during signup: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while creating your account: {str(e)}"
        )


@router.post("/login", response_model=Token)
async def login(
    login_data: BusinessLogin,
    db: Session = Depends(get_db)
):
    """Login and get access token"""
    business = authenticate_business(db, login_data.email, login_data.password)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": business.email},
        expires_delta=access_token_expires
    )
    
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=BusinessInfo)
async def get_current_user_info(
    business: Business = Depends(get_current_business)
):
    """Get current authenticated business information"""
    return BusinessInfo(
        id=business.id,
        email=business.email,
        business_name=business.business_name,
        address=business.address,
        business_type=business.business_type
    )
