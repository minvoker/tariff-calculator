from sqlalchemy import (
    Column, Integer, String, Float, Numeric, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSON

Base = declarative_base()

class Region(Base):
    __tablename__ = 'regions'
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True)
    retail_peak_start = Column(Integer)  # Start hour of retail peak
    retail_peak_end = Column(Integer)    # End hour of retail peak
    network_peak_hours = Column(JSON)    # List of network peak hours
    loss_factor = Column(Float)          # Loss factor for the region
    summer_months = Column(JSON)         # List of summer months
    tariff_plans = relationship('TariffPlan', back_populates='region')


class Provider(Base):
    __tablename__ = 'providers'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    region_id = Column(Integer, ForeignKey('regions.id'), nullable=False)

    region = relationship("Region", back_populates="providers")
    tariff_plans = relationship("TariffPlan", back_populates="provider")


class TariffPlan(Base):
    __tablename__ = 'tariff_plans'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    provider_id = Column(Integer, ForeignKey('providers.id'), nullable=False)
    region_id = Column(Integer, ForeignKey('regions.id'), nullable=False)
    provider = relationship("Provider", back_populates="tariff_plans")
    tariff_components = relationship("TariffComponent", back_populates="tariff_plan")


class TariffComponent(Base):
    __tablename__ = 'tariff_components'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    rate = Column(Numeric(12, 6), nullable=False)
    charge_type = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    tariff_plan_id = Column(Integer, ForeignKey('tariff_plans.id'), nullable=False)

    tariff_plan = relationship("TariffPlan", back_populates="tariff_components")

# -------------------------------
# New Tables from config.yaml
# -------------------------------

class UnitDefinition(Base):
    __tablename__ = 'unit_definitions'
    id              = Column(Integer, primary_key=True)
    unit            = Column(String(20), unique=True, nullable=False)
    conversion_type = Column(String(20), nullable=False)
    factor          = Column(Numeric(12,6), nullable=False, default=1.0)
    factor_function = Column(String(50))


class Formula(Base):
    __tablename__ = 'formulas'
    id          = Column(Integer, primary_key=True)
    charge_type = Column(String(20), unique=True, nullable=False)
    expression  = Column(Text, nullable=False)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# This is your actual database URL (change if needed)
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/energy_database"

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

