from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, Dict
import json
import logging

from app.db.models import LLMOutput, ExternalCache
from app.core.config import settings

logger = logging.getLogger(__name__)


class CacheService:
    """Service for caching LLM outputs and external API calls"""
    
    @staticmethod
    def get_llm_output(db: Session, cache_key: str) -> Optional[Dict]:
        """
        Retrieve cached LLM output if not expired
        
        Args:
            db: Database session
            cache_key: Cache key (hash of input + model)
            
        Returns:
            Cached output dict or None if not found/expired
        """
        cached = db.query(LLMOutput).filter(
            LLMOutput.key == cache_key,
            LLMOutput.ttl_expires_at > datetime.utcnow()
        ).first()
        
        if cached:
            logger.info(f"LLM cache hit for key: {cache_key[:16]}...")
            try:
                return json.loads(cached.output_json)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse cached LLM output")
                return None
        
        logger.info(f"LLM cache miss for key: {cache_key[:16]}...")
        return None
    
    @staticmethod
    def set_llm_output(
        db: Session,
        cache_key: str,
        model: str,
        output: Dict,
        ttl_hours: Optional[int] = None
    ) -> None:
        """
        Cache LLM output with TTL
        
        Args:
            db: Database session
            cache_key: Cache key
            model: Model name
            output: Output to cache
            ttl_hours: Time to live in hours (default from config)
        """
        if ttl_hours is None:
            ttl_hours = settings.llm_cache_ttl_hours
        
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
        
        # Check if exists
        existing = db.query(LLMOutput).filter(LLMOutput.key == cache_key).first()
        
        if existing:
            # Update existing
            existing.output_json = json.dumps(output)
            existing.ttl_expires_at = expires_at
            existing.created_at = datetime.utcnow()
            logger.info(f"Updated LLM cache for key: {cache_key[:16]}...")
        else:
            # Create new
            cached = LLMOutput(
                key=cache_key,
                model=model,
                output_json=json.dumps(output),
                ttl_expires_at=expires_at
            )
            db.add(cached)
            logger.info(f"Created LLM cache for key: {cache_key[:16]}...")
        
        db.commit()
    
    @staticmethod
    def get_external_cache(
        db: Session,
        source: str,
        query_hash: str
    ) -> Optional[Dict]:
        """
        Retrieve cached external API response if not expired
        
        Args:
            db: Database session
            source: API source (noaa, events, surf, osm)
            query_hash: Hash of query parameters
            
        Returns:
            Cached payload dict or None
        """
        cached = db.query(ExternalCache).filter(
            ExternalCache.source == source,
            ExternalCache.query_hash == query_hash,
            ExternalCache.expires_at > datetime.utcnow()
        ).first()
        
        if cached:
            logger.info(f"External cache hit for {source}:{query_hash[:16]}...")
            try:
                return json.loads(cached.payload)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse cached external data")
                return None
        
        logger.info(f"External cache miss for {source}:{query_hash[:16]}...")
        return None
    
    @staticmethod
    def set_external_cache(
        db: Session,
        source: str,
        query_hash: str,
        payload: Dict,
        ttl_hours: Optional[int] = None
    ) -> None:
        """
        Cache external API response with TTL
        
        Args:
            db: Database session
            source: API source
            query_hash: Hash of query
            payload: Data to cache
            ttl_hours: Time to live (default from config)
        """
        if ttl_hours is None:
            ttl_hours = settings.external_cache_ttl_hours
        
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
        
        # Check if exists
        existing = db.query(ExternalCache).filter(
            ExternalCache.source == source,
            ExternalCache.query_hash == query_hash
        ).first()
        
        if existing:
            existing.payload = json.dumps(payload)
            existing.expires_at = expires_at
            existing.created_at = datetime.utcnow()
            logger.info(f"Updated external cache for {source}:{query_hash[:16]}...")
        else:
            cached = ExternalCache(
                source=source,
                query_hash=query_hash,
                payload=json.dumps(payload),
                expires_at=expires_at
            )
            db.add(cached)
            logger.info(f"Created external cache for {source}:{query_hash[:16]}...")
        
        db.commit()
    
    @staticmethod
    def cleanup_expired(db: Session) -> int:
        """
        Remove expired cache entries
        
        Returns:
            Number of entries deleted
        """
        now = datetime.utcnow()
        
        llm_deleted = db.query(LLMOutput).filter(
            LLMOutput.ttl_expires_at <= now
        ).delete()
        
        external_deleted = db.query(ExternalCache).filter(
            ExternalCache.expires_at <= now
        ).delete()
        
        db.commit()
        
        total = llm_deleted + external_deleted
        if total > 0:
            logger.info(f"Cleaned up {total} expired cache entries")
        
        return total
