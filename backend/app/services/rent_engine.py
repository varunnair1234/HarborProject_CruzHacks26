from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class RentEngine:
    """Compute impact of rent changes on business metrics"""
    
    @staticmethod
    def simulate_rent_impact(
        current_metrics: Dict,
        current_fixed_costs: Dict[str, float],
        increase_pct: Optional[float] = None,
        new_rent: Optional[float] = None
    ) -> Dict:
        """
        Simulate the impact of a rent increase on business metrics
        
        Args:
            current_metrics: Current cashflow metrics
            current_fixed_costs: Current fixed costs (rent, payroll, other)
            increase_pct: Percentage increase (e.g., 15.0 for 15%)
            new_rent: Absolute new rent amount
            
        Returns:
            Dict with impact metrics
        """
        # Validate inputs
        if increase_pct is None and new_rent is None:
            raise ValueError("Must provide either increase_pct or new_rent")
        
        current_rent = current_fixed_costs.get("rent", 0)
        
        # Calculate new rent
        if new_rent is not None:
            calculated_new_rent = new_rent
            calculated_increase_pct = (
                ((new_rent - current_rent) / current_rent * 100) 
                if current_rent > 0 else 0
            )
        else:
            calculated_new_rent = current_rent * (1 + increase_pct / 100)
            calculated_increase_pct = increase_pct
        
        # Calculate delta
        delta_monthly = calculated_new_rent - current_rent
        
        # Recompute fixed cost burden with new rent
        avg_monthly_revenue = current_metrics.get("avg_daily_revenue", 0) * 30
        new_total_fixed = (
            calculated_new_rent +
            current_fixed_costs.get("payroll", 0) +
            current_fixed_costs.get("other", 0)
        )
        new_fixed_cost_burden = (
            new_total_fixed / avg_monthly_revenue if avg_monthly_revenue > 0 else float("inf")
        )
        
        # Recompute runway if available
        cash_on_hand = current_fixed_costs.get("cash_on_hand")
        new_runway_days = None
        current_runway_days = current_metrics.get("runway_days")
        runway_impact_days = None
        
        if cash_on_hand is not None:
            avg_daily_revenue = current_metrics.get("avg_daily_revenue", 0)
            daily_new_fixed = new_total_fixed / 30
            net_daily_cash_flow = avg_daily_revenue - daily_new_fixed
            
            if net_daily_cash_flow > 0:
                new_runway_days = None  # Positive cash flow
            else:
                daily_burn = abs(net_daily_cash_flow)
                new_runway_days = cash_on_hand / daily_burn if daily_burn > 0 else None
            
            # Calculate impact
            if current_runway_days is not None and new_runway_days is not None:
                runway_impact_days = new_runway_days - current_runway_days
        
        # Assess new risk state
        new_risk_state = RentEngine._assess_new_risk_state(
            current_metrics.get("volatility", 0),
            new_fixed_cost_burden,
            new_runway_days,
            current_metrics.get("trend_30d", 0)
        )
        
        return {
            "current_rent": current_rent,
            "new_rent": calculated_new_rent,
            "delta_monthly": delta_monthly,
            "delta_pct": calculated_increase_pct,
            "new_fixed_cost_burden": new_fixed_cost_burden,
            "current_risk_state": current_metrics.get("risk_state", "unknown"),
            "new_risk_state": new_risk_state,
            "runway_impact_days": runway_impact_days,
        }
    
    @staticmethod
    def _assess_new_risk_state(
        volatility: float,
        new_burden: float,
        new_runway: Optional[float],
        trend_30d: float
    ) -> str:
        """Assess risk state with new rent (uses same thresholds as CashFlowEngine)"""
        from app.services.cashflow_engine import CashFlowEngine
        
        # Critical conditions
        if new_runway is not None and new_runway < CashFlowEngine.RUNWAY_CRITICAL_DAYS:
            return "critical"
        if new_burden > CashFlowEngine.BURDEN_CRITICAL:
            return "critical"
        if volatility > CashFlowEngine.VOLATILITY_CRITICAL and trend_30d < -15:
            return "critical"
        
        # Caution conditions
        if new_runway is not None and new_runway < CashFlowEngine.RUNWAY_CAUTION_DAYS:
            return "caution"
        if new_burden > CashFlowEngine.BURDEN_CAUTION:
            return "caution"
        if volatility > CashFlowEngine.VOLATILITY_CAUTION:
            return "caution"
        if trend_30d < -10:
            return "caution"
        
        return "healthy"
