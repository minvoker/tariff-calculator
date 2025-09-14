import pandas as pd
from enum import Enum
import math
import calendar

class Agg(str, Enum):
    MAX = "max"
    MEAN = "mean"

############################## Resampling Stream (TZ Aware, DST-safe) ############################
# Helper: Resamples meter data into canonical 30-minute buckets.
# - Demand (kW/kVA) is resampled to a 1-minute grid with forward-fill capped at 5 minutes,
#   then aggregated via a 30-minute rolling window. No backfill is applied.
# - Timestamps are localized using ambiguous="infer" and nonexistent="shift_forward"
#   so daylight-savings transitions are handled safely.
# - Energy assumption: usage_kwh values are treated as per-interval (not cumulative) kWh readings
#   and summed into 30-minute buckets.

# Resample data into 30-minute intervals, handling timezone localisation and rolling window aggregation for power demand.
def resample_to_30min(
    df: pd.DataFrame,
    tz: str = "Australia/Melbourne",
    kw_column: str = "KW",
    usage_column: str = "usage_kwh",
    demand_agg: Agg = Agg.MAX,
    timestamp_column: str = "timestamp"
) -> pd.DataFrame:

    # Ensure the input df is a copy to avoid modifying the original
    df = df.copy()

    # Ensure the df has a datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        if timestamp_column not in df.columns:
            raise ValueError(f"Missing timestamp column: '{timestamp_column}'")
        df[timestamp_column] = pd.to_datetime(df[timestamp_column], errors='coerce')
        df.set_index(timestamp_column, inplace=True)

    # Localise or convert the index to the specified timezone
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
    else:
        df.index = df.index.tz_convert(tz)

    # Resample energy column to 30 minute intervals
    if usage_column in df.columns:
        energy_resampled = df[[usage_column]].resample("30T").sum()
    else:
        energy_resampled = pd.DataFrame()

    # Resample power column to 30 minute intervals
    if kw_column in df.columns:
        
        # Interpolate missing values in the power column
        power_1min = df[[kw_column]].resample("1T").mean().ffill(limit=5)

        # Apply rolling window aggregation
        if demand_agg == Agg.MAX:
            power_rolled = power_1min.rolling("30T", min_periods=1).max()
        elif demand_agg == Agg.MEAN:
            power_rolled = power_1min.rolling("30T", min_periods=1).mean()
        else:
            raise ValueError(f"Invalid value for demand_agg: '{demand_agg}'")

        # Resample the rolled power data to 30-minute intervals
        demand_resampled = power_rolled.resample("30T").max()
    else:
        demand_resampled = pd.DataFrame()

    # Combine the resampled energy and demand data
    combined = pd.concat([energy_resampled, demand_resampled], axis=1)

    # Drop rows where all values are NaN
    combined.dropna(how="all", inplace=True)

    return combined

############################ ## End of Resampling Stream ############################

############################ Incentive KVA Calculation ############################
# Helper: Computes incentive_kva for billing formulas.
# - Based on the rolling mean of KVA demand over a configurable window (default 30 minutes).
# - Minimal interpolation: 1-minute resample with forward-fill capped at 5 minutes.
# - Returns either the maximum value of this rolling series ("max") or its overall average ("mean")
#   across the billing period.

def get_incentive_kva(
    df: pd.DataFrame,
    window_minutes: int = 30,
    kva_column: str = "KVA",
    demand_agg: Agg = Agg.MAX
) -> float:
    
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("The data frame must have a tz-aware DatetimeIndex.")

    # Grab the KVA column and ensure it's float
    kva_series = df[kva_column].astype(float)
    
    # Resample to 1 min intervals with forward-fil capped at 5 minutes
    kva_1min = kva_series.resample("1T").mean().ffill(limit=5)

    # rolling average over the specified window
    rolling_avg = kva_1min.rolling(
        f"{window_minutes}T",
        min_periods=1,
        closed="right"
    ).mean()

    if demand_agg == Agg.MEAN:
        return float(rolling_avg.mean())
    elif demand_agg == Agg.MAX:
        return float(rolling_avg.max())
    else:
        raise ValueError(f"Unsupported demand_agg: {demand_agg}")

############################ ## End of Incentive KVA Calculation ###########################