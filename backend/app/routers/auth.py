from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta

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

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=BusinessInfo, status_code=status.HTTP_201_CREATED)
async def signup(
    signup_data: BusinessSignup,
    db: Session = Depends(get_db)
):
    """Register a new business account"""
    # Check if email already exists
    existing_business = get_business_by_email(db, signup_data.email)
    if existing_business:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new business
    business = Business(
        email=signup_data.email,
        business_name=signup_data.business_name,
        address=signup_data.address,
        business_type=signup_data.business_type,
        password_hash=get_password_hash(signup_data.password),
        is_active=True
    )
    
    db.add(business)
    db.commit()
    db.refresh(business)
    
    return BusinessInfo(
        id=business.id,
        email=business.email,
        business_name=business.business_name,
        address=business.address,
        business_type=business.business_type
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
