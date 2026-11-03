from users.models import User
from ngo.models import NGOProfile
users = User.objects.filter(email__startswith='e2e_ngo_csr_')
for u in users:
    ngo = getattr(u, 'ngo_profile', None)
    if ngo:
        v = getattr(ngo, 'verification', None)
        l = getattr(ngo, 'legal_info', None)
        print(f"User: {u.email}")
        print(f"  NGO status: {ngo.status}, is_active: {ngo.is_active}")
        print(f"  Legal: org_type={l.organisation_type if l else None}, 3yr={l.three_years_completed if l else None}, csr1={l.has_csr_1 if l else None}, is_csr_eligible={l.is_csr_eligible if l else None}")
        print(f"  Verification: is_csr_verified={v.is_csr_verified if v else None}")
