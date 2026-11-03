from users.models import User
from ngo.models import NGOProfile
users = User.objects.filter(email__startswith='e2e_ngo_sd_')
for u in users:
    ngo = getattr(u, 'ngo_profile', None)
    if ngo:
        v = getattr(ngo, 'verification', None)
        l = getattr(ngo, 'legal_info', None)
        print(f"User: {u.email}")
        print(f"  NGO status: {ngo.status}, is_active: {ngo.is_active}")
        print(f"  Legal: {l}")
        if l:
            print(f"    csr1={l.has_csr_1}, crn={l.csr_registration_number}, 12a={l.has_12a}, 80g={l.has_80g}, 3yr={l.three_years_completed}, is_eligible={l.is_csr_eligible}")
        print(f"  Verification: is_csr_verified={v.is_csr_verified if v else None}")
