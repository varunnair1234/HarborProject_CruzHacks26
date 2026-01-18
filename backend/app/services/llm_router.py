import httpx
import json
import hashlib
from typing import Dict
from tenacity import retry, stop_after_attempt, wait_exponential
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMRouter:
    """Route LLM calls to appropriate models with retry logic"""

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
    GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    @staticmethod
    def generate_cache_key(input_data: Dict, model: str) -> str:
        """Generate deterministic cache key from input + model"""
        input_str = json.dumps(input_data, sort_keys=True)
        combined = f"{model}:{input_str}"
        return hashlib.sha256(combined.encode()).hexdigest()

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_deepseek_r1(metrics: Dict, fixed_costs: Dict) -> Dict:
        """CashFlow explanation (JSON: bullets, actions, confidence_note)"""

        if not settings.openrouter_api_key or not settings.openrouter_api_key.strip():
            logger.warning("OPENROUTER_API_KEY not configured; returning fallback for DeepSeek R1")
            return {
                "bullets": ["Analysis complete", "Review metrics above", "Add API key for richer insights"],
                "actions": ["Monitor trends", "Review fixed costs", "Plan contingencies"],
                "confidence_note": f"Based on {metrics.get('confidence', 0):.0%} confidence score",
            }

        prompt = f"""You are a financial advisor analyzing cash flow for a small business.

Given these metrics:
- Average daily revenue: ${metrics['avg_daily_revenue']:.2f}
- 7-day trend: {metrics['trend_7d']:.1f}%
- 14-day trend: {metrics['trend_14d']:.1f}%
- 30-day trend: {metrics['trend_30d']:.1f}%
- Volatility (coefficient of variation): {metrics['volatility']:.2f}
- Fixed cost burden: {metrics['fixed_cost_burden']:.1%}
- Risk state: {metrics['risk_state']}
- Confidence: {metrics['confidence']:.1%}
{f"- Runway: {metrics['runway_days']:.0f} days" if metrics.get('runway_days') else ""}

Fixed costs:
- Monthly rent: ${fixed_costs.get('rent', 0):.2f}
- Monthly payroll: ${fixed_costs.get('payroll', 0):.2f}
- Other fixed costs: ${fixed_costs.get('other', 0):.2f}

Provide analysis as JSON with exactly these fields:
{{
  "bullets": ["insight 1", "insight 2", "insight 3"],
  "actions": ["action 1", "action 2", "action 3"],
  "confidence_note": "explanation of confidence score"
}}

Keep bullets concise (1 sentence each). Actions should be specific and actionable."""

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                LLMRouter.OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.deepseek_r1_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)
                logger.info("DeepSeek R1 response parsed successfully")
                return parsed
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse DeepSeek R1 response: {e}")
                return {
                    "bullets": ["Analysis complete", "Review metrics above", "Contact advisor for details"],
                    "actions": ["Monitor trends", "Review fixed costs", "Plan contingencies"],
                    "confidence_note": f"Based on {metrics['confidence']:.0%} confidence score",
                }

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_deepseek_v3(impact_metrics: Dict, context: Dict) -> Dict:
        """RentGuard explanation (JSON: summary, concerns, recommendations)"""

        if not settings.openrouter_api_key or not settings.openrouter_api_key.strip():
            logger.warning("OPENROUTER_API_KEY not configured; returning fallback for DeepSeek V3")
            return {
                "summary": f"Rent increase of {impact_metrics.get('delta_pct', 0):.1f}% analyzed.",
                "concerns": ["Impact on cash flow", "Risk state change"],
                "recommendations": ["Review budget", "Negotiate terms", "Monitor closely"],
            }

        prompt = f"""You are a financial advisor analyzing the impact of a rent increase.

Current situation:
- Current rent: ${impact_metrics['current_rent']:.2f}/month
- New rent: ${impact_metrics['new_rent']:.2f}/month
- Increase: ${impact_metrics['delta_monthly']:.2f}/month ({impact_metrics['delta_pct']:.1f}%)
- Current risk state: {impact_metrics['current_risk_state']}
- New risk state: {impact_metrics['new_risk_state']}
- New fixed cost burden: {impact_metrics['new_fixed_cost_burden']:.1%}
{f"- Runway impact: {impact_metrics['runway_impact_days']:.0f} days" if impact_metrics.get('runway_impact_days') else ""}

Provide analysis as JSON with exactly these fields:
{{
  "summary": "1-2 sentence overview",
  "concerns": ["concern 1", "concern 2"],
  "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"]
}}

Be honest but constructive. Focus on actionable advice."""

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                LLMRouter.OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.deepseek_v3_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)
                logger.info("DeepSeek V3 response parsed successfully")
                return parsed
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse DeepSeek V3 response: {e}")
                return {
                    "summary": f"Rent increase of {impact_metrics['delta_pct']:.1f}% analyzed",
                    "concerns": ["Impact on cash flow", "Risk state change"],
                    "recommendations": ["Review budget", "Negotiate terms", "Monitor closely"],
                }

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_gemini(business_profile: Dict, ranking_context: Dict) -> Dict:
        """Shopline featured business blurbs (JSON: blurb, highlights, score)

        Uses OpenRouter API to access Gemini model for consistent API interface.
        """
        fallback_response = {
            "blurb": f"Featured local business in {business_profile.get('category', 'general')}.",
            "highlights": ["Local favorite", "Quality service", "Community focused"],
            "score": 75.0,
        }

        # Check for OpenRouter API key (preferred method via OpenRouter)
        if not settings.openrouter_api_key or not settings.openrouter_api_key.strip():
            logger.warning("OPENROUTER_API_KEY not configured; using fallback for Gemini calls")
            return fallback_response

        prompt = f"""Generate a compelling featured business description.

Business: {business_profile.get('name')}
Category: {business_profile.get('category')}
Location: {business_profile.get('location')}
Description: {business_profile.get('description', 'N/A')}

Create JSON with:
{{
  "blurb": "2-3 sentence marketing description",
  "highlights": ["feature 1", "feature 2", "feature 3"],
  "score": 85.5
}}

Make it appealing but honest. Score should reflect local appeal, uniqueness, and quality."""

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Use OpenRouter API with Gemini model for consistent interface
            response = await client.post(
                LLMRouter.OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.gemini_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 500,
                }
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Log the exact status + body to diagnose auth/quota/model issues
                status = e.response.status_code if e.response is not None else "unknown"
                body = e.response.text if e.response is not None else ""
                logger.error(f"Gemini (via OpenRouter) HTTP error status={status} body={body[:200]}")
                raise

            result = response.json()

            # Validate response structure before accessing
            if "choices" not in result or not result["choices"]:
                logger.error(f"Invalid Gemini response structure: missing 'choices' key")
                return fallback_response

            first_choice = result["choices"][0]
            if "message" not in first_choice or "content" not in first_choice.get("message", {}):
                logger.error(f"Invalid Gemini response structure: missing 'message.content'")
                return fallback_response

            content = first_choice["message"]["content"]
            if not content:
                logger.error("Empty content in Gemini response")
                return fallback_response

            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)
                logger.info("Gemini response parsed successfully")
                return parsed
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Gemini response: {e}")
                return fallback_response
