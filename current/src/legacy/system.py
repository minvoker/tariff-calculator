"""
Energy Billing System
This script calculates energy charges based on usage data and tariff information.
It includes functionalities for loading configuration, processing invoices, and saving results.
Integrates with a database for storing tariff plans, units, and formulas.
Required files: usage data (Excel), tariff data (CSV), and configuration (YAML).

Modified date: 2025-06-7
Version: 3.0 (API Integration)
"""
import pandas as pd
import yaml
import calendar
import logging
import argparse
import requests
from datetime import date, datetime
from typing import Dict

logging.basicConfig(
    filename='../docs/energy_billing.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BASE_URL = "http://localhost:8000"
PEAK_HOURS = range(17, 22)  # hardcoded as not in DB

class EnergyBillingSystem:
    def __init__(self, customer_id: int):
        self.customer_id = customer_id
        self.plan = None
        self.region = None
        self.unit_defs = {}
        self.formulas = {}

    def load_config(self):
        # Get customer
        customers = requests.get(f"{BASE_URL}/customers").json()
        customer = next((c for c in customers if c['id'] == self.customer_id), None)
        logging.info(f"Loading config for customer ID: {self.customer_id}")
        if not customer:
            raise ValueError(f"Customer ID {self.customer_id} not found in API data.")


        # Get region from DB
        self.region = requests.get(f"{BASE_URL}/regions/1").json()

        if 'summer_months' in self.region and isinstance(self.region['summer_months'], str):
            import ast
            try:
                self.region['summer_months'] = ast.literal_eval(self.region['summer_months'])
            except Exception:
                self.region['summer_months'] = [12, 1, 2]
        elif 'summer_months' not in self.region:
            self.region['summer_months'] = [12, 1, 2]  # Default to Dec, Jan, Feb

        # --- REMOVE YAML loading for units/formulas ---
        # with open("../docs/config.yaml", "r") as f:
        #     config = yaml.safe_load(f)
        # yaml_region_data = config.get("regions", {}).get(self.region['region_name'])
        # if yaml_region_data:
        #     self.region.update(yaml_region_data)
        # self.formulas = config.get("charge_formulas", {})
        # self.unit_defs = config.get("unit_definitions", {})

        # --- Instead, fetch from API ---
        self.unit_defs = {u['unit']: u for u in requests.get(f"{BASE_URL}/unit_definitions").json()}
        self.formulas = {f['charge_type']: f['expression'] for f in requests.get(f"{BASE_URL}/formulas").json()}

        # Get tariff components
        self.plan = {"id": 0}
        self.plan["components"] = requests.get(
            f"{BASE_URL}/tariff_components",
            params={"region_id": self.region["region_id"]}
        ).json()

    def _is_leap_year(self, y: int):
        return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)

    def _convert_units(self, value: float, unit: str, start_date: date, end_date: date) -> float:
        logging.info(f"Converting units: {unit}")
        converted = float(value)
        unit_parts = unit.split('/')
        days_in_range = (end_date - start_date).days + 1  # inclusive

        # For proration
        days_in_month = calendar.monthrange(start_date.year, start_date.month)[1]
        days_in_year = 366 if self._is_leap_year(start_date.year) else 365

        for part in unit_parts:
            part = part.strip()
            defn = self.unit_defs.get(part)
            if not defn:
                raise ValueError(f"Undefined unit: {part}")
            logging.info(f"Conversion: {converted} * {defn['factor']} (type: {defn['conversion_type']})")
            if defn['conversion_type'] == 'static':
                converted *= defn['factor']
            elif defn['conversion_type'] == 'dynamic':
                if defn['factor_function'] == 'days_in_month':
                    converted *= (days_in_range / days_in_month)
                elif defn['factor_function'] == 'days_in_year':
                    converted *= (days_in_range / days_in_year)

        # Prorate for common period-based units
        if unit in ['$/meter/year', '$/year']:
            converted *= (days_in_range / days_in_year)
        elif unit in ['$/meter/month', '$/month', '$/kVA/Mth']:
            converted *= (days_in_range / days_in_month)
        elif unit in ['c/day', '$/day']:
            converted *= days_in_range

        return converted
    

    def prompt_network_peak_usage(self, retail_peak, retail_offpeak):
        try:
            net_peak = input(f"Enter NETWORK peak usage (kWh) for the period (default={retail_peak:.2f}): ")
            net_offpeak = input(f"Enter NETWORK off-peak usage (kWh) for the period (default={retail_offpeak:.2f}): ")
            net_peak = float(net_peak) if net_peak.strip() else retail_peak
            net_offpeak = float(net_offpeak) if net_offpeak.strip() else retail_offpeak
        except Exception:
            net_peak, net_offpeak = retail_peak, retail_offpeak
        return net_peak, net_offpeak

    def fetch_usage_data(self, start: date, end: date) -> pd.DataFrame:
        res = requests.get(f"{BASE_URL}/meter_readings", params={
            "customer_id": self.customer_id,
            "start": str(start),
            "end": str(end)
        })
        data = res.json()
        print("API response type:", type(data))
        if isinstance(data, dict):
            # Dict of lists (incorrect for this API)
            df = pd.DataFrame.from_dict(data)
            df = df.transpose()
        else:
            # List of dicts (correct)
            df = pd.DataFrame(data)
        print(df.shape)
        print(df.head())
        print(df['usage_kwh'].sum())
        if df.empty:
            raise ValueError("No usage data in given period")
        df['ReadingDateTime'] = pd.to_datetime(df['timestamp'])
        return df
    def _get_peak_usage(self, df: pd.DataFrame) -> float:
        return df[df['ReadingDateTime'].dt.hour.isin(PEAK_HOURS)]['usage_kwh'].sum()

    def get_incentive_kva(df: pd.DataFrame, window_minutes=30) -> float:
        # ensure timestamp index
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index('timestamp')
        # compute rolling-average demand over window (assumes 'kva' is instantaneous or interval average)
        window = f'{window_minutes}T'
        # resample to 1-minute (or your smallest interval) then rolling average:
        demand = df['kva'] \
            .resample('1T').interpolate() \
            .rolling(window=window, min_periods=1).mean()
        return demand.max()


    def calculate_charges(self, df: pd.DataFrame, start: date, end: date) -> Dict[str, float]:
        df['usage_kwh'] = df['usage_kwh'].astype(float)
        total_usage = df['usage_kwh'].sum()
        max_kva = df['kva'].max() if 'kva' in df.columns else 0
        days = (end - start).days + 1
        charges = {}

        incentive_kva = None
        if 'incentive_kva' in df.columns:
            incentive_kva = self.get_incentive_kva(df, window_minutes=30)
        if incentive_kva is None or pd.isna(incentive_kva):
            incentive_kva = max_kva
        
        retail_peak_usage = self._get_peak_usage(df)
        retail_offpeak_usage = total_usage - retail_peak_usage

        # Prompt user for network peak/off-peak usage
        network_peak_usage, network_offpeak_usage = self.prompt_network_peak_usage(retail_peak_usage, retail_offpeak_usage)
        # Debug: Log overall period stats
        logging.info(f"Calculation period: {start} to {end} ({days} days)")
        logging.info(f"Total usage_kwh: {total_usage}")
        logging.info(f"Max KVA: {max_kva}")
        logging.info(f"Incentive KVA: {incentive_kva}")

        for comp in self.plan['components']:
            logging.info(f"--- Calculating component: {comp['category_name']} (unit_type: {comp['unit_type']}) ---")
            charge_type = comp.get('charge_type', comp['unit_type'])
            formula = self.formulas.get(charge_type.lower())
            logging.info(f"Formula used: {formula}")
            if "summer" in comp['category_name'].lower() and start.month not in self.region['summer_months']:
                logging.info("Skipped (not in summer months)")
                continue

            try:
                rate = self._convert_units(comp['rate_per_unit'], comp['unit'], start, end)
                logging.info(f"Converted rate for {comp['unit']}: {rate}")
            except Exception as e:
                logging.warning(f"Unit conversion failed for {comp['category_name']}: {e}")
                continue

            variables = {
                'total_usage': total_usage,
                'peak_usage': retail_peak_usage,
                'off_peak_usage': retail_offpeak_usage,
                'max_kva': max_kva,
                'incentive_kva': incentive_kva,
                'rate': rate,
                'loss_factor': comp['loss_factor'] or self.region['loss_factor'],
                'days': days
            }
            if comp['unit_type'] in ['network_peak']:
                variables['peak_usage'] = network_peak_usage
            if comp['unit_type'] in ['network_offpeak']:
                variables['off_peak_usage'] = network_offpeak_usage
                    # Log variables used in formula
            logging.info(f"Variables for formula: {variables}")

            if not formula:
                logging.warning(f"No formula found for {charge_type}")
                continue
            try:
                result = eval(formula, {}, variables)
                charges[comp['category_name']] = round(result, 2)
                logging.info(f"Result for {comp['category_name']}: {result} (rounded: {charges[comp['category_name']]})")
            except Exception as e:
                logging.warning(f"Error in {comp['category_name']}: {e}")

        logging.info(f"Final charges for {comp['category_name']}: {charges}")
        return charges
    
    def calculate_from_api(self, api_url: str, start_date: date, end_date: date):
        global BASE_URL
        BASE_URL = api_url
        self.load_config()
        df = self.fetch_usage_data(start_date, end_date)
        return self.calculate_charges(df, start_date, end_date)\
        
    def save_invoice(self, charges: dict, start_date: date, end_date: date):
        # Find component IDs for each charge
        name_to_id = {c['category_name']: c['id'] for c in self.plan['components']}
        breakdowns = []
        for name, cost in charges.items():
            breakdowns.append({
                "component_id": name_to_id[name],
                "units_used": 0,  # You can calculate actual units if needed
                "cost": cost
            })
        payload = {
            "customer_id": self.customer_id,
            "period_start": str(start_date),
            "period_end": str(end_date),
            "total_cost": sum(charges.values()),
            "breakdowns": breakdowns
        }
        resp = requests.post(f"{BASE_URL}/invoices", json=payload)
        if resp.status_code == 200:
            print("Invoice saved to database.")
        else:
            print("Failed to save invoice:", resp.text)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--customer_id', required=True, type=int) # 1 EXISTS IN DB
    parser.add_argument('--start', required=True) # YYYY-MM-DD
    parser.add_argument('--end', required=True) # YYYY-MM-DD
    args = parser.parse_args()

    billing = EnergyBillingSystem(args.customer_id)
    billing.load_config()
    start_date, end_date = date.fromisoformat(args.start), date.fromisoformat(args.end)
    df = billing.fetch_usage_data(start_date, end_date)
    charges = billing.calculate_charges(df, start_date, end_date)

    print(f"\nCharges for customer {args.customer_id}, from {start_date} to {end_date}:") # TODO: ADD TO INVOICE TABLE USING ENDPOINT (AFTER CONFIRMING VALIDITY)
    for k, v in charges.items():
        print(f"  {k}: ${v:.2f}")
    print(f"Total: ${sum(charges.values()):.2f}")

    billing.save_invoice(charges, start_date, end_date)

if __name__ == "__main__":
    main()

# must use by cli example: python system.py --customer_id 1 --start 2023-09-01 --end 2023-10-01
