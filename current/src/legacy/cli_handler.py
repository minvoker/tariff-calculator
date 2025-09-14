from datetime import datetime
from api.db_models import Session, TariffPlan, TariffComponent, Provider

def get_user_input():
    session = Session()
    
    # Get meter data path
    data_path = input("Enter meter data file path: ").strip()
    
    # Get date
    calc_date = datetime.strptime(
        input("Date (YYYY-MM-DD): ").strip(), 
        "%Y-%m-%d"
    ).date()
    
    # Select provider
    providers = session.query(Provider).all()
    print("\nProviders:")
    for i, p in enumerate(providers, 1):
        print(f"{i}. {p.name}")
    provider = providers[int(input("Select provider: "))-1]
    
    # Select plan
    plans = session.query(TariffPlan).filter_by(provider_id=provider.id).all()
    print("\nTariff Plans:")
    for i, p in enumerate(plans, 1):
        print(f"{i}. {p.name}")
    plan = plans[int(input("Select plan: "))-1]
    
    return {
        'data_path': data_path,
        'calc_date': calc_date,
        'plan_id': plan.id
    }