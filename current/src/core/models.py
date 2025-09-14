from sqlalchemy import Column, Integer, Text, Date, DateTime, Numeric, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

class Region(Base):
    __tablename__ = "region"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    loss_factor = Column(Numeric(6,4))

    customers = relationship("Customer", back_populates="region")
    tariff_plans = relationship("TariffPlan", back_populates="region")

class Customer(Base):
    __tablename__ = "customer"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    address = Column(Text)
    region_id = Column(Integer, ForeignKey("region.id", ondelete="SET NULL"))

    region = relationship("Region", back_populates="customers")
    meter_readings = relationship("MeterReading", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")
    calc_runs = relationship("CalcRun", back_populates="customer")

class TariffPlan(Base):
    __tablename__ = "tariff_plan"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    region_id = Column(Integer, ForeignKey("region.id", ondelete="CASCADE"))
    description = Column(Text)
    created_at = Column(DateTime)

    region = relationship("Region", back_populates="tariff_plans")
    versions = relationship("TariffVersion", back_populates="plan")

class TariffVersion(Base):
    __tablename__ = "tariff_versions"
    id = Column(Integer, primary_key=True)
    tariff_plan_id = Column(Integer, ForeignKey("tariff_plan.id", ondelete="CASCADE"), nullable=False)
    canonical_json = Column(JSONB, nullable=False)
    version = Column(Integer, nullable=False)
    uploaded_by = Column(Text, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    created_at = Column(DateTime)

    plan = relationship("TariffPlan", back_populates="versions")
    calc_runs = relationship("CalcRun", back_populates="tariff_version")

class MarketOpFee(Base):
    __tablename__ = "market_op_fees"
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    amount = Column(Numeric(10,4), nullable=False)
    unit = Column(Text)
    effective_from = Column(Date)
    effective_to = Column(Date)
    source = Column(Text)

class MeterReading(Base):
    __tablename__ = "meter_reading"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    kwh_used = Column(Numeric(10,4), nullable=False)

    customer = relationship("Customer", back_populates="meter_readings")

class CalcRun(Base):
    __tablename__ = "calc_runs"
    id = Column(Integer, primary_key=True)
    tariff_version_id = Column(Integer, ForeignKey("tariff_versions.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    status = Column(Text)
    result_summary_json = Column(JSONB)  # will store breakdown and checksum

    tariff_version = relationship("TariffVersion", back_populates="calc_runs")
    customer = relationship("Customer", back_populates="calc_runs")

class Invoice(Base):
    __tablename__ = "invoice"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"), nullable=False)
    calc_run_id = Column(Integer, ForeignKey("calc_runs.id", ondelete="CASCADE"), nullable=False)
    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Numeric(12,2), nullable=False)

    customer = relationship("Customer", back_populates="invoices")
