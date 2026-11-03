import requests
from users.models import User
u = User.objects.filter(email__startswith='e2e_ngo_csr_').first()
from rest_framework_simplejwt.tokens import RefreshToken
token = str(RefreshToken.for_user(u).access_token)
headers = {"Authorization": f"Bearer {token}"}

legal_payload = {
    "organisation_type": "SECTION_8_COMPANY",
    "registration_number": "U85100GJ2018NPL123456",
    "pan_number": "AAACG1234K",
    "darpan_id": "GJ/2018/0123456",
    "has_12a": True,
    "twelve_a_number": "12A-REG-98765",
    "has_80g": True,
    "eighty_g_number": "80G-REG-98765",
    "has_10_23c": False,
    "has_fcra": False,
    "has_csr_1": True,
    "csr_registration_number": "CSR00012345"
}
r = requests.post("http://localhost:8000/api/v1/ngo/legal/me/", json=legal_payload, headers=headers)
print("Legal status:", r.status_code)
print("Legal text:", r.text)
