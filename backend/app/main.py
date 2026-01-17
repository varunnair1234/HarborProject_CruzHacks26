from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import init_db
from app.routers import health, cashflow, rentguard, touristpulse, shopline

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup
    logger.info("Starting Harbor API...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Version: {settings.app_version}")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Harbor API...")


# Create FastAPI application
app = FastAPI(
    title="Harbor API",
    description="Backend API for Harbor - Small business financial tools",
    version=settings.app_version,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://varunnair1234.github.io",
        # If you ever use a custom domain, add it here too
        # "https://yourdomain.com",
    ],
    allow_origin_regex=r"^https://.*\.github\.io$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(health.router)
app.include_router(cashflow.router)
app.include_router(rentguard.router)
app.include_router(touristpulse.router)
app.include_router(shopline.router)


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Harbor API",
        "version": settings.app_version,
        "description": "Small business financial tools backend",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "cashflow_analyze": "POST /cashflow/analyze",
            "rentguard_impact": "POST /rentguard/impact",
            "touristpulse_outlook": "GET /touristpulse/outlook",
            "shopline_search": "POST /shopline/search",
            "shopline_featured": "POST /shopline/featured"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
