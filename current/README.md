# Canonical Tariff JSON & Schema Cheatsheet
## Overview
- **Schema**(`docs/tariff_schema.json`) defines the *shape* every canonical tariff JSON needs to follow, helping the system validate that a tariff file contains required fields in the expected types (time bands, components, units, rate schedules, etc.)
- **Canonical tariff JSON** (`tariffs/shell-2024-04-01.json`) is the *contract* ingested by the system
    1. Resamples meter data to 30-min buckets (helper function by Jackson)
    2. Assigns time-band labels (helper function by Jackson)
    3. Computes aggregate variables like *peak, total, max kva*
    4. Converts rates to numeric $/units
    5. Evaluates each component's `calculation` expression using safe AST evaluator (security by Madara)
    6. Returns and persists the invoice
## File Locations (Repo convention)
- Schema: `docs/tariff_schema.json`
- Canonical tariffs: `tariffs/{provider}-{code}-{version}.json`
- Translation notes (if any): `docs/translation_notes/{provider}.md`
- Test: `tests/test_abstract_billing_from_csv.py`
## Variable Context for `calculation`
The engine supplies these variables when evaluating `calculation` strings:
- `total_usage`: total kWh in billing period (float)
- `peak_usage`: kWh labelled `peak` by time bands (float)
- `off_peak_usage`: kWh not in `peak` (float) or use `shoulder_usage` if explicitly defined
- `max_kva`: maximum kva (30-min bucket basis) for the period (float)
- `incentive_kva`: rolling or incentive-specific demand (float)
- `rate`: numeric $ per unit (converted & prorated by system) used in formula
- `loss_factor`: multiplier (default 1.0 if missing)
- `days`: integer number of days in billing period
- `billing_period_start`,` billing_period_end` — date strings (YYYY-MM-DD)
Allowed functions in expressions: `min`, `max`, `round`, `math.*` (whitelisted). No `eval()`; AST whitelist only
## Schema Breakdown
- `provider`: name (for UI/logs)
- `tariff_code`: canonical identifier for lookup
- `version`: version string for reproducibility/audit
- `effective_from` / `effective_to`: date validity window
- `time_zones`: tz database name (for band assignment and DST)
- `meta`: free-text notes (source, assumptions, GST handling)
- `time_band`: array of band objects: `{id, label, days, times, date_ranges(optional)}`. Used to label 30-min buckets
- `components`: array of charge definitions; each component must include:
    - `id`: unique key used in invoice lines and DB lookups
    - `label`: human readables
    - `category`: one of `retail_energy`, `network_energy`, `demand`, `environment`, `fixed`, `ancillary` (use this controlled vocab for clarification)
    - `unit`: published string unit like `c/kWh`, `$/kVA/Mth`, `c/day`, engine parses & converts
    - `applies_to`: arrau pf semantic tokens like `usage_peak`, `demand`, `usage_total` for filtering/reporting
    - `rate_schedule`: array of `{from?, to?, value}` for single or tiered rates
    - `loss_factor`: optional multiplier
    - `season`: optional `{from, to}` dates (component applies only in season)
    - `rolling_window`: optional `{months, interval_minutes}` for demand-rolling logic
    - `calculation`: required string expression returning $ cost (system evaluates)
    - `notes`: optional notes
PS: `applies_to` = semantic tag for filtering, UI grouping, compatibility; `calculation` = executable formula (how to compute cost). Keep both: one helps humans & tooling, the other is canonical computation
## Example
```
{
  "id":"VIC_Peak",
  "label":"VIC Peak (retailer energy)",
  "category":"retail_energy",
  "unit":"c/kWh",
  "applies_to":["usage_peak"],
  "rate_schedule":[{"value":11.5511}],
  "loss_factor":1.06013,
  "calculation":"peak_usage * rate * loss_factor"
}
```
1. Determine `peak_usage` by summing resampled 30-min buckets labelled `peak`
2. Convert `11.5511 c/kWh` to `0.115511 $/kWh`
3. Multiply: `peak_usage * 0.115511 * 1.06013`, line cost
4. Round as per policy
## How to create a tariff (Practical checklist)
Use this for human translation work. Put final data into `tariffs/<file>.json`.
1. **Scan PDF & identify invoice lines**
   - Make two-column extraction: `component name`/`published rate + unit + notes (hours, seasons)`
   - Common items:  supply charge (c/day), energy tariffs by band (c/kWh), demand charges ($/kVA/Mth), environmental (c/kWh), AEMO fees (c/kWh or c/day), meter charges ($/year)
2. **Define Time Bands**
   - From text like "Peak 3pm-9pm weekdays", you create a `time_bands` entry: `id: "peak"`, `days:["mon","tue","wed","thu","fri"]`, `times:[{"from":"15:00", "to":"21:00"}]`
3. **Map each published line to a `component`**
   - Choose `id` = short stable key (no spaces, uppercase underscores)
   - `label` = verbatim human string
   - `category` = pick from canonical set (`retail_energy`, `network_energy`, `demand`, `fixed`, `environment`, `ancillary`)
   - `unit` = keep published unit EXACT (system will parse)
   - `applies_to` = add semantic tag(s) (`usage_peak` / `usage_offpeak` / `usage_total` / `demand` / `fixed` etc.)
   - `rate_schedule` = one entry with `value` if flat; add `from`/`to` for tiers
   - If seasonal, set `season`. If demand-based requiring history, add `rolling_window`
   - Formulate `calculation` string using allowed variable names
