import httpx
import json
import hashlib
from typing import Dict, Optional
from datetime import datetime, timedelta
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
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call_deepseek_r1(metrics: Dict, fixed_costs: Dict) -> Dict:
        """
        Call DeepSeek R1 for CashFlow explanation
        
        Returns JSON with: bullets, actions, confidence_note
        """
        try:
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

            logger.info(f"Calling OpenRouter API with model: {settings.deepseek_r1_model}")
            
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
                    }
                )
                
                logger.info(f"OpenRouter response status: {response.status_code}")
                
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"OpenRouter API error: {response.status_code} - {error_text}")
                    raise Exception(f"OpenRouter returned {response.status_code}: {error_text}")
                
                response.raise_for_status()
                
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                # Parse JSON from response
                try:
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()
                    
                    parsed = json.loads(content)
                    logger.info("DeepSeek R1 response parsed successfully")
                    return parsed
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse DeepSeek response: {e}")
                    # Fallback response
                    return {
                        "bullets": ["Analysis complete", "Review metrics above", "Contact advisor for details"],
                        "actions": ["Monitor trends", "Review fixed costs", "Plan contingencies"],
                        "confidence_note": f"Based on {metrics['confidence']:.0%} confidence score"
                    }
        except Exception as e:
            logger.error(f"DeepSeek R1 call failed completely: {type(e).__name__}: {str(e)}")
            raise
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call_deepseek_v3(impact_metrics: Dict, context: Dict) -> Dict:
        """
        Call DeepSeek V3 for RentGuard explanation
        
        Returns JSON with: summary, concerns, recommendations
        """
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
                }
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
                    "recommendations": ["Review budget", "Negotiate terms", "Monitor closely"]
                }
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call_gemini(business_profile: Dict, ranking_context: Dict) -> Dict:
        """
        Call Gemini 2 Flash for Shopline featured business blurbs

        Returns JSON with: blurb, highlights, score
        """
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

        url = f"{LLMRouter.GEMINI_BASE_URL}/{settings.gemini_model}:generateContent?key={settings.google_api_key}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 500,
                    }
                }
            )
            response.raise_for_status()

            result = response.json()
            content = result["candidates"][0]["content"]["parts"][0]["text"]

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
                return {
                    "blurb": f"Featured local business in {business_profile.get('category')}",
                    "highlights": ["Local favorite", "Quality service", "Community focused"],
                    "score": 75.0
                }

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call_shopline_analyst(input_data: Dict) -> Dict:
        """
        Call Gemini for Shopline business analysis

        Returns comprehensive business analysis with diagnosis, outlook, and actions
        """
        input_json = json.dumps(input_data, ensure_ascii=False, default=str)

        prompt = f"""<identity>
You are SantaCruz Shopline's on-demand business analyst for small retail and food businesses in Santa Cruz, CA.
Your job is to convert structured business + local-signal inputs into clear, actionable, low-risk guidance.
</identity>

<context>
SantaCruz Shopline helps local operators understand what's driving sales (and what's not) using:
- business performance signals (revenue trend, volatility, fixed cost burden, runway)
- local demand signals (weather, events, seasonality, day-of-week, foot-traffic proxies)
You must stay grounded in the provided inputs only.
</context>

<hard_rules>
- Do NOT invent facts, numbers, events, weather, or performance results not included in the input.
- Do NOT claim certainty or guarantees; use probabilistic language.
- Do NOT recommend illegal, unsafe, discriminatory, or privacy-invasive actions.
- Do NOT reference private or personal data.
- Do NOT output markdown, code fences, or extra text outside the JSON response.
- If key inputs are missing or inconsistent, say so in "limitations" and lower confidence.
</hard_rules>

<task>
Given the structured input JSON, produce a Shopline-style analysis for a Santa Cruz business for the next 7 days.

You must:
1) Summarize business health from the metrics (trend/volatility/fixed costs/runway/risk state).
2) Explain what local demand signals imply for the next week (only if provided).
3) Produce 3–5 prioritized actions that are:
   - specific
   - realistic for a small business
   - tied directly to the signals
   - low-cost / low-risk where possible
4) Provide a short "watchlist" (what to monitor daily).
5) Provide a confidence score (0–1) based on signal alignment + data completeness.
</task>

<output_format>
Return ONLY valid JSON matching this exact schema:

{{
  "summary": string,
  "diagnosis": {{
    "state": "healthy" | "caution" | "risk",
    "why": [string, string, string]
  }},
  "next_7_days_outlook": {{
    "demand_level": "low" | "moderate" | "high",
    "drivers": [string, ...],
    "suppressors": [string, ...]
  }},
  "prioritized_actions": [
    {{
      "action": string,
      "reason": string,
      "expected_impact": "low" | "medium" | "high",
      "effort": "low" | "medium" | "high"
    }}
  ],
  "watchlist": [string, ...],
  "confidence": number,
  "limitations": string
}}

Constraints:
- diagnosis.why: exactly 3 bullets, each one sentence.
- next_7_days_outlook.drivers: 1–4 items, one sentence each.
- next_7_days_outlook.suppressors: 0–3 items, one sentence each.
- prioritized_actions: 3–5 items.
- watchlist: 3–6 items, one sentence each.
- confidence must be between 0.0 and 1.0.
</output_format>

<input>
BUSINESS + SIGNAL INPUT JSON:
{input_json}
</input>

<final_instruction>
Based only on the input JSON above, produce the JSON output now.
</final_instruction>"""

        url = f"{LLMRouter.GEMINI_BASE_URL}/{settings.gemini_model}:generateContent?key={settings.google_api_key}"

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 1500,
                    }
                }
            )
            response.raise_for_status()

            result = response.json()
            content = result["candidates"][0]["content"]["parts"][0]["text"]

            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)
                logger.info("Shopline analyst response parsed successfully")
                return parsed
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Shopline analyst response: {e}")
                return {
                    "summary": "Unable to generate complete analysis due to parsing error.",
                    "diagnosis": {
                        "state": "caution",
                        "why": [
                            "Analysis system encountered an error.",
                            "Please review raw metrics manually.",
                            "Contact support if issue persists."
                        ]
                    },
                    "next_7_days_outlook": {
                        "demand_level": "moderate",
                        "drivers": ["Unable to determine drivers."],
                        "suppressors": []
                    },
                    "prioritized_actions": [
                        {
                            "action": "Review business metrics manually",
                            "reason": "Automated analysis unavailable",
                            "expected_impact": "medium",
                            "effort": "medium"
                        }
                    ],
                    "watchlist": ["Daily revenue", "Customer traffic", "Weather conditions"],
                    "confidence": 0.3,
                    "limitations": "Analysis parsing failed. Results are placeholder only."
                }