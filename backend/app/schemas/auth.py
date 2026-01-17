from pydantic import BaseModel, EmailStr, Field
from typing import Literal


class BusinessSignup(BaseModel):
    """Business signup request"""
    email: EmailStr
    business_name: str = Field(..., min_length=1, max_length=255)
    address: str = Field(..., min_length=1, max_length=500)
    business_type: Literal["cafe", "boutique", "bakery/dessert", "bookstore/stationary", "art"]
    password: str = Field(..., min_length=8)


class BusinessLogin(BaseModel):
    """Business login request"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"


class BusinessInfo(BaseModel):
    """Business information response"""
    id: int
    email: str
    business_name: str
    address: str
    business_type: str
    
    class Config:
        from_attributes = True
