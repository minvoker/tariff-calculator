"""
Core calculation engine for tariff billing.

This module evaluates a canonical tariff JSON for a billing period, computes
usage aggregates, performs unit conversions, evaluates each component's
calculation expression safely, and returns a detailed breakdown and total cost.

It supports the canonical schema defined in docs/tariff_schema.json, including
the following:
  * Time bands and date ranges to assign peak/offpeak/shoulder labels
  * Components with units like c/kWh, c/day, $/kVA/Mth, $/meter/year
  * Multi-tier rate schedules (selects the applicable tier based on usage)
  * Seasonal applicability via the "season" property
  * Loss factors per component (default 1.0 if absent)
  * Safe evaluation of arithmetic expressions using allowed variables and
    whitelisted math functions (no eval or unsafe code)

Usage variables available for expressions:
  - total_usage: total kWh in period
  - peak_usage: kWh labelled "peak" by time bands
  - off_peak_usage: kWh not in peak (or as specified by offpeak bands)
  - shoulder_usage: kWh labelled "shoulder" (if defined)
  - max_kva: maximum kva recorded (if available, else 0)
  - incentive_kva: rolling or incentive demand (if available, else 0)
  - rate: dollar amount per unit (converted from published unit)
  - loss_factor: multiplier (defaults to 1.0 if absent)
  - days: integer number of days in billing period
  - billing_period_start, billing_period_end: strings YYYY-MM-DD

The engine persists a summary in calc_runs table via upsert_calc_run.
"""

from datetime import datetime, date
import math
import ast
import calendar
from typing import Dict, Any, Optional, Callable

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..models import TariffVersion, MeterReading, CalcRun
from .timeband import assign_band


