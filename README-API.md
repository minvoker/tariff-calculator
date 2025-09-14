
# Thin API v2 (shared core, existing schema unchanged)

**What this is**
- A *thin, purposeful* FastAPI service that uses shared core models/services.
- **No schema changes**. We persist results in `calc_runs.result_summary_json`.
- Component IDs are preserved from `tariff_versions.canonical_json.components[].id`.

## Structure
- `current/src/core/database.py` – engine & session (`DATABASE_URL`)
- `current/src/core/models.py` – SQLAlchemy models *matching your existing schema*
- `current/src/core/services/` – business logic
  - `timeband.py` – matches timestamps to `time_bands`
  - `checksum.py` – hashes tariff JSON + readings + window
  - `calc.py` – `calculate_bill(...)` + `upsert_calc_run(...)`

- `current/src/api_v2/main_v2.py` – thin API
  - `POST /bills/calculate-and-store` – compute & store (idempotent via checksum); returns `{ total_cost, breakdown }`
  - `GET /customers/{id}/bills?start=&end=&tariff_version_id=` – returns last stored result or computes if missing

- `examples/portal-demo/index.html` – tiny portal page to test

## Running
```bash
export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/energy
cd current/src/api_v2
uvicorn main_v2:app --reload
# Open examples/portal-demo/index.html in a browser (serving it with any static server)
```

## Assumptions
- Your existing tables include: `region`, `customer`, `tariff_plan`, `tariff_versions (JSONB canonical_json)`, `market_op_fees`, `meter_reading`, `calc_runs (result_summary_json JSONB)`, `invoice`.
- We **do not** modify SQL schema. We store calculation results and metadata (checksum, window) in `calc_runs.result_summary_json`.
- **Effective tariff version** is supplied by the caller (we accept `tariff_version_id`). If you want the API to *resolve* the correct version by date, we can add that helper without changing schema.
- Component IDs come from `canonical_json.components[].id` and appear unchanged in the breakdown keys.
- Units/rates are read from `rate_schedule[0].value` (cents-based); extend as needed for block/seasonal rates.
- Time-of-use matching reads `canonical_json.time_bands` with `days` + `times` (`from`/`to` in `HH:MM`).

## Extending
- Add `usage_demand` (kW demand windows) or block pricing by enhancing `calc.py` only.
- Add auth/tenancy to endpoints.
- If you later want granular invoice line items, we can use `invoice` plus a new breakdown table—but **not done here** per your “no schema change” requirement.

