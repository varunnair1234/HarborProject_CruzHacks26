from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Analysis(Base):
    """Main analysis record for CashFlow Calm"""
    __tablename__ = "analyses"
    
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    business_name = Column(String(255), nullable=True)
    data_days = Column(Integer, nullable=False)
    risk_state = Column(String(50), nullable=False)  # healthy, caution, critical
    confidence = Column(Float, nullable=False)  # 0.0 to 1.0
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)
    
    # Relationships
    daily_revenues = relationship("DailyRevenue", back_populates="analysis", cascade="all, delete-orphan")
    fixed_costs = relationship("FixedCost", back_populates="analysis", cascade="all, delete-orphan", uselist=False)
    rent_scenarios = relationship("RentScenario", back_populates="analysis", cascade="all, delete-orphan")
    business = relationship("Business", back_populates="analyses")


class DailyRevenue(Base):
    """Daily revenue time series data"""
    __tablename__ = "daily_revenue"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    date = Column(Date, nullable=False)
    revenue = Column(Float, nullable=False)
    
    # Relationship
    analysis = relationship("Analysis", back_populates="daily_revenues")


class FixedCost(Base):
    """Fixed costs for a business"""
    __tablename__ = "fixed_costs"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, unique=True)
    rent = Column(Float, nullable=False)
    payroll = Column(Float, nullable=False)
    other = Column(Float, nullable=False)
    cash_on_hand = Column(Float, nullable=True)
    
    # Relationship
    analysis = relationship("Analysis", back_populates="fixed_costs")


class RentScenario(Base):
    """Rent increase scenarios for RentGuard"""
    __tablename__ = "rent_scenarios"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    increase_pct = Column(Float, nullable=True)  # percentage increase
    new_rent = Column(Float, nullable=True)  # or absolute new rent
    effective_date = Column(Date, nullable=True)
    delta_monthly = Column(Float, nullable=False)  # monthly impact
    new_risk_state = Column(String(50), nullable=False)
    
    # Relationship
    analysis = relationship("Analysis", back_populates="rent_scenarios")


class LLMOutput(Base):
    """Cache for LLM responses"""
    __tablename__ = "llm_outputs"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, nullable=False, index=True)  # hash of input + model
    model = Column(String(100), nullable=False)
    output_json = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ttl_expires_at = Column(DateTime, nullable=False)


class ExternalCache(Base):
    """Cache for external API calls (weather, events, surf, OSM)"""
    __tablename__ = "external_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)  # noaa, events, surf, osm
    query_hash = Column(String(64), nullable=False, index=True)
    payload = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class Business(Base):
    """Business user accounts"""
    __tablename__ = "businesses"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    business_name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=False)
    business_type = Column(String(50), nullable=False)  # cafe, boutique, bakery/dessert, bookstore/stationary, art
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationship to analyses
    analyses = relationship("Analysis", back_populates="business")

class BusinessProfile(Base):
    """Extended business profile with financial info"""
    __tablename__ = "business_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, unique=True)
    monthly_rent = Column(Float, nullable=False)
    monthly_payroll = Column(Float, nullable=False)
    other_fixed_costs = Column(Float, default=0.0, nullable=False)
    cash_on_hand = Column(Float, nullable=True)
    variable_cost_rate = Column(Float, default=0.0)  # 0.0 to 1.0
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    business = relationship("Business", backref="profile", uselist=False)


class BusinessProfileInput(BaseModel):
    """Business profile financial information"""
    monthly_rent: float = Field(..., gt=0, description="Monthly rent")
    monthly_payroll: float = Field(..., ge=0, description="Monthly payroll")
    other_fixed_costs: float = Field(default=0.0, ge=0, description="Other monthly fixed costs")
    cash_on_hand: float = Field(None, ge=0, description="Current cash reserves")
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