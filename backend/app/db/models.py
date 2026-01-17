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
    
    # Relationships
    daily_revenues = relationship("DailyRevenue", back_populates="analysis", cascade="all, delete-orphan")
    fixed_costs = relationship("FixedCost", back_populates="analysis", cascade="all, delete-orphan", uselist=False)
    rent_scenarios = relationship("RentScenario", back_populates="analysis", cascade="all, delete-orphan")


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