4. **Special cases**
   - Controlled loads: treat as separate component with `applies_to: ["usage_controlled"]`. If separate meter exists, system will use that meter's readings
   - Per-day items (`c/day`): `calculation` usually `"rate*days"`
   - Meter/year items (`$/meter/year`): convert to prorated value for billing days (system handles proration). Use `calculation` `"rate"` if rate already prorated by system before evaluation, or `"rate"` after system conversion, decide one consistent approach
5. **Validation**
   - Run `jsonschema.validate(tariff, docs/tariff_schema.json)`. Fix any errors
6. **Test in harness**
   - Use `tests/test_abstract_billing_from_csv.py` or equivalent to run the sample meter file and compare expected component values
## All Possible or Common Components (Non-exhaustive)
Use these tokens for `category` or `applies_to`. Add to schema if extending them
**Categories (1)**
`retail_energy`, `network_energy`, `demand`, `fixed`, `environment`, `ancillary`, `supply`, `metering`, `incentive`
**applies_to tokens (common)**
`usage_peak`, `usage_offpeak`, `usage_shoulder`, `usage_total`, `usage_controlled`, `demand`, `network_peak`, `network_offpeak`, `fixed`, `meter`, `ancillary`, `environmental`
**Potential Extra Components**
- Time-of-use export (for feed-in tariffs) — `category: retail_energy`, `applies_to: ["export"]`
- Bandwidth/connection fees (e.g., $/kW connection charge) — `category: fixed` or custom `network_connection`
- Reactive energy penalties — `category: ancillary` with `calculation` referencing reactive energy metric if available
- Solar FIT / export credits — `category: retail_energy`, negative `calculation` allowed if engine supports credits. (Be cautious — business logic for negative lines should be explicit.)
## Tips when translation PDFs
- **Capture exact words** for `label` and `notes`, auditors rely on fidelity
- **Confirm units**, some documents show `c` but actually mean `$` (rare). If uncertain, record assumption in `meta` or `translation_notes`
- **Prefer `rate_schedule` for tiering**, do not encode tiers inside `calculation`
- **Keep `calculation` simple**, prefer arithmetic only; avoid conditional/time checks in `calculation` (use `season`/`time_bands` instead)
- **Record assumtions** like timezone, GST inclusion/exclusion, etc. Put in `meta` or `docs/translation_notes`
- **Test with small sample meter data** that exercises peak/shoulder/offpeak and demand windows
- **If uncertain about demand windows** like “recorded monthly maximum demand between 3pm–9pm working weekdays”, model the time-band restriction in either `time_bands` or in `calculation` (preferred: time-band + `rolling_window`)
## Schema Maintenance
**When to change the schema**
- New provider introduces a new primitive not covered before (e.g., `export_credit` needs `units: c/kWh_export`)
- New requirement for `components` needs an extra property like `eligibility` contraints, min_kva_
- If recommended field needs to be changed into required
**How to Change**
1. Add non-breaking fields first: add new optional properties for components/time_bands, update schema version (bump meta `schema_version` inside file or use date-based name)
2. Doc change in `docs/schema_change_log.md` with reason and migration instructions
3. Update validators and tests: add unit test that rejects old invalid forms and accepts new structure
4. Migration for stored tariffs: provide script to migrate existing tariff JSONs if necessary like adding default values. Keep backwards-compatible loader that handles older tariffs if immediate migration not admissible
5. If requiring a field, like breaking the change, plan one sprint to
   - add schema change but keep validator in permissive mode
   - migrate existing tariffs
   - flip validator to strict mode in next release (push)
   - communicate change to the team
Example scenario: add min_kva to components to enforce a minimum charge for demand components. Steps:
- Add optional min_kva to schema and engine fetch logic (tolerant)
- Update `translation_notes` & sample tariffs.
- Add test asserting that if`min_kva` present engine applies max(max_kva, min_kva) in demand calculation
- After validation & migration, mark `min_kva` required if you later decide it must exist for all demand tariffs.
## Checklist before committing
- [] `jsonschema.validate()` passes
- [] `time_bands` cover all published band definitions (and seasons if present)
- [] All `components` have *id*, *label*, *category*, *unit*, *rate_schedule*, *calculation*
- [] *calculation* uses only allowed variables and functions
- [] *translation_notes* created with assumptions (timezone, GST, proration)
- [] Run harness vs. representative meter sample and compare key lines to expected numbers
- [] `tariff_code` and `version` follow naming conventions and are unique
## Do / Don't
- Do include both `applies_to` and `calculation`
- Do keep `calculation` simple (math only)
- Do convert published units to normalised $/unit in engine, not in `calculation`
- Don't use arbitrary code in `calculation`. No loops, no attribute access, no function calls except whitelisted
- Don't hardcode dates inside `calculation`, use `season` and `time_bands`