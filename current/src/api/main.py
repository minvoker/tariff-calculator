from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session
import sys, os
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from core.database import get_db
from core.services.calc import calculate_bill, upsert_calc_run
from core.services.checksum import compute_checksum


app = FastAPI(title="Calculator API")

class CalcStoreRequest(BaseModel):
    customer_id: int
    tariff_version_id: int
    start: datetime
    end: datetime
    force: Optional[bool] = False

@app.post("/calculate")
def calculate_and_store(req: CalcStoreRequest, db: Session = Depends(get_db)):
    # Compute checksum to avoid unnecessary recomputation
    checksum = compute_checksum(db, req.customer_id, req.tariff_version_id, req.start, req.end)
    result = calculate_bill(db, req.customer_id, req.tariff_version_id, req.start, req.end)
    run_id = upsert_calc_run(db, req.customer_id, req.tariff_version_id, req.start, req.end, checksum, result)
    return {"calc_run_id": run_id, **result}

@app.get("/customers/{customer_id}/bills")
def get_bill(customer_id: int, start: datetime, end: datetime, tariff_version_id: int, db: Session = Depends(get_db)):
    # Return last stored calc_run for the inputs if available
    from sqlalchemy import select
    from core.models import CalcRun
    row = db.execute(
        select(CalcRun).where(
            CalcRun.customer_id == customer_id,
            CalcRun.tariff_version_id == tariff_version_id
        ).order_by(CalcRun.id.desc())
    ).scalars().first()

    if not row or not row.result_summary_json:
        # fallback: compute & store now
        checksum = compute_checksum(db, customer_id, tariff_version_id, start, end)
        result = calculate_bill(db, customer_id, tariff_version_id, start, end)
        run_id = upsert_calc_run(db, customer_id, tariff_version_id, start, end, checksum, result)
        return {"calc_run_id": run_id, **result}

    return {"calc_run_id": row.id, **row.result_summary_json.get("result", {})}

# Finalise validate endpoint
#@app.post("/validate")
#def validate_tariff(tariff: Tariff, db: Session = Depends(get_db)):