import requests
import uuid

BASE_URL = "http://localhost:8000/api/v1"
email = f"debug_comp_{uuid.uuid4().hex[:6]}@daangives.org"
pwd = "CompPass@12345"

r_reg = requests.post(f"{BASE_URL}/auth/register/", json={
    "email": email, "full_name": "Debug Lead", "phone": "+919876543299",
    "password": pwd, "password_confirm": pwd, "role": "COMPANY"
})

r_login = requests.post(f"{BASE_URL}/auth/login/", json={"email": email, "password": pwd})
token = r_login.json()["access"]
headers = {"Authorization": f"Bearer {token}"}

cin_b = f"L12345MH2020PLC{uuid.uuid4().int % 900000 + 100000:06d}"
pan_b = f"AAACB{uuid.uuid4().int % 9000 + 1000:04d}K"

r_prof = requests.post(f"{BASE_URL}/csr/profile/me/", json={
    "company_name": "Debug Corp Ltd",
    "legal_name": "Debug Corporation Limited",
    "cin_number": cin_b,
    "pan_number": pan_b,
    "contact_person_name": "Aakash Mehta",
    "contact_person_designation": "Head CSR",
    "contact_email": email,
    "contact_phone": "+919876543299",
    "registered_address": "401 Cyber Heights",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400051",
    "annual_csr_budget": "5000000.00"
}, headers=headers)
print("Profile create status:", r_prof.status_code)
print("Profile id:", r_prof.json().get('id'))
