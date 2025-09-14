"""
Utility script to bulk‑insert meter readings from a CSV into the database.

This script reads a CSV file containing meter readings and writes the values
into the `meter_reading` table for a specified customer.  It attempts to
automatically detect the timestamp and consumption columns but allows for
explicit specification via command‑line flags.  Example usage:

    python load_sample_meter_data.py --csv-path "./Sample Meter Data.csv" \
        --db-url "postgresql://postgres:postgres@localhost:5432/energy" \
        --customer-id 1

By default the script looks for columns containing the words "date",
"time" or "timestamp" for the timestamp and "kwh", "kw" or "usage" for
the consumption value.  If these heuristics are insufficient, supply
--timestamp-col and --usage-col explicitly.

This script is intended to be run manually after the database has been
initialised; it does not form part of the automatic docker initdb process.
"""

import argparse
import os
import sys
from typing import Tuple

import pandas as pd
import psycopg2


import re


def _normalize(col: str) -> str:
    """
    Normalize a column name by converting to lowercase and stripping all
    non‑alphanumeric characters.  This allows for fuzzy matching against
    column names like ``E (Usage kWh)``.
    """
    return re.sub(r"[^a-z0-9]", "", col.lower())


def guess_columns(df: pd.DataFrame) -> Tuple[str, str]:
    """Attempt to guess the timestamp and usage columns from a DataFrame.

    Timestamp columns are those whose normalized name contains ``date``,
    ``time`` or ``timestamp``.  Usage columns are those whose normalized name
    contains ``kwh``, ``kw`` or ``usage``.  Returns a tuple of the original
    column names (timestamp_col, usage_col).

    Raises a ValueError if no suitable columns are found.
    """
    normalized = {col: _normalize(col) for col in df.columns}
    ts_candidates = [
        col
        for col, norm in normalized.items()
        if any(term in norm for term in ("date", "time", "timestamp"))
    ]
    usage_candidates = [
        col
        for col, norm in normalized.items()
        if any(term in norm for term in ("kwh", "kw", "usage"))
    ]
    if not ts_candidates:
        raise ValueError(
            "Unable to infer timestamp column; please provide --timestamp-col"
        )
    if not usage_candidates:
        raise ValueError(
            "Unable to infer usage column; please provide --usage-col"
        )
    return ts_candidates[0], usage_candidates[0]


def insert_meter_readings(
    csv_path: str,
    db_url: str,
    customer_id: int,
    timestamp_col: str | None = None,
    usage_col: str | None = None,
):
    """Read a CSV and insert its readings into the meter_reading table.

    :param csv_path: path to the CSV file containing meter data
    :param db_url: PostgreSQL connection string
    :param customer_id: ID of the customer to associate readings with
    :param timestamp_col: optional name of the timestamp column
    :param usage_col: optional name of the kWh usage column
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Read the CSV; let pandas infer datatypes
    df = pd.read_csv(csv_path)

    # Identify columns.  If the user supplied explicit names, attempt to match
    # them in a case‑insensitive manner by normalising both the input and
    # dataframe column names.  This allows specifying "E (Usage Kwh)" when
    # the actual column name is "E (Usage kWh)".
    normalized_map = {col: _normalize(col) for col in df.columns}
    if timestamp_col:
        norm_ts = _normalize(timestamp_col)
        matches = [col for col, norm in normalized_map.items() if norm == norm_ts]
        if not matches:
            raise KeyError(
                f"Timestamp column '{timestamp_col}' not found in CSV. Available columns: {list(df.columns)}"
            )
        timestamp_col = matches[0]
    if usage_col:
        norm_usg = _normalize(usage_col)
        matches = [col for col, norm in normalized_map.items() if norm == norm_usg]
        if not matches:
            raise KeyError(
                f"Usage column '{usage_col}' not found in CSV. Available columns: {list(df.columns)}"
            )
        usage_col = matches[0]
    # If either column is still unset, attempt to guess
    if timestamp_col is None or usage_col is None:
        auto_ts_col, auto_usage_col = guess_columns(df)
        timestamp_col = timestamp_col or auto_ts_col
        usage_col = usage_col or auto_usage_col

    # Convert timestamp column to datetime
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors="coerce")
    # Drop any rows with invalid timestamps
    df = df.dropna(subset=[timestamp_col])
    # Ensure usage column is numeric
    df[usage_col] = pd.to_numeric(df[usage_col], errors="coerce")
    df = df.dropna(subset=[usage_col])

    # Prepare values for insertion
    records = list(
        zip([
            customer_id
        ] * len(df), df[timestamp_col].tolist(), df[usage_col].astype(float).tolist())
    )
    if not records:
        print("No valid meter readings found to insert.")
        return

    # Connect and insert
    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO meter_reading (customer_id, timestamp, kwh_used) VALUES (%s, %s, %s)",
                    records,
                )
        print(f"Inserted {len(records)} meter readings for customer_id={customer_id}.")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Load meter data from a CSV into the meter_reading table"
    )
    parser.add_argument(
        "--csv-path",
        default=os.environ.get(
            "METER_CSV_PATH",
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "./",
                "Sample Meter Data.csv",
            ),
        ),
        help=(
            "Path to the CSV file containing meter data. If not supplied, the"
            " script will look for an environment variable METER_CSV_PATH or"
            " default to ../current/data/Sample Meter Data.csv relative to this script."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/energy",
        ),
        help=(
            "Database connection string (default reads DATABASE_URL environment"
            " variable or falls back to a local Postgres instance)"
        ),
    )
    parser.add_argument(
        "--customer-id",
        type=int,
        default=1,
        help="Customer ID to associate readings with (default: 1)",
    )
    parser.add_argument(
        "--timestamp-col",
        dest="timestamp_col",
        help="Explicit name of the timestamp column in the CSV",
    )
    parser.add_argument(
        "--usage-col",
        dest="usage_col",
        help="Explicit name of the usage (kWh) column in the CSV",
    )

    args = parser.parse_args(argv)
    insert_meter_readings(
        csv_path=args.csv_path,
        db_url=args.db_url,
        customer_id=args.customer_id,
        timestamp_col=args.timestamp_col,
        usage_col=args.usage_col,
    )


if __name__ == "__main__":
    main()