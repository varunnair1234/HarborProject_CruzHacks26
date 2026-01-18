from typing import Dict, Optional
import logging

from app.services.rentguard_model import predict_expected_land_price, z_score_for_yoy

logger = logging.getLogger(__name__)


class RentEngine:
    """Compute impact of rent changes on business metrics"""

    @staticmethod
    def simulate_rent_impact(
        current_metrics: Dict,
        current_fixed_costs: Dict[str, float],
        increase_pct: Optional[float] = None,
        new_rent: Optional[float] = None,
        year: Optional[int] = None,
        observed_yoy_pct: Optional[float] = None,
    ) -> Dict:
        """
        Simulate the impact of a rent increase on business metrics.

        Args:
            current_metrics: Current cashflow metrics (from CashFlowEngine)
            current_fixed_costs: Current fixed costs (rent, payroll, other, cash_on_hand)
            increase_pct: Percentage increase (e.g., 15.0 for 15%)
            new_rent: Absolute new rent amount
            year: Optional year for market baseline comparison
            observed_yoy_pct: Optional observed YoY% used for z-score, if available
        """
        if increase_pct is None and new_rent is None:
            raise ValueError("Must provide either increase_pct or new_rent")

        current_rent = float(current_fixed_costs.get("rent") or 0.0)
        payroll = float(current_fixed_costs.get("payroll") or 0.0)
        other = float(current_fixed_costs.get("other") or 0.0)

        # Calculate new rent + increase %
        if new_rent is not None:
            new_rent_f = float(new_rent)
            calculated_new_rent = new_rent_f
            calculated_increase_pct = ((new_rent_f - current_rent) / current_rent * 100.0) if current_rent > 0 else 0.0
        else:
            inc = float(increase_pct)  # type: ignore[arg-type]
            calculated_new_rent = current_rent * (1.0 + inc / 100.0)
            calculated_increase_pct = inc

        delta_monthly = float(calculated_new_rent - current_rent)

        # Optional: compare to market baseline (RentGuard model)
        expected_land_price = None
        market_delta_monthly = None
        market_delta_pct = None
        market_z_score = None

        if year is not None:
            try:
                expected_land_price = float(predict_expected_land_price(int(year)))
                market_delta_monthly = float(calculated_new_rent) - expected_land_price
                market_delta_pct = (market_delta_monthly / expected_land_price * 100.0) if expected_land_price > 0 else None

                yoy_for_scoring = float(observed_yoy_pct) if observed_yoy_pct is not None else float(calculated_increase_pct)
                market_z_score = float(z_score_for_yoy(yoy_for_scoring))
            except Exception as e:
                logger.warning("RentGuard market baseline comparison failed (year=%s): %s", year, e)

        # Fixed cost burden (ratio) using avg monthly revenue proxy
        avg_daily_revenue = float(current_metrics.get("avg_daily_revenue") or 0.0)
        avg_monthly_revenue = avg_daily_revenue * 30.0
        new_total_fixed = float(calculated_new_rent + payroll + other)

        revenue_insufficient = avg_monthly_revenue <= 0
        new_fixed_cost_burden = None if revenue_insufficient else (new_total_fixed / avg_monthly_revenue)

        # Runway effects (net cashflow approach)
        cash_on_hand = current_fixed_costs.get("cash_on_hand")
        new_runway_days = None
        current_runway_days = current_metrics.get("runway_days")
        runway_impact_days = None
        runway_transition: Optional[str] = None
        runway_is_infinite = False

        if cash_on_hand is not None:
            cash = float(cash_on_hand or 0.0)
            daily_new_fixed = new_total_fixed / 30.0
            net_daily_cash_flow = avg_daily_revenue - daily_new_fixed

            if net_daily_cash_flow > 0:
                new_runway_days = None
                runway_is_infinite = True
            else:
                daily_burn = abs(net_daily_cash_flow)
                new_runway_days = (cash / daily_burn) if daily_burn > 0 else None

            # transitions
            if current_runway_days is None and new_runway_days is not None:
                runway_transition = "infinite_to_finite"
            elif current_runway_days is not None and new_runway_days is None:
                runway_transition = "finite_to_infinite"
            elif current_runway_days is not None and new_runway_days is not None:
                runway_impact_days = new_runway_days - current_runway_days

        new_risk_state = RentEngine._assess_new_risk_state(
            float(current_metrics.get("volatility") or 0.0),
            new_fixed_cost_burden,
            new_runway_days,
            float(current_metrics.get("trend_30d") or 0.0),
        )

        return {
            "current_rent": current_rent,
            "new_rent": float(calculated_new_rent),
            "old_rent": current_rent,
            "delta_monthly": delta_monthly,
            "delta_pct": float(calculated_increase_pct),
            "new_fixed_cost_burden": new_fixed_cost_burden,
            "revenue_insufficient": revenue_insufficient,
            "current_risk_state": current_metrics.get("risk_state", "unknown"),
            "new_risk_state": new_risk_state,
            "runway_impact_days": runway_impact_days,
            "runway_transition": runway_transition,
            "runway_is_infinite": runway_is_infinite,
            "market_expected_land_price": expected_land_price,
            "market_delta_monthly": market_delta_monthly,
            "market_delta_pct": market_delta_pct,
            "market_z_score": market_z_score,
        }

    @staticmethod
    def _assess_new_risk_state(
        volatility: float,
        new_burden: Optional[float],
        new_runway: Optional[float],
        trend_30d: float,
    ) -> str:
        """Assess risk state with new rent (uses same thresholds as CashFlowEngine).

        Note: When new_burden is None (no revenue), we treat it as infinite burden
        for risk assessment purposes, which will result in 'critical' state.
        """
        from app.services.cashflow_engine import CashFlowEngine

        # None burden means no revenue - treat as infinite for risk assessment
        burden_value = new_burden if new_burden is not None else float("inf")

        if new_runway is not None and new_runway < CashFlowEngine.RUNWAY_CRITICAL_DAYS:
            return "critical"
        if burden_value > CashFlowEngine.BURDEN_CRITICAL:
            return "critical"
        if volatility > CashFlowEngine.VOLATILITY_CRITICAL and trend_30d < -15:
            return "critical"

        if new_runway is not None and new_runway < CashFlowEngine.RUNWAY_CAUTION_DAYS:
            return "caution"
        if burden_value > CashFlowEngine.BURDEN_CAUTION:
            return "caution"
        if volatility > CashFlowEngine.VOLATILITY_CAUTION:
            return "caution"
        if trend_30d < -10:
            return "caution"

        return "healthy"
