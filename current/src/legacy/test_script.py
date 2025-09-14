from system import EnergyBillingSystem
from datetime import date

# Create billing object with customer_id
billing = EnergyBillingSystem(customer_id=1)

# Call the convenience method
invoice = billing.calculate_from_api(
    api_url="http://localhost:8000",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 1, 31)
)

# Print charges
print("Charges:")
for k, v in invoice.items():
    print(f"  {k}: ${v:.2f}")
print(f"Total: ${sum(invoice.values()):.2f}")
