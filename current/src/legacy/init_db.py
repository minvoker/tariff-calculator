# Updated to handle new YAML structure
import os
import sys
from glob import glob
import pandas as pd
import yaml
import logging
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from api.db_models import (
    Base, Region, Provider, TariffPlan, TariffComponent,
    UnitDefinition, Formula
)
from api.database import engine, Session

def reset_database():
    """Force drop all tables using CASCADE, then recreate them."""
    from sqlalchemy import text
    with engine.connect() as conn:
        with conn.begin():  # Begin a transaction block
            conn.execute(text("DROP SCHEMA public CASCADE;"))
            conn.execute(text("CREATE SCHEMA public;"))

    print("✔️ All tables dropped with CASCADE. Recreating...")
    Base.metadata.create_all(engine)

def load_configs(session):
    config_path = os.path.join(os.path.dirname(__file__), "../config/config.yaml")
    with open(os.path.abspath(config_path)) as f:
        config = yaml.safe_load(f)
        
        # Load Regions
        for region_name, region_data in config['regions'].items():
            region = session.query(Region).filter_by(name=region_name).first()
            if not region:
                region = Region(
                    name=region_name,
                    retail_peak_start=region_data['retail_peak_start'],
                    retail_peak_end=region_data['retail_peak_end'],
                    network_peak_hours=region_data['network_peak_hours'],
                    loss_factor=region_data['loss_factor'],
                    summer_months=region_data['summer_months']
                )
                session.add(region)
        
        # Load Providers and Tariff Plans
        for provider_data in config['providers']:
            provider = session.query(Provider).filter_by(name=provider_data['name']).first()
            if not provider:
                provider = Provider(name=provider_data['name'], type=provider_data['type'])
                session.add(provider)
        
        for plan_data in config['tariff_plans']:
            provider = session.query(Provider).filter_by(name=plan_data['provider']).first()
            region = session.query(Region).filter_by(name=plan_data['region']).first()
            
            # Check if the plan already exists
            plan = session.query(TariffPlan).filter_by(name=plan_data['name'], provider=provider, region=region).first()
            if not plan:
                plan = TariffPlan(
                    name=plan_data['name'],
                    provider=provider,
                    region=region
                )
                session.add(plan)
                session.commit()  # Commit the plan before adding components
            
            # Load components from CSV
            df = pd.read_csv(plan_data['components_path'])
            for _, row in df.iterrows():
                logging.info(f"Adding component: {row['Component']} to plan: {plan.name}")
                component = session.query(TariffComponent).filter_by(name=row['Component']).first()
                loss_factor = row.get('LossFactor', 1.0)
                if pd.isna(loss_factor):
                    loss_factor = 1.0
                if not component:
                    component = TariffComponent(
                        name=row['Component'],
                        rate=row['Rate'],
                        unit=row['Unit'],
                        charge_type=row['ChargeType'],
                        loss_factor=loss_factor,
                        tariff_plan=plan
                    )
                    session.add(component)
                else:
                    logging.warning(f"Component {row['Component']} already exists in the database.")
        
        # Load Units and Formulas
        for unit, defn in config['unit_definitions'].items():
            if not session.query(UnitDefinition).filter_by(unit=unit).first():
                session.add(UnitDefinition(
                    unit=unit,
                    conversion_type=defn['conversion_type'],
                    factor=defn.get('factor', 1.0),
                    factor_function=defn.get('factor_function')
                ))
                
        for charge_type, expr in config['charge_formulas'].items():
            if not session.query(Formula).filter_by(charge_type=charge_type).first():
                session.add(Formula(
                    charge_type=charge_type,
                    expression=expr
                ))
        

        session.commit()

if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv  # Check if the reset flag is passed
    session = Session()
    
    if reset_flag:
        reset_database()  # Drop and recreate all tables
    
    load_configs(session)