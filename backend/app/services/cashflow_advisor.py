

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .cashflow_engine import CashFlowEngine

logger = logging.getLogger(__name__)


@dataclass
class AdvisorConfig:
    """Tunable thresholds and behavior for the advisor layer."""

    # Output sizing
    max_drivers: int = 3
    max_actions: int = 5

    # Data sufficiency note
    min_days_for_confident_advice: int = 14

    # Whether to include the engine's raw metric block in response
    include_metrics_block: bool = True


class CashFlowAdvisor:
    """CashFlow Calm advisor layer.

    This class:
      1) Computes deterministic metrics via CashFlowEngine
      2) Converts metrics into a product-friendly state: stable / watch_closely / action_needed
      3) Generates drivers and recommended actions (rules-based)
      4) Optionally uses DeepSeek to narrate (best-effort) without changing any numbers
    """

    def __init__(self, config: Optional[AdvisorConfig] = None):
        self.config = config or AdvisorConfig()

    def advise(
        self,
        daily_revenues: List[Dict[str, Any]],
        fixed_costs: Dict[str, float],
        variable_cost_rate: float = 0.0,
        use_llm: bool = False,
        llm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate cashflow advice.

        Args:
            daily_revenues: list of {"date": ..., "revenue": ...}
            fixed_costs: {"rent":..., "payroll":..., "other":..., "cash_on_hand":...}
            variable_cost_rate: fraction 0..1 (COGS/fees)
            use_llm: attach DeepSeek narrative (JSON) if True
            llm_model: optional model override

        Returns:
            Dict containing state, runway, drivers, actions, and optional narrative.
        """
        metrics = CashFlowEngine.compute_metrics(
            daily_revenues=daily_revenues,
            fixed_costs=fixed_costs,
            variable_cost_rate=variable_cost_rate,
        )

        state = self._map_state(metrics.get("risk_state"))
        runway_days = metrics.get("runway_days")

        drivers = self._build_drivers(metrics, fixed_costs, variable_cost_rate)
        drivers = drivers[: self.config.max_drivers]

        actions = self._build_actions(metrics, fixed_costs, variable_cost_rate)
        actions = actions[: self.config.max_actions]

        response: Dict[str, Any] = {
            "state": state,
            "runway_days": runway_days,
            "risk_horizon": metrics.get("risk_horizon"),
            "confidence": metrics.get("confidence"),
            "drivers": drivers,
            "actions": actions,
            "assumptions_used": {
                "cash_on_hand": fixed_costs.get("cash_on_hand"),
                "monthly_fixed_costs": {
                    "rent": float(fixed_costs.get("rent", 0.0)),
                    "payroll": float(fixed_costs.get("payroll", 0.0)),
                    "other": float(fixed_costs.get("other", 0.0)),
                },
                "variable_cost_rate": float(variable_cost_rate),
            },
        }

        # Optional metrics block (useful for debugging / later UI)
        if self.config.include_metrics_block:
            response["metrics"] = {
                "avg_daily_revenue": metrics.get("avg_daily_revenue"),
                "trend_7d": metrics.get("trend_7d"),
                "trend_14d": metrics.get("trend_14d"),
                "trend_30d": metrics.get("trend_30d"),
                "volatility": metrics.get("volatility"),
                "fixed_cost_burden": metrics.get("fixed_cost_burden"),
                "engine_risk_state": metrics.get("risk_state"),
            }

        # Data sufficiency note (does not block output)
        data_days = len(daily_revenues)
        if data_days < self.config.min_days_for_confident_advice:
            response["note"] = (
                f"Advice is based on {data_days} days of revenue data. "
                "For more reliable guidance, upload ~30+ days."
            )

        # Optional LLM narrative (best-effort)
        if use_llm:
            narrative = self._narrate_with_llm(response, model=llm_model)
            if narrative is not None:
                response["narrative"] = narrative

        return response

    # -----------------------------
    # Mapping + rules
    # -----------------------------

    @staticmethod
    def _map_state(engine_risk_state: Optional[str]) -> str:
        """Map engine risk_state to product language."""
        s = (engine_risk_state or "").strip().lower()
        if s == "critical":
            return "action_needed"
        if s == "caution":
            return "watch_closely"
        return "stable"

    def _build_drivers(
        self,
        metrics: Dict[str, Any],
        fixed_costs: Dict[str, float],
        variable_cost_rate: float,
    ) -> List[str]:
        """Generate short, factual 'why' statements."""
        avg_daily = float(metrics.get("avg_daily_revenue") or 0.0)
        vol = float(metrics.get("volatility") or 0.0)
        trend_30 = float(metrics.get("trend_30d") or 0.0)
        burden = metrics.get("fixed_cost_burden")
        runway = metrics.get("runway_days")

        drivers: List[str] = []

        # Runway
        if runway is None:
            drivers.append("On average, your cash flow is not negative (no near-term runway risk detected).")
        else:
            drivers.append(f"At the current average burn, runway is about {runway:.0f} days.")

        # Fixed cost burden
        if burden is None or burden == float("inf"):
            drivers.append("Fixed-cost burden couldn't be computed reliably from the current inputs.")
        else:
            drivers.append(f"Fixed costs are about {float(burden) * 100:.0f}% of average monthly sales.")

        # Variable cost rate
        if variable_cost_rate > 0:
            drivers.append(
                f"Variable costs (COGS/fees) reduce usable cash from sales by ~{variable_cost_rate * 100:.0f}% on average."
            )

        # Trend
        if trend_30 <= -10:
            drivers.append(f"Sales trend is down ~{abs(trend_30):.0f}% over the last 30 days.")
        elif trend_30 >= 10:
            drivers.append(f"Sales trend is up ~{trend_30:.0f}% over the last 30 days.")
        else:
            drivers.append("Sales trend over the last 30 days is relatively flat.")

        # Volatility
        if vol >= CashFlowEngine.VOLATILITY_CRITICAL:
            drivers.append("Day-to-day sales vary a lot, which increases cash risk in a bad week.")
        elif vol >= CashFlowEngine.VOLATILITY_CAUTION:
            drivers.append("Day-to-day sales are somewhat volatile; planning should use a safety buffer.")
        else:
            drivers.append("Sales volatility appears manageable based on the recent data.")

        # Prioritize the most important drivers
        prioritized: List[str] = []
        for phrase in ("runway", "fixed", "Variable costs", "trend", "volatile"):
            for d in drivers:
                if phrase.lower() in d.lower() and d not in prioritized:
                    prioritized.append(d)
        for d in drivers:
            if d not in prioritized:
                prioritized.append(d)

        return prioritized

    def _build_actions(
        self,
        metrics: Dict[str, Any],
        fixed_costs: Dict[str, float],
        variable_cost_rate: float,
    ) -> List[Dict[str, str]]:
        """Generate practical, safe actions."""
        actions: List[Dict[str, str]] = []

        runway = metrics.get("runway_days")
        burden = metrics.get("fixed_cost_burden")
        trend_30 = float(metrics.get("trend_30d") or 0.0)
        vol = float(metrics.get("volatility") or 0.0)

        # Always: simple checkpoint
        actions.append(
            {
                "title": "Set a weekly cash checkpoint",
                "detail": "Once per week, review: cash balance, last-7-day sales, and upcoming fixed payments. "
                "This catches problems early without needing dashboards.",
            }
        )

        # Runway actions
        if runway is not None and runway < CashFlowEngine.RUNWAY_CAUTION_DAYS:
            actions.append(
                {
                    "title": "Reduce fixed commitments by 5–10%",
                    "detail": "Look for fast changes: pause non-essential subscriptions, renegotiate vendor minimums, "
                    "tighten scheduling to demand, and delay discretionary purchases for 30 days.",
                }
            )
            actions.append(
                {
                    "title": "Pull some cash forward",
                    "detail": "Consider gift cards, pre-paid bundles, or deposits (if appropriate). Keep terms clear and deliverable.",
                }
            )

        # Burden actions
        if burden is not None and burden != float("inf") and float(burden) > CashFlowEngine.BURDEN_CAUTION:
            actions.append(
                {
                    "title": "Rebalance fixed vs. flexible costs",
                    "detail": "If fixed costs are consuming most sales, prioritize changes that convert fixed to flexible: "
                    "align labor hours with demand, adjust operating hours, or shift some spend to performance-based channels.",
                }
            )

        # Trend actions
        if trend_30 <= -10:
            actions.append(
                {
                    "title": "Run a 2-week sales lift experiment",
                    "detail": "Pick one lever for 2 weeks: a slow-weekday promo, a bundle of best-sellers, or a partnership with a nearby business. "
                    "Compare results to your normal weekday baseline.",
                }
            )

        # Volatility actions
        if vol >= CashFlowEngine.VOLATILITY_CAUTION:
            actions.append(
                {
                    "title": "Plan using a safety buffer",
                    "detail": "Use below-average weeks (not just the mean) for planning. Hold a buffer before committing to new spend.",
                }
            )

        # Variable-cost actions
        if variable_cost_rate >= 0.30:
            actions.append(
                {
                    "title": "Improve margin on top items",
                    "detail": "Review your top 10 items/services. Look for supplier swaps, portion control, small price adjustments, "
                    "or steering customers toward higher-margin options.",
                }
            )

        # Deduplicate by title
        seen = set()
        deduped: List[Dict[str, str]] = []
        for a in actions:
            t = a.get("title")
            if t and t not in seen:
                seen.add(t)
                deduped.append(a)

        return deduped

    # -----------------------------
    # LLM narration (optional)
    # -----------------------------

    def _narrate_with_llm(self, payload: Dict[str, Any], model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Best-effort narration via DeepSeek.

        Returns:
            Parsed JSON dict if successful, else None.
        """
        try:
            from .deepseek_client import call_deepseek  # local import to avoid hard dependency
        except Exception as e:
            logger.warning("DeepSeek client import failed: %s", e)
            return None

        system_prompt = (
            "You are CashFlow Calm, a calm and conservative advisor for small business owners.\n\n"
            "Hard rules:\n"
            "- Do NOT compute or change any numbers. Use only the facts provided.\n"
            "- Do NOT invent transactions, causes, or external context.\n"
            "- Keep tone calm, direct, and practical.\n\n"
            "Return ONLY valid JSON in this schema:\n"
            "{\n"
            '  "headline": string,\n'
            '  "summary": string,\n'
            '  "why": [string, string, string],\n'
            '  "actions": [\n'
            '    {"title": string, "detail": string},\n'
            '    {"title": string, "detail": string},\n'
            '    {"title": string, "detail": string}\n'
            "  ]\n"
            "}\n"
        )

        user_prompt = "FACTS (do not alter):\n" + json.dumps(payload, indent=2, default=str)

        try:
            content = call_deepseek(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
            )
            return json.loads(content)
        except Exception as e:
            logger.warning("DeepSeek narration failed (skipping): %s", e)
            return None