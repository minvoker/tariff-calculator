-- Drop existing tables if needed
DROP TABLE IF EXISTS invoice CASCADE;
DROP TABLE IF EXISTS calc_runs CASCADE;
DROP TABLE IF EXISTS meter_reading CASCADE;
DROP TABLE IF EXISTS market_op_fees CASCADE;
DROP TABLE IF EXISTS tariff_versions CASCADE;
DROP TABLE IF EXISTS tariff_plan CASCADE;
DROP TABLE IF EXISTS customer CASCADE;
DROP TABLE IF EXISTS region CASCADE;

-- 1. Regions

CREATE TABLE region (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    loss_factor DECIMAL(6,4) DEFAULT 1.0000
);

-- 2. Customers
CREATE TABLE customer (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT,
    region_id INT REFERENCES region(id) ON DELETE SET NULL
);

-- 3. Tariff Plans
-- (High-level grouping, e.g., "Shell Energy TOU Plan")

CREATE TABLE tariff_plan (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    region_id INT REFERENCES region(id) ON DELETE CASCADE,
    description TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- 4. Tariff Versions (JSONB storage for canonical schema)
-- Stores full uploaded tariff schema (e.g., Shell PDF parsed)

CREATE TABLE tariff_versions (
    id SERIAL PRIMARY KEY,
    tariff_plan_id INT REFERENCES tariff_plan(id) ON DELETE CASCADE,
    canonical_json JSONB NOT NULL,  
    -- stores canonical tariff_schema.json
    version INT NOT NULL DEFAULT 1,
    uploaded_by TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_at TIMESTAMP DEFAULT now()
);

-- Indexes for JSONB queries + effective date filtering
CREATE INDEX ix_tariff_versions_plan_version ON tariff_versions (tariff_plan_id, version);
CREATE INDEX ix_tariff_versions_effective ON tariff_versions (effective_from, effective_to);
CREATE INDEX ix_tariff_versions_jsonb_components ON tariff_versions USING gin (canonical_json);

-- 5. Market Operator Fees (with effective validity)

CREATE TABLE market_op_fees (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    amount DECIMAL(10,4) NOT NULL,
    unit TEXT, -- e.g., $/MWh
    effective_from DATE,
    effective_to DATE,
    source TEXT
);

CREATE INDEX ix_market_op_fees_effective ON market_op_fees (effective_from, effective_to);

-- 6. Meter Readings (time-series data from smart meters)

CREATE TABLE meter_reading (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customer(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    kwh_used DECIMAL(10,4) NOT NULL
);
-- Indexes for fast queries on time-series
CREATE INDEX ix_meter_readings_customer_ts ON meter_reading (customer_id, timestamp);

-- 7. Calculation Runs (audit + results summary)

CREATE TABLE calc_runs (
    id SERIAL PRIMARY KEY,
    tariff_version_id INT REFERENCES tariff_versions(id) ON DELETE CASCADE,
    customer_id INT REFERENCES customer(id) ON DELETE CASCADE,
    started_at TIMESTAMP DEFAULT now(),
    finished_at TIMESTAMP,
    status TEXT CHECK (status IN ('pending', 'running', 'completed', 'failed')) DEFAULT 'pending',
    result_summary_json JSONB,
    checksum TEXT
);

CREATE INDEX ix_calc_runs_status ON calc_runs (status);
CREATE INDEX ix_calc_runs_tariff_customer ON calc_runs (tariff_version_id, customer_id);

-- 8. Invoices (linked to calc_runs for traceability)

CREATE TABLE invoice (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customer(id) ON DELETE CASCADE,
    calc_run_id INT REFERENCES calc_runs(id) ON DELETE CASCADE,
    issue_date DATE NOT NULL,
    due_date DATE NOT NULL,
    total_amount DECIMAL(12,2) NOT NULL
);
