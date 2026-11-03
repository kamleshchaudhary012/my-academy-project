import requests
r = requests.get("http://localhost:8000/api/v1/public/ngos/")
print("List status:", r.status_code, "Count:", len(r.json().get('results', [])))
if r.json().get('results'):
    first = r.json()['results'][0]
    first_id = first['id']
    first_slug = first['slug']
    r_uuid = requests.get(f"http://localhost:8000/api/v1/public/ngos/id/{first_id}/")
    print("UUID detail status:", r_uuid.status_code, "has_csr_1:", r_uuid.json().get('has_csr_1'), "is_csr_verified:", r_uuid.json().get('is_csr_verified'))
