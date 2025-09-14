import hashlib
from sqlalchemy import select
from ..models import MeterReading, TariffVersion

def compute_checksum(db, customer_id: int, tariff_version_id: int, start, end) -> str:
    tv = db.get(TariffVersion, tariff_version_id)
    h = hashlib.sha256()
    h.update(str(tariff_version_id).encode())
    if tv and tv.canonical_json:
        h.update(repr(tv.canonical_json).encode())
    rows = db.execute(
        select(MeterReading.timestamp, MeterReading.kwh_used)
        .where(MeterReading.customer_id == customer_id,
               MeterReading.timestamp >= start,
               MeterReading.timestamp < end)
        .order_by(MeterReading.timestamp.asc())
    ).all()
    for ts, kwh in rows:
        h.update(str(ts).encode()); h.update(str(kwh).encode())
    h.update(str(start).encode()); h.update(str(end).encode())
    return h.hexdigest()