def _safe_eval(expr: str, variables: Dict[str, Any]) -> float:
    """Safely evaluate an arithmetic expression using whitelisted functions.

    Only allows basic arithmetic operations, comparison, boolean operators,
    names corresponding to variables in `variables`, and functions from math,
    min, max, and round.
    """
    # Prepare allowed names
    allowed_funcs: Dict[str, Callable] = {
        'min': min,
        'max': max,
        'round': round,
    }
    # Add math functions
    for fname in dir(math):
        if not fname.startswith('_'):
            func = getattr(math, fname)
            if callable(func):
                allowed_funcs[fname] = func

    allowed_names = set(variables.keys()) | set(allowed_funcs.keys()) | {'math'}

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Num):  # type: ignore
            return node.n
        if isinstance(node, ast.Constant):  # for Python3.8+
            return node.value
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                return left / right
            elif isinstance(node.op, ast.Mod):
                return left % right
            elif isinstance(node.op, ast.Pow):
                return left ** right
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +operand
            elif isinstance(node.op, ast.USub):
                return -operand
        if isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            if node.id in allowed_funcs:
                return allowed_funcs[node.id]
            if node.id == 'math':
                return math
            raise ValueError(f"Use of name {node.id} not allowed")
        if isinstance(node, ast.Call):
            func = _eval(node.func)
            args = [_eval(arg) for arg in node.args]
            kwargs = {kw.arg: _eval(kw.value) for kw in node.keywords}
            return func(*args, **kwargs)
        if isinstance(node, ast.IfExp):
            cond = _eval(node.test)
            return _eval(node.body) if cond else _eval(node.orelse)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            results = []
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                if isinstance(op, ast.Lt):
                    results.append(left < right)
                elif isinstance(op, ast.LtE):
                    results.append(left <= right)
                elif isinstance(op, ast.Gt):
                    results.append(left > right)
                elif isinstance(op, ast.GtE):
                    results.append(left >= right)
                elif isinstance(op, ast.Eq):
                    results.append(left == right)
                elif isinstance(op, ast.NotEq):
                    results.append(left != right)
                else:
                    raise ValueError(f"Comparison operator {op} not allowed")
                left = right
            return all(results)
        if isinstance(node, ast.BoolOp):
            values = [_eval(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            elif isinstance(node.op, ast.Or):
                return any(values)
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")

    try:
        parsed = ast.parse(expr, mode='eval')
    except Exception as e:
        raise ValueError(f"Invalid expression: {expr}: {e}")
    return float(_eval(parsed))


def _parse_rate(unit: str, value: float, days: int, billing_start: date) -> float:
    """
    Convert a published rate into a dollar value per unit for the billing period.

    For units expressed in cents (c/...), divide by 100 to convert to dollars.
    Prorate monthly or yearly rates based on the length of the billing period.

    Args:
        unit: original unit string from tariff (e.g. 'c/kWh', 'c/day', '$/kVA/Mth', '$/meter/year')
        value: numeric value from rate_schedule
        days: number of days in the billing period
        billing_start: start date of billing period (for month-based proration)

    Returns:
        Converted rate value in dollars per unit (prorated where appropriate).
    """
    if unit is None:
        return value
    unit = unit.strip().lower()
    rate = float(value)
    # Convert cents to dollars
    if unit.startswith('c/'):
        rate = rate / 100.0
        unit = unit[2:]
    # Handle per day charges
    if unit.endswith('/day'):
        # Already in $/day; the caller should multiply by days for total
        return rate
    # Per-kWh charges: rate already $/kWh
    if unit.endswith('/kwh'):
        return rate
    # Per-month or per-mth charges (e.g. $/kva/mth, $/kva/month, $/meter/month)
    if unit.endswith('/mth') or unit.endswith('/month'):
        # Determine the number of days in the billing month for proration
        month_days = calendar.monthrange(billing_start.year, billing_start.month)[1]
        return rate * (days / month_days)
    # Per-kva/month is handled above by the generic month logic
    # Per-year charges (e.g. $/meter/year)
    if unit.endswith('/meter/year') or unit.endswith('/year'):
        return rate * (days / 365.0)
    # Unknown unit: return the value as a dollar rate
    return rate


def _select_rate_value(rate_schedule: list, usage: float) -> float:
    """
    Select a value from a rate_schedule based on usage for tiered rates.

    If multiple tiers are defined with 'from' and/or 'to', choose the tier where
    usage is within the (from, to) bounds. If usage exceeds all defined tiers,
    use the last tier's value. If no tiers match, return the first value.
    """
    if not rate_schedule:
        return 0.0
    # If only one tier, return its value
    if len(rate_schedule) == 1:
        return float(rate_schedule[0].get('value', 0.0))
    # Find tier where usage is between from and to
    applicable = None
    for tier in rate_schedule:
        frm = tier.get('from')
        to = tier.get('to')
        val = float(tier.get('value', 0.0))
        if frm is None and (to is None or usage <= to):
            applicable = val
            break
        if frm is not None and to is None and usage >= frm:
            applicable = val
            break
        if frm is not None and to is not None and usage >= frm and usage < to:
            applicable = val
            break
    if applicable is not None:
        return applicable
    # Default to last tier's value
    return float(rate_schedule[-1].get('value', 0.0))


def calculate_bill(db: Session, customer_id: int, tariff_version_id: int, start: datetime, end: datetime):
    """
    Calculate a bill for a customer using the specified tariff version within
    a billing period. Returns a dict with total cost, a breakdown per component,
    and the units of currency.
    """
    tv = db.get(TariffVersion, tariff_version_id)
    if not tv:
        return {"total_cost": 0.0, "breakdown": {}, "units": "AUD"}
    canonical = tv.canonical_json or {}
    components = canonical.get("components", [])
    time_bands = canonical.get("time_bands", [])

    # Fetch meter readings for the period
    readings = db.execute(
        select(MeterReading).where(
            MeterReading.customer_id == customer_id,
            MeterReading.timestamp >= start,
            MeterReading.timestamp < end
        ).order_by(MeterReading.timestamp.asc())
    ).scalars().all()

    # Compute days in period (inclusive of start date but not end date)
    days = max(1, (end.date() - start.date()).days)

    # Aggregate usage (kWh) by band
    total_usage: float = 0.0
    peak_usage: float = 0.0
    off_peak_usage: float = 0.0
    shoulder_usage: float = 0.0
    # Additional buckets for potential network usage (approximate using retail usage)
    for r in readings:
        total_usage += float(r.kwh_used)
        # Determine which time band this reading falls into
        band_id = assign_band(r.timestamp, canonical)
        b = (band_id or '').lower()
        # Treat variations of peak / offpeak / shoulder identically
        if b in ('peak', 'usage_peak', 'retail_peak', 'network_peak'):
            peak_usage += float(r.kwh_used)
        elif b in ('shoulder', 'usage_shoulder', 'retail_shoulder', 'network_shoulder'):
            shoulder_usage += float(r.kwh_used)
        else:
            # offpeak or any other band falls into off_peak_usage by default
            off_peak_usage += float(r.kwh_used)
    # Approximate network usage as equal to retail usage (we have no separate network meter)
    network_peak_usage: float = peak_usage
    network_off_peak_usage: float = off_peak_usage

    # Demand metrics (placeholder: assume no kva data available)
    # If future meter data includes kva readings, these should be computed here.
    max_kva: float = 0.0
    incentive_kva: float = 0.0

    # Loss factor default
    default_loss_factor = 1.0

    breakdown: Dict[str, dict] = {}
    total_cost = 0.0

    # Determine billing start date for proration
    billing_start_date = start.date()

    # Variables common across all components
    # Note: network_* variables mirror retail usage, as separate network readings are not available.
    base_vars = {
        'total_usage': total_usage,
        'peak_usage': peak_usage,
        'off_peak_usage': off_peak_usage,
        'shoulder_usage': shoulder_usage,
        'network_peak_usage': network_peak_usage,
        'network_off_peak_usage': network_off_peak_usage,
        'network_total_usage': total_usage,
        'max_kva': max_kva,
        'incentive_kva': incentive_kva,
        'days': days,
        'billing_period_start': billing_start_date.strftime("%Y-%m-%d"),
        'billing_period_end': (end.date()).strftime("%Y-%m-%d"),
    }

    for comp in components:
        comp_id = comp.get('id')
        if not comp_id:
            continue
        # Check season applicability
        season = comp.get('season')
        if season:
            try:
                from_date = datetime.strptime(season.get('from'), "%Y-%m-%d").date()
                to_date = datetime.strptime(season.get('to'), "%Y-%m-%d").date()
                # If billing period end date before season start or start date after season end, skip
                if end.date() < from_date or start.date() > to_date:
                    continue
            except Exception:
                pass
        # Determine usage variable to use for tier selection
        applies = [a.lower() for a in comp.get('applies_to', [])]
        usage_for_tier: float = 0.0
        # Map applies_to tokens to usage buckets
        if any(tag in applies for tag in ('usage_peak', 'network_peak')):
            usage_for_tier = peak_usage
        elif any(tag in applies for tag in ('usage_offpeak', 'usage_off_peak', 'network_offpeak', 'network_off_peak')):
            usage_for_tier = off_peak_usage
        elif any(tag in applies for tag in ('usage_shoulder', 'shoulder_usage', 'network_shoulder')):
            usage_for_tier = shoulder_usage
        elif any(tag in applies for tag in ('usage_total', 'total_usage', 'usage_all')):
            usage_for_tier = total_usage
        elif 'demand' in applies:
            usage_for_tier = max_kva
        elif 'incentive_demand' in applies:
            usage_for_tier = incentive_kva
        # Select rate value from schedule
        rate_val = _select_rate_value(comp.get('rate_schedule', []), usage_for_tier)
        # Convert rate to dollars per unit (prorated where needed)
        unit = comp.get('unit')
        rate_dollars = _parse_rate(unit, rate_val, days, billing_start_date)
        # Build variables for expression
        vars_for_expr = base_vars.copy()
        vars_for_expr.update({
            'rate': rate_dollars,
            'loss_factor': comp.get('loss_factor') if comp.get('loss_factor') not in (None, '') else default_loss_factor
        })
        # Evaluate calculation expression
        expr = comp.get('calculation')
        if not expr:
            continue
        try:
            cost = _safe_eval(expr, vars_for_expr)
        except Exception:
            # If expression fails, skip this component
            continue
        # Only include if positive cost
        if cost is None:
            continue
        try:
            cost_float = float(cost)
        except Exception:
            continue
        # Determine units used and label
        units_used: Optional[float] = None
        unit_label: Optional[str] = None
        # Determine units used and label based on applies_to
        if any(tag in applies for tag in ('usage_peak', 'network_peak')):
            units_used = peak_usage
            unit_label = 'kWh'
        elif any(tag in applies for tag in ('usage_offpeak', 'usage_off_peak', 'network_offpeak', 'network_off_peak')):
            units_used = off_peak_usage
            unit_label = 'kWh'
        elif any(tag in applies for tag in ('usage_shoulder', 'shoulder_usage', 'network_shoulder')):
            units_used = shoulder_usage
            unit_label = 'kWh'
        elif any(tag in applies for tag in ('usage_total', 'total_usage', 'usage_all')):
            units_used = total_usage
            unit_label = 'kWh'
        elif 'demand' in applies:
            units_used = max_kva
            unit_label = 'kVA'
        elif 'incentive_demand' in applies:
            units_used = incentive_kva
            unit_label = 'kVA'
        elif any(tag in applies for tag in ('fixed', 'meter', 'metering', 'ancillary')):
            # Per-day or per-meter charges use days as units
            units_used = days
            unit_label = 'days'
        else:
            # For unknown categories, use the usage selected for tiering
            units_used = usage_for_tier
            unit_label = 'unit'
        # If units_used is None, skip
        if units_used is None:
            continue
        breakdown[comp_id] = {
            'units_used': round(units_used, 4) if isinstance(units_used, float) else int(units_used),
            'unit_label': unit_label,
            'cost': round(cost_float, 4)
        }
        total_cost += cost_float

    return {
        'total_cost': round(total_cost, 4),
        'breakdown': breakdown,
        'units': 'AUD'
    }


def upsert_calc_run(db: Session, customer_id: int, tariff_version_id: int, start: datetime, end: datetime, checksum: str, result: dict) -> int:
    """
    Upsert a CalcRun record: return existing row ID if the checksum and period
    match, otherwise create a new row.
    """
    row = db.execute(
        select(CalcRun).where(
            CalcRun.customer_id == customer_id,
            CalcRun.tariff_version_id == tariff_version_id
        ).order_by(CalcRun.id.desc())
    ).scalars().first()
    if row and isinstance(row.result_summary_json, dict):
        meta = row.result_summary_json.get('_meta', {})
        if meta.get('checksum') == checksum and meta.get('start') == str(start) and meta.get('end') == str(end):
            return row.id
    newrow = CalcRun(
        customer_id=customer_id,
        tariff_version_id=tariff_version_id,
        status='completed',
        result_summary_json={
            '_meta': {'start': str(start), 'end': str(end), 'checksum': checksum},
            'result': result
        }
    )
    db.add(newrow)
    db.commit()
    db.refresh(newrow)
    return newrow.id
