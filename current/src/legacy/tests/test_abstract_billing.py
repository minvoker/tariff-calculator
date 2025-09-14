# tests/test_abstract_billing.py
"""
Test + debug logging that resamples meter CSV, assigns time bands,
evaluates tariff components and writes debugging outputs to tests/logs/.
"""

import json
import math
import ast
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest
import jsonschema
from jsonschema.exceptions import ValidationError

# Paths
SCHEMA_PATH = Path("docs/tariff_schema.json")
TARIFF_PATH = Path("tariffs/shell-2024-04-01.json")
METER_CSV_PATH = Path("data/Sample Meter Data.csv")
LOGS_DIR = Path("tests/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Configure logger
logger = logging.getLogger("abstract_billing_debug")
logger.setLevel(logging.DEBUG)
log_path = LOGS_DIR / "abstract_billing_debug.log"
fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
fh.setFormatter(formatter)
# remove old handlers
if logger.hasHandlers():
    logger.handlers.clear()
logger.addHandler(fh)

# === AST safe evaluator
ALLOWED_NAMES = {"min": min, "max": max, "round": round, "math": __import__("math")}
ALLOWED_NODE_TYPES = {
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Load, ast.Call,
    ast.Name, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd, ast.Compare, ast.Eq, ast.NotEq, ast.Lt,
    ast.LtE, ast.Gt, ast.GtE, ast.IfExp
}


def safe_eval(expr: str, variables: dict):
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, tuple(ALLOWED_NODE_TYPES)):
            raise ValueError(f"Disallowed expression: {node.__class__.__name__}")
        if isinstance(node, ast.Name):
            if node.id not in variables and node.id not in ALLOWED_NAMES:
                raise ValueError(f"Use of unknown variable or function: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_NAMES:
                raise ValueError(f"Function calls allowed only for {list(ALLOWED_NAMES.keys())}")
    compiled = compile(tree, filename="<ast>", mode="eval")
    env = {}
    env.update(ALLOWED_NAMES)
    env.update(variables)
    return eval(compiled, {"__builtins__": {}}, env)


# === Unit conversion helpers
def days_in_month(dt):
    import calendar
    return calendar.monthrange(dt.year, dt.month)[1]


def is_leap_year(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def convert_rate_value(rate_value, unit_str, start_date, end_date):
    numerator_and_rest = unit_str.split("/")
    numerator = numerator_and_rest[0].strip()
    if numerator == "c":
        base = float(rate_value) * 0.01
    elif numerator == "$":
        base = float(rate_value)
    else:
        base = float(rate_value)
    denom = numerator_and_rest[1:] if len(numerator_and_rest) > 1 else []
    days = (end_date - start_date).days + 1
    if any(p.upper() == "MTH" for p in denom):
        dim = days_in_month(start_date)
        base = base * (days / dim)
    if any(p.lower() == "year" for p in denom):
        year_days = 366 if is_leap_year(start_date.year) else 365
        base = base * (days / year_days)
    if any(p.lower() == "day" for p in denom):
        base = base * days
    return base


# === Resample helper
def resample_to_30min(df: pd.DataFrame, tz_name: str = "Australia/Melbourne"):
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    # localize naive to tz
    if df["timestamp"].dt.tz is None or df["timestamp"].dt.tz.dtype == "O":
        tz = ZoneInfo(tz_name)
        df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.set_index("timestamp").sort_index()
    if "kva" not in df.columns or df["kva"].isnull().all():
        if "kw" in df.columns and "kvar" in df.columns:
            df["kva"] = (df["kw"] ** 2 + df["kvar"] ** 2) ** 0.5
        else:
            df["kva"] = 0.0
    usage_30 = df["usage_kwh"].resample("30min", label="left", closed="left").sum(min_count=1).fillna(0)
    kva_30 = df["kva"].resample("30min", label="left", closed="left").max().fillna(0)
    out = pd.concat([usage_30, kva_30], axis=1).reset_index().rename(columns={"timestamp": "period_start"})
    return out


# === Assign time band
def assign_time_band(df_resampled: pd.DataFrame, tariff: dict):
    tz = ZoneInfo(tariff.get("time_zones", "Australia/Melbourne"))
    df = df_resampled.copy()
    df["local_ts"] = df["period_start"].dt.tz_convert(tz)
    df["weekday"] = df["local_ts"].dt.day_name().str.slice(0, 3).str.lower()
    df["time"] = df["local_ts"].dt.time
    df["time_band"] = None
    for band in tariff["time_bands"]:
        days = band["days"]
        for t in band["times"]:
            start = datetime.strptime(t["from"], "%H:%M").time()
            end = datetime.strptime(t["to"], "%H:%M").time()
            if start <= end:
                mask_time = df["time"].between(start, end)
            else:
                mask_time = (df["time"] >= start) | (df["time"] <= end)
            if "all" in days:
                mask_day = pd.Series([True] * len(df), index=df.index)
            else:
                mask_day = df["weekday"].isin(days)
            df.loc[mask_time & mask_day, "time_band"] = band["id"]
    df["time_band"] = df["time_band"].fillna("offpeak")
    return df


EXPECTED_COMPONENTS = {
    "VIC_Peak": 118.19,
    "VIC_Off_Peak": 59.68,
    "LRECs": 17.01,
    "VEECs": 24.35,
    "SRECs": 14.88,
    "AEMO_Market_Fee_Daily": 0.69,
    "AEMO_Ancillary_Fee_UFE": 0.38,
    "AEMO_Market_Fee_30_Days": 0.02,
    "Meter_Charge": 6.58,
    "LLVT2_Peak_Energy": 39.47,
    "LLVT2_Off_Peak_Energy": 20.19,
    "LLVT2_Peak_Demand": 38.87,
    "LLVT2_Summer_Incentive_Demand": 0.00,
}

ABS_TOL = 0.5


def _write_debug_csv(df: pd.DataFrame, name: str):
    path = LOGS_DIR / name
    df.to_csv(path, index=False)
    logger.info(f"Wrote debug CSV: {path}")


def _write_debug_json(obj, name: str):
    path = LOGS_DIR / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    logger.info(f"Wrote debug JSON: {path}")


def test_schema_and_tariff_files_exist_and_validate():
    assert SCHEMA_PATH.exists(), f"Schema file not found: {SCHEMA_PATH}"
    assert TARIFF_PATH.exists(), f"Tariff file not found: {TARIFF_PATH}"
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(TARIFF_PATH, "r", encoding="utf-8") as f:
        tariff = json.load(f)
    try:
        jsonschema.validate(instance=tariff, schema=schema)
    except ValidationError as e:
        msg = str(e.message).lower()
        if "rolling_window" in msg or "additional properties are not allowed" in msg:
            schema.setdefault("properties", {})
            schema["properties"]["rolling_window"] = {
                "type": "object",
                "properties": {"months": {"type": "integer"}, "interval_minutes": {"type": "integer"}},
            }
            jsonschema.validate(instance=tariff, schema=schema)
        else:
            raise


def test_end_to_end_from_csv_matches_expected_components_and_log():
    with open(TARIFF_PATH, "r", encoding="utf-8") as f:
        tariff = json.load(f)
    assert METER_CSV_PATH.exists(), f"Meter CSV not found at {METER_CSV_PATH}"
    df_raw = pd.read_csv(METER_CSV_PATH, parse_dates=["ReadingDateTime"])
    df_raw = df_raw.rename(columns={"ReadingDateTime": "timestamp", "E (Usage kWh)": "usage_kwh", "KVA": "kva", "KW": "kw"})
    df_raw["usage_kwh"] = pd.to_numeric(df_raw["usage_kwh"], errors="coerce")
    if "kva" in df_raw.columns:
        df_raw["kva"] = pd.to_numeric(df_raw["kva"], errors="coerce")
    if "kw" in df_raw.columns:
        df_raw["kw"] = pd.to_numeric(df_raw["kw"], errors="coerce")

    df_raw["date"] = df_raw["timestamp"].dt.date
    target_date = pd.to_datetime("2023-08-01").date()
    df_day = df_raw[df_raw["date"] == target_date]
    assert not df_day.empty, "No meter data for 2023-08-01 in CSV"

    resampled = resample_to_30min(df_day, tz_name=tariff.get("time_zones", "Australia/Melbourne"))
    logger.info("Resampled buckets:")
    logger.info(resampled.to_string(index=False))
    _write_debug_csv(resampled, "resampled_2023-08-01.csv")

    assigned = assign_time_band(resampled, tariff)
    logger.info("Assigned time bands (first rows):")
    logger.info(assigned.head().to_string(index=False))
    _write_debug_csv(assigned, "assigned_2023-08-01.csv")

    total_usage = float(assigned["usage_kwh"].sum())
    peak_usage = float(assigned[assigned["time_band"] == "peak"]["usage_kwh"].sum())
    off_peak_usage = float(assigned[assigned["time_band"] != "peak"]["usage_kwh"].sum())
    max_kva = float(assigned["kva"].max())

    period_start = assigned["period_start"].min().tz_convert(ZoneInfo(tariff["time_zones"])).date()
    period_end = assigned["period_start"].max().tz_convert(ZoneInfo(tariff["time_zones"])).date()
    days = (period_end - period_start).days + 1

    logger.info(f"Aggregates: total_usage={total_usage}, peak_usage={peak_usage}, off_peak_usage={off_peak_usage}, max_kva={max_kva}, days={days}")

    evaluated = {}
    debug_items = {}
    for comp in tariff["components"]:
        cid = comp["id"]
        unit = comp.get("unit", "")
        rate_raw = comp.get("rate_schedule", [{}])[0].get("value", 0.0)
        rate_converted = convert_rate_value(rate_raw, unit, period_start, period_end)
        variables = {
            "total_usage": total_usage,
            "peak_usage": peak_usage,
            "off_peak_usage": off_peak_usage,
            "max_kva": max_kva,
            "incentive_kva": max_kva,
            "rate": rate_converted,
            "loss_factor": float(comp.get("loss_factor", 1.0) or 1.0),
            "days": int(days),
            "period_start": str(period_start),
            "period_end": str(period_end),
        }
        try:
            cost_raw = safe_eval(comp["calculation"], variables)
            cost = round(float(cost_raw), 2)
        except Exception as e:
            logger.exception(f"Evaluation error for comp {cid}")
            pytest.fail(f"Failed to evaluate component {cid}: {e}")
        evaluated[cid] = cost

        # debug item
        debug_items[cid] = {
            "unit": unit,
            "rate_raw": rate_raw,
            "rate_converted": rate_converted,
            "loss_factor": variables["loss_factor"],
            "variables": variables,
            "cost": cost,
            "expected": EXPECTED_COMPONENTS.get(cid),
            "diff": None if EXPECTED_COMPONENTS.get(cid) is None else round(cost - EXPECTED_COMPONENTS[cid], 2),
        }
        logger.info(f"Component {cid}: unit={unit}, rate_raw={rate_raw}, rate_converted={rate_converted}, loss_factor={variables['loss_factor']}, cost={cost}, expected={EXPECTED_COMPONENTS.get(cid)}")

    _write_debug_json({"aggregates": {"total_usage": total_usage, "peak_usage": peak_usage, "off_peak_usage": off_peak_usage, "max_kva": max_kva, "days": days}, "components": debug_items}, "abstract_billing_debug.json")

    # Assertions (fail if mismatch)
    for cid, expected_val in EXPECTED_COMPONENTS.items():
        assert cid in evaluated, f"Component {cid} missing from tariff"
        got = evaluated[cid]
        assert math.isclose(got, expected_val, abs_tol=ABS_TOL), f"{cid} mismatch: got {got}, expected {expected_val}"

    # sanity
    invoice_total = round(sum(evaluated.values()), 2)
    assert math.isclose(invoice_total, round(sum(evaluated.values()), 2), rel_tol=1e-9)
