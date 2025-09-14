--demo insertion scrypt data 
-- Insert a region
INSERT INTO region (name, loss_factor) VALUES ('Victoria', 0.98);

-- Insert a customer
INSERT INTO customer (name, address, region_id)
VALUES ('Demo CustomerID', '92 Chevron Street, VIC', 1);

-- Insert a tariff plan
INSERT INTO tariff_plan (name, region_id, description)
VALUES ('Shell Energy TOU', 1, 'Time of Use Tariff Plan');

-- Insert tariff version (JSONB schema)
-- Insert a comprehensive Shell Energy tariff (canonical JSON)
INSERT INTO tariff_versions (tariff_plan_id, canonical_json, version, uploaded_by, effective_from)
VALUES (
    1,
    '{
      "provider": "Shell Energy",
      "tariff_code": "SHELL-TOU-LLV-ABSTRACT",
      "version": "2024-04-01",
      "effective_from": "2024-04-01",
      "time_zones": "Australia/Melbourne",
      "time_bands": [
        {
          "id": "peak",
          "label": "Retail Peak (sample)",
          "days": ["mon","tue","wed","thu","fri"],
          "times": [{"from": "07:00", "to": "19:00"}]
        },
        {
          "id": "offpeak",
          "label": "Retail Off-Peak",
          "days": ["sat","sun","all"],
          "times": [
            {"from": "00:00", "to": "07:00"},
            {"from": "19:00", "to": "23:59"}
          ]
        }
      ],
      "meta": {
        "notes": "Abstract canonical derived from invoice-level CSV. Units kept as published (c/kWh, $/kVA/Mth, c/day, $/meter/year). Loss factors per CSV."
      },
      "components": [
        {
          "id": "VIC_Peak",
          "label": "VIC Peak (retailer energy)",
          "category": "retail_energy",
          "unit": "c/kWh",
          "applies_to": ["usage_peak"],
          "rate_schedule": [{"value": 11.5511}],
          "loss_factor": 1.06013,
          "calculation": "peak_usage * rate * loss_factor"
        },
        {
          "id": "VIC_Off_Peak",
          "label": "VIC Off Peak (retailer energy)",
          "category": "retail_energy",
          "unit": "c/kWh",
          "applies_to": ["usage_offpeak"],
          "rate_schedule": [{"value": 8.0880}],
          "loss_factor": 1.06013,
          "calculation": "off_peak_usage * rate * loss_factor"
        },
        {
          "id": "LRECs",
          "label": "LRECs",
          "category": "environment",
          "unit": "c/kWh",
          "applies_to": ["usage_total"],
          "rate_schedule": [{"value": 0.9663}],
          "loss_factor": 1.05960,
          "calculation": "total_usage * rate * loss_factor"
        },
        {
          "id": "VEECs",
          "label": "VEECs",
          "category": "environment",
          "unit": "c/kWh",
          "applies_to": ["usage_total"],
          "rate_schedule": [{"value": 1.3831}],
          "loss_factor": 1.05960,
          "calculation": "total_usage * rate * loss_factor"
        },
        {
          "id": "SRECs",
          "label": "SRECs",
          "category": "environment",
          "unit": "c/kWh",
          "applies_to": ["usage_total"],
          "rate_schedule": [{"value": 0.8451}],
          "loss_factor": 1.05960,
          "calculation": "total_usage * rate * loss_factor"
        },
        {
          "id": "LLVT2_Peak_Energy",
          "label": "Distribution Peak Energy (LLVT2)",
          "category": "network_energy",
          "unit": "c/kWh",
          "applies_to": ["network_peak"],
          "rate_schedule": [{"value": 4.09}],
          "calculation": "peak_usage * rate"
        },
        {
          "id": "LLVT2_Off_Peak_Energy",
          "label": "Distribution Off-peak Energy (LLVT2)",
          "category": "network_energy",
          "unit": "c/kWh",
          "applies_to": ["network_offpeak"],
          "rate_schedule": [{"value": 2.9}],
          "calculation": "off_peak_usage * rate"
        },
        {
          "id": "LLVT2_Peak_Demand",
          "label": "Distribution Peak Demand (LLVT2)",
          "category": "demand",
          "unit": "$/kVA/Mth",
          "applies_to": ["demand"],
          "rate_schedule": [{"value": 11.6}],
          "rolling_window": {"months": 12, "interval_minutes": 30},
          "calculation": "max_kva * rate"
        },
        {
          "id": "LLVT2_Summer_Incentive_Demand",
          "label": "Distribution Summer Incentive Demand (LLVT2)",
          "category": "incentive_demand",
          "unit": "$/kVA/Mth",
          "applies_to": ["incentive_demand"],
          "rate_schedule": [{"value": 8.77}],
          "season": {"from": "2024-12-01", "to": "2025-03-31"},
          "rolling_window": {"months": 12, "interval_minutes": 30},
          "calculation": "incentive_kva * rate"
        },
        {
          "id": "AEMO_Market_Fee_30_Days",
          "label": "AEMO Market Fee (30 days)",
          "category": "fixed",
          "unit": "c/day",
          "applies_to": ["fixed"],
          "rate_schedule": [{"value": 2.1756}],
          "calculation": "rate * days"
        },
        {
          "id": "AEMO_Ancillary_Fee_UFE",
          "label": "AEMO Ancillary Fee UFE",
          "category": "usage_total",
          "unit": "c/kWh",
          "applies_to": ["usage_total"],
          "rate_schedule": [{"value": 0.0215}],
          "loss_factor": 1.05960,
          "calculation": "total_usage * rate * loss_factor"
        },
        {
          "id": "AEMO_Market_Fee_Daily",
          "label": "AEMO Market Fee Daily (per kWh)",
          "category": "usage_total",
          "unit": "c/kWh",
          "applies_to": ["usage_total"],
          "rate_schedule": [{"value": 2.1756}],
          "loss_factor": 1.05960,
          "calculation": "total_usage * rate * loss_factor"
        },
        {
          "id": "Meter_Charge",
          "label": "Meter Charge",
          "category": "fixed",
          "unit": "$/meter/year",
          "applies_to": ["fixed"],
          "rate_schedule": [{"value": 2400.0}],
          "calculation": "rate"
        }
      ],
      "rolling_window": {
        "months": 12,
        "interval_minutes": 30
      }
    }'::jsonb,
    1,
    'admin',
    '2024-04-01'
);

-- Insert meter readings
INSERT INTO meter_reading (customer_id, timestamp, kwh_used)
VALUES (1, now() - interval '1 hour', 1.25);

-- Insert calc run with demo summary
INSERT INTO calc_runs (tariff_version_id, customer_id, status, result_summary_json)
VALUES (
    1,
    1,
    'completed',
    '{"total_cost": 42.75, "breakdown": {"supply": 10.0, "peak_usage": 32.75}}'
);