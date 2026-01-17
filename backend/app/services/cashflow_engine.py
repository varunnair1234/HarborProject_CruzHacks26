import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class CashFlowEngine:
    """Deterministic cash flow metrics computation engine"""

    # Risk thresholds
    VOLATILITY_CAUTION = 0.3  # CV > 30%
    VOLATILITY_CRITICAL = 0.5  # CV > 50%

    # Fixed cost burden thresholds when burden is computed on REVENUE
    BURDEN_CAUTION = 0.7  # Fixed costs > 70% of revenue
    BURDEN_CRITICAL = 0.9  # Fixed costs > 90% of revenue

    # Fixed cost burden thresholds when burden is computed on GROSS PROFIT (revenue after variable costs)
    BURDEN_GP_CAUTION = 0.8  # Fixed costs > 80% of gross profit
    BURDEN_GP_CRITICAL = 1.0  # Fixed costs >= 100% of gross profit (structurally unprofitable)

    RUNWAY_CRITICAL_DAYS = 30  # < 30 days runway is critical
    RUNWAY_CAUTION_DAYS = 60  # < 60 days runway is caution

    @staticmethod
    def compute_metrics(
        daily_revenues: List[Dict],
        fixed_costs: Dict[str, float],
        variable_cost_rate: float = 0.0,
        days_per_month: float = 30.4,
    ) -> Dict:
        """Compute cash flow metrics from daily revenue data.

        Args:
            daily_revenues: List of dicts like {"date": ..., "revenue": ...}
            fixed_costs: Dict with rent, payroll, other, cash_on_hand
            variable_cost_rate: Fraction of revenue considered variable costs (0 to 1)
            days_per_month: Average number of days per month for monthly calculations

        Returns:
            Dict of computed metrics.
            Backward-compatible keys preserved:
              - avg_daily_revenue
              - fixed_cost_burden  (kept as burden on revenue for historical compatibility)
              - runway_days
              - risk_state
              - etc.
            New keys added:
              - avg_daily_gross_profit
              - fixed_cost_burden_revenue
              - fixed_cost_burden_gross_profit
              - net_daily_cash_flow
        """
        if not daily_revenues:
            raise ValueError("No revenue data provided")

        if not (0.0 <= variable_cost_rate <= 1.0):
            raise ValueError("variable_cost_rate must be between 0 and 1")

        for r in daily_revenues:
            if "revenue" not in r:
                raise ValueError("Each daily_revenues entry must include a 'revenue' field")

        # Convert to numpy arrays for computation
        revenues = np.array([float(r["revenue"]) for r in daily_revenues], dtype=float)
        data_days = int(len(revenues))

        # Basic statistics
        avg_daily_revenue = float(np.mean(revenues)) if data_days > 0 else 0.0
        avg_monthly_revenue = avg_daily_revenue * float(days_per_month)

        # Gross profit (revenue after variable costs)
        vcr = float(variable_cost_rate)
        avg_daily_gross_profit = avg_daily_revenue * (1.0 - vcr)
        avg_monthly_gross_profit = avg_daily_gross_profit * float(days_per_month)

        # Trends (percentage change over periods)
        trend_7d = CashFlowEngine._compute_trend(revenues, 7)
        trend_14d = CashFlowEngine._compute_trend(revenues, 14)
        trend_30d = CashFlowEngine._compute_trend(revenues, 30)

        # Volatility (coefficient of variation)
        volatility = float(np.std(revenues) / avg_daily_revenue) if avg_daily_revenue > 0 else 0.0

        # Fixed costs
        total_fixed_monthly = (
            float(fixed_costs.get("rent", 0.0))
            + float(fixed_costs.get("payroll", 0.0))
            + float(fixed_costs.get("other", 0.0))
        )
        daily_fixed_costs = total_fixed_monthly / float(days_per_month)

        # Burdens
        fixed_cost_burden_revenue = (
            total_fixed_monthly / avg_monthly_revenue if avg_monthly_revenue > 0 else float("inf")
        )
        fixed_cost_burden_gross_profit = (
            total_fixed_monthly / avg_monthly_gross_profit
            if avg_monthly_gross_profit > 0
            else float("inf")
        )

        # Backward compatible: keep fixed_cost_burden as burden-on-revenue
        fixed_cost_burden = fixed_cost_burden_revenue

        # Net daily cash flow (gross profit - fixed costs)
        net_daily_cash_flow = avg_daily_gross_profit - daily_fixed_costs

        # Runway (if cash_on_hand is provided)
        cash_on_hand = fixed_costs.get("cash_on_hand")
        runway_days: Optional[float] = None
        if cash_on_hand is not None:
            if net_daily_cash_flow >= 0:
                runway_days = None  # Not burning cash on average
            else:
                daily_burn = abs(net_daily_cash_flow)
                runway_days = float(float(cash_on_hand) / daily_burn) if daily_burn > 0 else None

        # Risk horizon (how many days ahead to monitor)
        risk_horizon = CashFlowEngine._compute_risk_horizon(volatility, trend_30d)

        # Risk state assessment
        # Use gross-profit burden when variable_cost_rate > 0, otherwise revenue burden.
        burden_for_risk = fixed_cost_burden_gross_profit if vcr > 0 else fixed_cost_burden_revenue

        risk_state = CashFlowEngine._assess_risk_state(
            volatility=volatility,
            burden_for_risk=burden_for_risk,
            runway_days=runway_days,
            trend_30d=trend_30d,
            net_daily_cash_flow=net_daily_cash_flow,
            variable_cost_rate=vcr,
        )

        # Confidence score (based on data quantity and quality)
        confidence = CashFlowEngine._compute_confidence(data_days, volatility)

        return {
            # Existing keys
            "avg_daily_revenue": avg_daily_revenue,
            "trend_7d": trend_7d,
            "trend_14d": trend_14d,
            "trend_30d": trend_30d,
            "volatility": volatility,
            "fixed_cost_burden": fixed_cost_burden,
            "runway_days": runway_days,
            "risk_horizon": risk_horizon,
            "risk_state": risk_state,
            "confidence": confidence,

            # New keys (safe to ignore by current UI)
            "avg_daily_gross_profit": avg_daily_gross_profit,
            "fixed_cost_burden_revenue": fixed_cost_burden_revenue,
            "fixed_cost_burden_gross_profit": fixed_cost_burden_gross_profit,
            "net_daily_cash_flow": net_daily_cash_flow,
            "days_per_month": float(days_per_month),
        }

    @staticmethod
    def _compute_trend(revenues: np.ndarray, days: int) -> float:
        """Compute percentage change trend over last N days."""
        if len(revenues) == 0:
            return 0.0

        if len(revenues) < days:
            days = len(revenues)

        if days < 2:
            return 0.0

        recent = revenues[-days:]
        older_half = recent[: days // 2]
        newer_half = recent[days // 2 :]

        avg_older = float(np.mean(older_half)) if len(older_half) else 0.0
        avg_newer = float(np.mean(newer_half)) if len(newer_half) else 0.0

        if avg_older == 0:
            return 0.0

        return float(((avg_newer - avg_older) / avg_older) * 100.0)

    @staticmethod
    def _compute_risk_horizon(volatility: float, trend_30d: float) -> int:
        """Determine how many days ahead to monitor based on risk factors."""
        base_horizon = 14

        # Increase monitoring period if volatile
        if volatility > CashFlowEngine.VOLATILITY_CRITICAL:
            base_horizon = 30
        elif volatility > CashFlowEngine.VOLATILITY_CAUTION:
            base_horizon = 21

        # Increase if declining trend
        if trend_30d < -10:
            base_horizon += 7

        return int(base_horizon)

    @staticmethod
    def _assess_risk_state(
        volatility: float,
        burden_for_risk: float,
        runway_days: Optional[float],
        trend_30d: float,
        net_daily_cash_flow: float,
        variable_cost_rate: float,
    ) -> str:
        """Assess overall risk state: healthy, caution, or critical.

        Key fix:
        - If variable_cost_rate > 0, burden_for_risk is on gross profit.
        - If net_daily_cash_flow < 0 and burden_for_risk >= 1.0 => structural margin issue => critical.
        """

        # Structural unprofitability (margin cannot cover fixed costs)
        if variable_cost_rate > 0 and burden_for_risk >= CashFlowEngine.BURDEN_GP_CRITICAL:
            return "critical"
        if net_daily_cash_flow < 0 and variable_cost_rate > 0 and burden_for_risk >= CashFlowEngine.BURDEN_GP_CAUTION:
            return "caution"

        # Critical conditions
        if runway_days is not None and runway_days < CashFlowEngine.RUNWAY_CRITICAL_DAYS:
            return "critical"

        # When variable_cost_rate == 0, burden_for_risk is on revenue
        if variable_cost_rate == 0 and burden_for_risk > CashFlowEngine.BURDEN_CRITICAL:
            return "critical"

        if volatility > CashFlowEngine.VOLATILITY_CRITICAL and trend_30d < -15:
            return "critical"

        # Caution conditions
        if runway_days is not None and runway_days < CashFlowEngine.RUNWAY_CAUTION_DAYS:
            return "caution"

        if variable_cost_rate == 0 and burden_for_risk > CashFlowEngine.BURDEN_CAUTION:
            return "caution"

        if volatility > CashFlowEngine.VOLATILITY_CAUTION:
            return "caution"

        if trend_30d < -10:
            return "caution"

        # Healthy
        return "healthy"

    @staticmethod
    def _compute_confidence(data_days: int, volatility: float) -> float:
        """Compute confidence score (0.0 to 1.0) based on data quality."""
        # Data quantity component (0.0 to 0.7)
        if data_days >= 90:
            data_confidence = 0.7
        elif data_days >= 30:
            data_confidence = 0.5 + (data_days - 30) / 60.0 * 0.2
        else:
            data_confidence = 0.3 + (data_days / 30.0) * 0.2

        # Volatility component (0.0 to 0.3)
        if volatility < 0.2:
            volatility_confidence = 0.3
        elif volatility < 0.4:
            volatility_confidence = 0.2
        else:
            volatility_confidence = 0.1

        return float(min(data_confidence + volatility_confidence, 1.0))
