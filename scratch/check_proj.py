import requests
from users.models import User
from projects.models import Project
from rest_framework_simplejwt.tokens import RefreshToken

p = Project.objects.order_by('-created_at').first()
token = str(RefreshToken.for_user(p.posted_by).access_token)
headers = {"Authorization": f"Bearer {token}"}

pdf_data = b"%PDF-1.4\n1 0 obj\n<< /Title (Test Document) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
r_doc = requests.post(
    f"http://localhost:8000/api/v1/projects/{p.id}/documents/",
    data={"document_type": "PANCHAYAT_RESOLUTION", "notes": "Resolution passed by Gram Panchayat."},
    files={"file": ("panchayat_noc.pdf", pdf_data, "application/pdf")},
    headers=headers
)
print("Doc upload status:", r_doc.status_code)

r_sub = requests.post(f"http://localhost:8000/api/v1/projects/{p.id}/submit/", headers=headers)
print("Project submit status:", r_sub.status_code, "text:", r_sub.text)

admin = User.objects.filter(role='ADMIN').first()
admin_token = str(RefreshToken.for_user(admin).access_token)
admin_headers = {"Authorization": f"Bearer {admin_token}"}
r_ver = requests.post(f"http://localhost:8000/api/v1/projects/{p.id}/verify/", json={"action": "VERIFY", "notes": "Inspected"}, headers=admin_headers)
print("Project verify status:", r_ver.status_code, "text:", r_ver.text)
p.refresh_from_db()
print("Final project status:", p.status, "is_csr_ready:", p.is_csr_ready)
