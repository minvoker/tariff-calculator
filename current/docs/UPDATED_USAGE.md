### SETUP
- Setup venv if needed
- `pip install -r requirements.txt`
- `cd src/database`
- `docker-compose up -d`
- `python3 03-insert_meter_readings.py`
- `cd src/api` (using another terminal is preferred here)
- `uvicorn main:app --reload`

### USAGE
- `cd src`
- `python3 system.py --start 2023-08-01 --end 2023-08-01`

### DEBUGGING
- `curl http://localhost:8000/customers | jq` (check link)
- `docker ps`
- `docker exec -it energy_db psql -U postgres -d energy_database` (SQL)
  - SELECT * FROM [table name];

### FLOW 
1. SETUP
a. Environment & Dependencies

requirements.txt: Lists all Python dependencies (FastAPI, SQLAlchemy, pandas, etc).
venv: (Virtual environment, not a file) Isolated Python environment for dependencies.
b. Database Initialization

docker-compose.yml:
Spins up a PostgreSQL database container.
Loads schema and initial data from schemaDB.sql and 01-shell-data.sql.
schemaDB.sql & 01-shell-data.sql:
Define all tables and insert initial region, customer, tariff, and unit data.
c. Meter Data Ingestion

03-insert_meter_readings.py:
Loads meter readings from Excel (Sample Meter Data.xlsx) and inserts them into the meter_readings table in the database.

2. API SERVER
a. API Models & Schemas

db_models.py:
SQLAlchemy ORM models for all tables.
schemas.py:
Pydantic models for API request/response validation.
b. API Endpoints

main.py:
FastAPI app with endpoints for CRUD on customers, meter readings, tariffs, invoices, etc.
Handles all data access for the calculation system.
c. Database Connection

database.py:
Sets up SQLAlchemy engine and session for API.

3. USAGE: Calculation System
a. Main Calculation Script

system.py:
Main logic for loading config, fetching data from API, calculating charges, and saving invoices.
Calls API endpoints to get meter readings, tariffs, formulas, etc.
Prompts user for network peak/off-peak usage if needed.
Saves results to the database via API.
b. CLI Handler (Optional)

cli_handler.py:
(If used) Handles CLI prompts for file paths, dates, provider/plan selection.
c. Test Script

test_script.py:
Example/test usage of EnergyBillingSystem for a given period.

4. DEBUGGING
a. Logs

energy_billing.log:
Detailed log of calculation steps, variable values, and results.
b. Database Inspection

Use docker exec -it energy_db psql -U postgres -d energy_database to:
Inspect tables (SELECT * FROM ...;)
Check meter readings, invoices, etc.
c. API Testing

Use curl or browser to hit endpoints (e.g., /customers, /meter_readings).
Swagger UI at http://localhost:8000/docs for interactive API testing.

5. DATA FILES
data/Sample Meter Data.xlsx or .csv:
Raw meter data for ingestion.
tariffs_shell.csv:
Tariff component rates and units.