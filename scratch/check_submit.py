import requests
from users.models import User
from rest_framework_simplejwt.tokens import RefreshToken
u = User.objects.filter(email__startswith='e2e_ngo_sd_').order_by('-date_joined').first()
token = str(RefreshToken.for_user(u).access_token)
headers = {"Authorization": f"Bearer {token}"}
r = requests.post("http://localhost:8000/api/v1/ngo/submit/", headers=headers)
print("Submit status:", r.status_code)
print("Submit response:", r.text)
