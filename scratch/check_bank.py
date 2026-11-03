import requests
from users.models import User
from rest_framework_simplejwt.tokens import RefreshToken
u = User.objects.filter(email__startswith='e2e_ngo_sd_').order_by('-date_joined').first()
token = str(RefreshToken.for_user(u).access_token)
headers = {"Authorization": f"Bearer {token}"}
r = requests.post("http://localhost:8000/api/v1/ngo/bank/me/", json={
    "account_holder_name": "Self Declared Foundation",
    "account_number": "987654321098",
    "ifsc_code": "BARB0VADODAX",
    "bank_name": "Bank of Baroda",
    "account_type": "SAVINGS"
}, headers=headers)
print("Bank create status:", r.status_code)
print("Bank text:", r.text)
