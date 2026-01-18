from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional


class BusinessSignup(BaseModel):
    """Business signup request"""
    email: EmailStr
    business_name: str = Field(..., min_length=1, max_length=255)
    address: str = Field(..., min_length=1, max_length=500)
    business_type: Literal[
        "food & drink",
        "arts, culture & creative",
        "nonprofit, education & community",
        "services & professional",
        "retail – apparel & accessories",
        "personal care & wellness",
        "business",
        "entertainment & recreation"
    ]
    password: str = Field(..., min_length=8, max_length=72, description="Password must be 8-72 characters")


class BusinessLogin(BaseModel):
    """Business login request"""
    email: EmailStr
    password: str = Field(..., max_length=72, description="Password must be 72 characters or less")


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


class BusinessProfileInput(BaseModel):
    """Business profile financial information"""
    monthly_rent: float = Field(..., gt=0, description="Monthly rent")
    monthly_payroll: float = Field(..., ge=0, description="Monthly payroll")
    other_fixed_costs: float = Field(default=0.0, ge=0, description="Other monthly fixed costs")
    cash_on_hand: Optional[float] = Field(None, ge=0, description="Current cash reserves")
    variable_cost_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Variable costs as fraction of revenue")


class BusinessProfileResponse(BaseModel):
    """Business profile response"""
    id: int
    business_id: int
    monthly_rent: float
    monthly_payroll: float
    other_fixed_costs: float
    cash_on_hand: Optional[float]
    variable_cost_rate: float
    created_at: str
    
    class Config:
        from_attributes = True


class BusinessFullInfo(BaseModel):
    """Complete business info with profile"""
    id: int
    email: str
    business_name: str
    address: str
    business_type: str
    profile: Optional[BusinessProfileResponse] = None
    
    class Config:
        from_attributes = True
