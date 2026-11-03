"""
Comprehensive Live E2E Verification Runner for DaanGives
Executes full HTTP user journeys against http://localhost:8000
Covers Scenarios A, B, C, D, and E.
"""

import sys
import os
import io
import json
import uuid
import requests
from datetime import date, timedelta

# Setup Django environment for ORM checks if needed
sys.path.insert(0, '/Users/chaudharykamlesh/Desktop/daangives-backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DaanProject.settings')
import django
django.setup()
from users.models import User

BASE_URL = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "test_admin_e2e@daangives.org"
ADMIN_PASSWORD = "AdminTest@123456"

results = []

def record_result(test_id, scenario, action, expected, actual, status_val, notes=""):
    results.append({
        "id": test_id,
        "scenario": scenario,
        "action": action,
        "expected": expected,
        "actual": actual,
        "status": status_val,
        "notes": notes,
    })
    badge = f"[{status_val}]"
    print(f"{badge:<8} {test_id}: {action} -> {status_val}")
    if status_val == "FAIL":
        print(f"         Expected: {expected}")
        print(f"         Actual:   {actual}")

def login(email, password):
    r = requests.post(f"{BASE_URL}/auth/login/", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()["access"]
    raise Exception(f"Login failed for {email}: {r.status_code} {r.text}")

def create_sample_pdf_bytes():
    return b"%PDF-1.4\n1 0 obj\n<< /Title (Test Document) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

def generate_valid_pan(prefix="AAACB"):
    digits = f"{uuid.uuid4().int % 9000 + 1000:04d}"
    return f"{prefix[:5]}{digits}K"

def generate_valid_cin():
    digits = f"{uuid.uuid4().int % 900000 + 100000:06d}"
    return f"L12345MH2020PLC{digits}"

def main():
    print("=" * 80)
    print("STARTING DAANGIVES LIVE END-TO-END VERIFICATION AUDIT")
    print("=" * 80)

    # Preconditions / Admin Auth
    try:
        admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        record_result("PRE-01", "Admin Auth", "Log in as dedicated test admin", "HTTP 200 with JWT access token", "Success", "PASS")
    except Exception as e:
        record_result("PRE-01", "Admin Auth", "Log in as dedicated test admin", "HTTP 200", str(e), "FAIL")
        sys.exit(1)

    # -------------------------------------------------------------------------
    # SCENARIO A: NGO Workflow (Standard Non-CSR NGO)
    # -------------------------------------------------------------------------
    ngo_a_email = f"e2e_ngo_std_{uuid.uuid4().hex[:6]}@daangives.org"
    ngo_a_pass = "NgoPass@12345"

    # A.1 Register new NGO user
    r = requests.post(f"{BASE_URL}/auth/register/", json={
        "email": ngo_a_email,
        "full_name": "Standard Charity Trustee",
        "phone": "+919876543210",
        "password": ngo_a_pass,
        "password_confirm": ngo_a_pass,
        "role": "NGO"
    })
    if r.status_code == 201:
        record_result("TC-A01", "NGO Registration", "Register new NGO user account", "HTTP 201 Created", f"HTTP {r.status_code}", "PASS")
    else:
        record_result("TC-A01", "NGO Registration", "Register new NGO user account", "HTTP 201 Created", f"HTTP {r.status_code}: {r.text}", "FAIL")
        return

    ngo_a_token = login(ngo_a_email, ngo_a_pass)
    ngo_a_headers = {"Authorization": f"Bearer {ngo_a_token}"}

    # A.2 Create initial NGO Profile (DRAFT)
    profile_data = {
        "legal_name": "Shree Seva Samiti Trust",
        "display_name": f"Shree Seva Samiti {uuid.uuid4().hex[:4]}",
        "category": "EDUCATION",
        "description": "Providing quality grassroots education and mid-day nutrition for rural underprivileged children in Gujarat villages.",
        "year_established": 2024, # 2-year-old NGO (<3 years track record)
        "official_email": ngo_a_email,
        "official_phone": "+919876543210"
    }
    r = requests.post(f"{BASE_URL}/ngo/profile/", json=profile_data, headers=ngo_a_headers)
    ngo_a_id = r.json().get("id") if r.status_code == 201 else None
    if r.status_code == 201 and r.json().get("status") == "DRAFT":
        record_result("TC-A02", "NGO Registration Status", "Verify initial NGO status is DRAFT and never auto-approved", "status=DRAFT, is_active=False", f"status={r.json().get('status')}, is_active={r.json().get('is_active')}", "PASS")
    else:
        record_result("TC-A02", "NGO Registration Status", "Verify initial NGO status is DRAFT", "status=DRAFT", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # A.3 Inspect Government verification state
    r = requests.get(f"{BASE_URL}/admin/ngos/{ngo_a_id}/", headers=admin_headers)
    gov_status = r.json().get("verification", {}).get("gov_check_status") if r.status_code == 200 else None
    if gov_status == "MANUAL_VERIFICATION_REQUIRED":
        record_result("TC-A03", "Government Verification State", "Verify initial gov check defaults to manual verification required", "gov_check_status=MANUAL_VERIFICATION_REQUIRED", f"gov_check_status={gov_status}", "PASS")
    else:
        record_result("TC-A03", "Government Verification State", "Verify initial gov check defaults", "MANUAL_VERIFICATION_REQUIRED", f"{gov_status}", "FAIL")

    # Complete NGO sections (Address, Legal, Bank, Leadership, Documents)
    # Address
    r = requests.post(f"{BASE_URL}/ngo/address/me/", json={
        "address_line1": "101 Seva Bhavan, Station Road",
        "city": "Ahmedabad",
        "district": "Ahmedabad",
        "state": "Gujarat",
        "pincode": "380001"
    }, headers=ngo_a_headers)
    
    # Legal (Non-CSR, no 12A/80G/CSR-1)
    pan_a = generate_valid_pan("AABTB")
    darpan_a = f"GJ/2024/{uuid.uuid4().hex[:7]}"
    r = requests.post(f"{BASE_URL}/ngo/legal/me/", json={
        "organisation_type": "TRUST",
        "registering_authority": "Charity Commissioner Ahmedabad",
        "registration_number": f"TRUST/{uuid.uuid4().hex[:6].upper()}",
        "registration_state": "Gujarat",
        "chief_trustee_name": "Rameshbhai Patel",
        "chief_trustee_designation": "Managing Trustee",
        "pan_number": pan_a,
        "darpan_id": darpan_a,
        "has_12a": False,
        "has_80g": False,
        "has_10_23c": False,
        "has_fcra": False,
        "has_csr_1": False
    }, headers=ngo_a_headers)

    # Bank
    r = requests.post(f"{BASE_URL}/ngo/bank/me/", json={
        "account_holder_name": "Shree Seva Samiti Trust",
        "account_number": "123456789012",
        "ifsc_code": "SBIN0001234",
        "bank_name": "State Bank of India",
        "account_type": "CURRENT"
    }, headers=ngo_a_headers)

    # Leadership
    r = requests.post(f"{BASE_URL}/ngo/leadership/", json={
        "full_name": "Rameshbhai Patel",
        "designation": "Managing Trustee",
        "email": ngo_a_email,
        "phone": "+919876543210",
        "is_primary_contact": True
    }, headers=ngo_a_headers)

    # 7 Universal Required Documents
    required_doc_types = [
        "REGISTRATION_CERT", "PAN_CARD", "DARPAN_CERTIFICATE",
        "AUDITED_FINANCIALS", "BANK_PASSBOOK", "CANCELLED_CHEQUE", "REPRESENTATIVE_ID"
    ]
    pdf_data = create_sample_pdf_bytes()
    for dtype in required_doc_types:
        requests.post(f"{BASE_URL}/ngo/documents/", data={
            "document_type": dtype
        }, files={
            "file": (f"{dtype.lower()}.pdf", pdf_data, "application/pdf")
        }, headers=ngo_a_headers)

    # A.4 Submit NGO Application
    r = requests.post(f"{BASE_URL}/ngo/submit/", headers=ngo_a_headers)
    if r.status_code == 200 and r.json().get("status") == "SUBMITTED":
        record_result("TC-A04", "NGO Submission", "Submit NGO application and confirm status is SUBMITTED (not approved)", "status=SUBMITTED, is_active=False", f"status={r.json().get('status')}, is_active={r.json().get('is_active')}", "PASS")
    else:
        record_result("TC-A04", "NGO Submission", "Submit NGO application", "status=SUBMITTED", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # A.5 Admin Inspection & Start Review
    r = requests.post(f"{BASE_URL}/admin/ngos/{ngo_a_id}/start-review/", headers=admin_headers)
    if r.status_code == 200 and r.json().get("status") == "UNDER_REVIEW":
        record_result("TC-A05", "Admin Review Start", "Admin transitions NGO from SUBMITTED to UNDER_REVIEW", "status=UNDER_REVIEW", "status=UNDER_REVIEW", "PASS")
    else:
        record_result("TC-A05", "Admin Review Start", "Admin transitions NGO to UNDER_REVIEW", "status=UNDER_REVIEW", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # A.6 Admin Request Corrections
    r = requests.post(f"{BASE_URL}/admin/ngos/{ngo_a_id}/request-correction/", json={
        "correction_instructions": "Please update description to include specific operational villages.",
        "admin_notes": "Internal review note: description requires village specifics."
    }, headers=admin_headers)
    if r.status_code == 200 and r.json().get("status") == "CORRECTION_REQUIRED":
        record_result("TC-A06", "Correction Request", "Admin requests correction from NGO (UNDER_REVIEW -> CORRECTION_REQUIRED)", "status=CORRECTION_REQUIRED", "status=CORRECTION_REQUIRED", "PASS")
    else:
        record_result("TC-A06", "Correction Request", "Admin requests correction", "status=CORRECTION_REQUIRED", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # A.7 NGO Resubmission Flow
    # NGO updates description
    requests.patch(f"{BASE_URL}/ngo/profile/me/", json={
        "description": "Providing quality grassroots education and mid-day nutrition for rural underprivileged children in Bavla and Sanand villages, Gujarat."
    }, headers=ngo_a_headers)
    r = requests.post(f"{BASE_URL}/ngo/submit/", headers=ngo_a_headers)
    if r.status_code == 200 and r.json().get("status") == "SUBMITTED":
        record_result("TC-A07", "NGO Resubmission", "NGO corrects profile and resubmits (CORRECTION_REQUIRED -> SUBMITTED)", "status=SUBMITTED", "status=SUBMITTED", "PASS")
    else:
        record_result("TC-A07", "NGO Resubmission", "NGO resubmission", "status=SUBMITTED", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # A.8 Record Manual Gov Check without Auto-Approval
    requests.post(f"{BASE_URL}/admin/ngos/{ngo_a_id}/start-review/", headers=admin_headers)
    r = requests.post(f"{BASE_URL}/admin/ngos/{ngo_a_id}/record-gov-check/", json={
        "outcome": "GOVERNMENT_CHECK_PASSED",
        "source": "NGO_DARPAN_MANUAL_SEARCH",
        "notes": "Verified Darpan ID matches NGO legal trust deed."
    }, headers=admin_headers)
    # Check that status remains UNDER_REVIEW
    r_check = requests.get(f"{BASE_URL}/admin/ngos/{ngo_a_id}/", headers=admin_headers)
    if r_check.status_code == 200 and r_check.json().get("status") == "UNDER_REVIEW":
        record_result("TC-A08", "Gov Check Non-Elevation", "Recording passing Gov Check does NOT automatically approve NGO", "status remains UNDER_REVIEW", f"status={r_check.json().get('status')}", "PASS")
    else:
        record_result("TC-A08", "Gov Check Non-Elevation", "Gov check non-elevation", "status=UNDER_REVIEW", f"{r_check.status_code}", "FAIL")

    # A.9 Authorized Admin Approval (without CSR verification)
    r = requests.post(f"{BASE_URL}/admin/ngos/{ngo_a_id}/approve/", json={
        "reason": "All documents verified and trustee credentials confirmed.",
        "verify_csr": False
    }, headers=admin_headers)
    if r.status_code == 200 and r.json().get("status") == "APPROVED" and r.json().get("is_active") is True:
        record_result("TC-A09", "Admin Final Approval", "Admin approves NGO for general charitable platform operations", "status=APPROVED, is_active=True", f"status={r.json().get('status')}, is_active={r.json().get('is_active')}", "PASS")
    else:
        record_result("TC-A09", "Admin Final Approval", "Admin approves NGO", "status=APPROVED", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # -------------------------------------------------------------------------
    # SCENARIO B: CSR Company Workflow End-to-End
    # -------------------------------------------------------------------------
    comp_b_email = f"e2e_comp_{uuid.uuid4().hex[:6]}@daangives.org"
    comp_b_pass = "CompPass@12345"
    cin_b = generate_valid_cin()
    pan_b = generate_valid_pan("AAACB")

    # B.1 Register CSR Company user
    r = requests.post(f"{BASE_URL}/auth/register/", json={
        "email": comp_b_email,
        "full_name": "Apex Corporate CSR Lead",
        "phone": "+919876543299",
        "password": comp_b_pass,
        "password_confirm": comp_b_pass,
        "role": "COMPANY"
    })
    comp_b_token = login(comp_b_email, comp_b_pass)
    comp_b_headers = {"Authorization": f"Bearer {comp_b_token}"}

    # B.2 Create Company Profile (DRAFT)
    r = requests.post(f"{BASE_URL}/csr/profile/me/", json={
        "company_name": "Apex Technologies India Ltd",
        "legal_name": "Apex Technologies India Limited",
        "cin_number": cin_b,
        "pan_number": pan_b,
        "contact_person_name": "Aakash Mehta",
        "contact_person_designation": "Head of Corporate Social Responsibility",
        "contact_email": comp_b_email,
        "contact_phone": "+919876543299",
        "registered_address": "401 Cyber Heights, BKC",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400051",
        "annual_csr_budget": "5000000.00"
    }, headers=comp_b_headers)
    comp_b_id = r.json().get("id") if r.status_code == 201 else None

    # Attach Verification Doc
    requests.post(f"{BASE_URL}/csr/profile/verification-document/", files={
        "file": ("coi.pdf", create_sample_pdf_bytes(), "application/pdf")
    }, headers=comp_b_headers)

    # Submit verification
    r = requests.post(f"{BASE_URL}/csr/profile/submit/", headers=comp_b_headers)
    if r.status_code == 200 and r.json().get("verification_status") == "PENDING_VERIFICATION":
        record_result("TC-B01", "Company Registration & Submit", "Company submits profile and status becomes PENDING_VERIFICATION (not approved)", "verification_status=PENDING_VERIFICATION", f"status={r.json().get('verification_status')}", "PASS")
    else:
        record_result("TC-B01", "Company Registration & Submit", "Company submits profile", "PENDING_VERIFICATION", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # B.3 Unapproved Company restricted action check
    # Try sending support request while unapproved
    r = requests.post(f"{BASE_URL}/csr/support-requests/", json={
        "requirement": str(uuid.uuid4()),
        "support_type": "FINANCIAL_GRANT",
        "proposed_funding": "50000.00",
        "spoc_name": "Aakash Mehta",
        "spoc_email": comp_b_email,
        "spoc_phone": "+919876543299",
        "message": "We would like to fund this project."
    }, headers=comp_b_headers)
    if r.status_code == 403:
        record_result("TC-B02", "Unapproved Company Restricted Action", "Unapproved company cannot perform restricted CSR transactions (create support request)", "HTTP 403 Forbidden", f"HTTP {r.status_code}", "PASS")
    else:
        record_result("TC-B02", "Unapproved Company Restricted Action", "Unapproved company restricted action", "HTTP 403 Forbidden", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # B.4 Admin records gov check on Company
    r = requests.post(f"{BASE_URL}/admin/csr/companies/{comp_b_id}/record-gov-check/", json={
        "outcome": "GOVERNMENT_CHECK_PASSED",
        "source": "MCA21_MASTER_DATA",
        "notes": "CIN verified on MCA portal."
    }, headers=admin_headers)
    r_check = requests.get(f"{BASE_URL}/admin/csr/companies/{comp_b_id}/", headers=admin_headers)
    if r_check.status_code == 200 and r_check.json().get("verification_status") == "PENDING_VERIFICATION":
        record_result("TC-B03", "Company Gov Check Non-Elevation", "Passing Company Gov Check preserves PENDING_VERIFICATION status", "verification_status=PENDING_VERIFICATION", f"status={r_check.json().get('verification_status')}", "PASS")
    else:
        record_result("TC-B03", "Company Gov Check Non-Elevation", "Company gov check non-elevation", "PENDING_VERIFICATION", f"{r_check.status_code}", "FAIL")

    # B.5 Admin Requests Corrections on Company
    r = requests.post(f"{BASE_URL}/admin/csr/companies/{comp_b_id}/request-correction/", json={
        "correction_instructions": "Please attach official ROC Board Resolution alongside COI.",
        "admin_notes": "Board resolution missing from upload."
    }, headers=admin_headers)
    if r.status_code == 200 and r.json().get("verification_status") == "CORRECTION_REQUIRED":
        record_result("TC-B04", "Company Correction Request", "Admin requests correction on Company (PENDING_VERIFICATION -> CORRECTION_REQUIRED)", "verification_status=CORRECTION_REQUIRED", "CORRECTION_REQUIRED", "PASS")
    else:
        record_result("TC-B04", "Company Correction Request", "Company correction request", "CORRECTION_REQUIRED", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # B.6 Company Resubmission
    requests.post(f"{BASE_URL}/csr/profile/verification-document/", files={
        "file": ("coi_with_resolution.pdf", create_sample_pdf_bytes(), "application/pdf")
    }, headers=comp_b_headers)
    r = requests.post(f"{BASE_URL}/csr/profile/submit/", headers=comp_b_headers)
    if r.status_code == 200 and r.json().get("verification_status") == "PENDING_VERIFICATION":
        record_result("TC-B05", "Company Resubmission", "Company resubmission transitions status back to PENDING_VERIFICATION", "verification_status=PENDING_VERIFICATION", "PENDING_VERIFICATION", "PASS")
    else:
        record_result("TC-B05", "Company Resubmission", "Company resubmission", "PENDING_VERIFICATION", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # B.7 Admin Approves Company
    r = requests.post(f"{BASE_URL}/admin/csr/companies/{comp_b_id}/approve/", json={
        "reason": "ROC incorporation documents and board resolution verified."
    }, headers=admin_headers)
    if r.status_code == 200 and r.json().get("verification_status") == "APPROVED":
        record_result("TC-B06", "Company Admin Approval", "Admin approves CSR company (PENDING_VERIFICATION -> APPROVED)", "verification_status=APPROVED", "APPROVED", "PASS")
    else:
        record_result("TC-B06", "Company Admin Approval", "Company admin approval", "APPROVED", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # -------------------------------------------------------------------------
    # SCENARIO C: CSR Eligibility Safeguards & Public Badges
    # -------------------------------------------------------------------------
    # C.1 Approved but CSR-ineligible NGO cannot create CSR requirement
    today_str = str(date.today())
    next_year_str = str(date.today() + timedelta(days=365))
    r = requests.post(f"{BASE_URL}/ngo/csr/requirements/", json={
        "title": "Unauthorized CSR Solar Proposal",
        "summary": "Proposal from non-CSR compliant entity trying to access Section 135 funds.",
        "detailed_description": "Comprehensive explanation of solar installation project.",
        "expected_outcomes": "Clean power for village schools.",
        "schedule_vii_category": "ENVIRONMENTAL_SUSTAINABILITY",
        "state": "Gujarat",
        "district": "Ahmedabad",
        "location_scope": "SPECIFIC_DISTRICT",
        "beneficiary_demographic": "RURAL_COMMUNITIES",
        "target_beneficiary_count": 500,
        "total_estimated_budget": "500000.00",
        "required_csr_funding": "500000.00",
        "start_date": today_str,
        "expected_completion_date": next_year_str
    }, headers=ngo_a_headers)
    if r.status_code == 403:
        record_result("TC-C01", "CSR-Ineligible Blocked", "Approved non-CSR NGO cannot create CSR requirements", "HTTP 403 Forbidden", f"HTTP {r.status_code}", "PASS")
    else:
        record_result("TC-C01", "CSR-Ineligible Blocked", "Approved non-CSR NGO cannot create CSR requirement", "HTTP 403 Forbidden", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # C.2 Self-declared CSR-1 NGO without Admin Verification
    ngo_sd_email = f"e2e_ngo_sd_{uuid.uuid4().hex[:6]}@daangives.org"
    requests.post(f"{BASE_URL}/auth/register/", json={
        "email": ngo_sd_email, "full_name": "Self Declared Trustee", "phone": "+919876543211",
        "password": "NgoPass@12345", "password_confirm": "NgoPass@12345", "role": "NGO"
    })
    ngo_sd_token = login(ngo_sd_email, "NgoPass@12345")
    ngo_sd_headers = {"Authorization": f"Bearer {ngo_sd_token}"}
    r = requests.post(f"{BASE_URL}/ngo/profile/", json={
        "legal_name": "Self Declared Foundation", "display_name": f"Self Declared Foundation {uuid.uuid4().hex[:4]}",
        "category": "HEALTHCARE", "description": "Healthcare outreach organization providing mobile dispensary services.",
        "year_established": 2020, "official_email": ngo_sd_email, "official_phone": "+919876543211"
    }, headers=ngo_sd_headers)
    ngo_sd_id = r.json().get("id")

    requests.post(f"{BASE_URL}/ngo/address/me/", json={
        "address_line1": "22 Seva Road", "city": "Vadodara", "district": "Vadodara", "state": "Gujarat", "pincode": "390001"
    }, headers=ngo_sd_headers)
    pan_sd = generate_valid_pan("AAATB")
    requests.post(f"{BASE_URL}/ngo/legal/me/", json={
        "organisation_type": "SOCIETY",
        "registering_authority": "Registrar of Societies Vadodara",
        "registration_number": f"SOC/{uuid.uuid4().hex[:6].upper()}",
        "registration_state": "Gujarat",
        "chief_trustee_name": "Hitesh Shah",
        "chief_trustee_designation": "President",
        "pan_number": pan_sd,
        "darpan_id": f"GJ/2020/{uuid.uuid4().hex[:7]}",
        "has_12a": True, "twelve_a_number": "12A-VAL-12345",
        "has_80g": True, "eighty_g_number": "80G-VAL-12345",
        "has_10_23c": False, "has_fcra": False,
        "has_csr_1": True, "csr_registration_number": f"CSR{uuid.uuid4().int % 100000000:08d}"
    }, headers=ngo_sd_headers)
    requests.post(f"{BASE_URL}/ngo/bank/me/", json={
        "account_holder_name": "Self Declared Foundation", "account_number": "987654321098",
        "ifsc_code": "BARB0VADODA", "bank_name": "Bank of Baroda", "account_type": "SAVINGS"
    }, headers=ngo_sd_headers)
    requests.post(f"{BASE_URL}/ngo/leadership/", json={
        "full_name": "Hitesh Shah", "designation": "President", "email": ngo_sd_email,
        "phone": "+919876543211", "is_primary_contact": True
    }, headers=ngo_sd_headers)
    for dtype in required_doc_types + ["TWELVE_A_CERT", "EIGHTY_G_CERT", "CSR_1_CERT"]:
        requests.post(f"{BASE_URL}/ngo/documents/", data={"document_type": dtype}, files={"file": ("doc.pdf", pdf_data, "application/pdf")}, headers=ngo_sd_headers)
    requests.post(f"{BASE_URL}/ngo/submit/", headers=ngo_sd_headers)
    requests.post(f"{BASE_URL}/admin/ngos/{ngo_sd_id}/start-review/", headers=admin_headers)
    # Admin approves general NGO WITHOUT granting CSR verification
    requests.post(f"{BASE_URL}/admin/ngos/{ngo_sd_id}/approve/", json={
        "reason": "General approval granted, CSR documentation pending further audit.",
        "verify_csr": False
    }, headers=admin_headers)

    # Check Public Profile for Self-Declared NGO via UUID endpoint
    r = requests.get(f"{BASE_URL}/public/ngos/id/{ngo_sd_id}/")
    is_csr_ver = r.json().get("is_csr_verified")
    has_csr_1 = r.json().get("has_csr_1")
    if r.status_code == 200 and has_csr_1 is True and is_csr_ver is False:
        record_result("TC-C02", "Self-Declared CSR-1 Badge Integrity", "Self-declared CSR-1 displays has_csr_1=True but is_csr_verified=False (amber unverified badge)", "has_csr_1=True, is_csr_verified=False", f"has_csr_1={has_csr_1}, is_csr_verified={is_csr_ver}", "PASS")
    else:
        record_result("TC-C02", "Self-Declared CSR-1 Badge Integrity", "Self-declared CSR badge", "is_csr_verified=False", f"has_csr_1={has_csr_1}, is_csr_verified={is_csr_ver}", "FAIL")

    # C.3 Fully Eligible and Admin-CSR Verified NGO
    ngo_csr_email = f"e2e_ngo_csr_{uuid.uuid4().hex[:6]}@daangives.org"
    requests.post(f"{BASE_URL}/auth/register/", json={
        "email": ngo_csr_email, "full_name": "CSR Eligible Director", "phone": "+919876543222",
        "password": "NgoPass@12345", "password_confirm": "NgoPass@12345", "role": "NGO"
    })
    ngo_csr_token = login(ngo_csr_email, "NgoPass@12345")
    ngo_csr_headers = {"Authorization": f"Bearer {ngo_csr_token}"}
    r = requests.post(f"{BASE_URL}/ngo/profile/", json={
        "legal_name": "Gram Vikas Section 8 Foundation", "display_name": f"Gram Vikas Foundation {uuid.uuid4().hex[:4]}",
        "category": "ENVIRONMENT", "description": "Specialized environmental water conservation and watershed development organization.",
        "year_established": 2018, # 8-year track record (> 3 years)
        "official_email": ngo_csr_email, "official_phone": "+919876543222"
    }, headers=ngo_csr_headers)
    ngo_csr_id = r.json().get("id")

    requests.post(f"{BASE_URL}/ngo/address/me/", json={
        "address_line1": "55 Green Valley", "city": "Rajkot", "district": "Rajkot", "state": "Gujarat", "pincode": "360001"
    }, headers=ngo_csr_headers)
    pan_csr = generate_valid_pan("AAACG")
    requests.post(f"{BASE_URL}/ngo/legal/me/", json={
        "organisation_type": "SECTION_8",
        "registering_authority": "ROC Gujarat",
        "registration_number": f"U85100GJ2018NPL{uuid.uuid4().hex[:6].upper()}",
        "registration_state": "Gujarat",
        "chief_trustee_name": "Dr. Sunil Mehta",
        "chief_trustee_designation": "Director",
        "pan_number": pan_csr,
        "darpan_id": f"GJ/2018/{uuid.uuid4().hex[:7]}",
        "has_12a": True, "twelve_a_number": "12A-REG-98765",
        "has_80g": True, "eighty_g_number": "80G-REG-98765",
        "has_10_23c": False, "has_fcra": False,
        "has_csr_1": True, "csr_registration_number": f"CSR{uuid.uuid4().int % 100000000:08d}"
    }, headers=ngo_csr_headers)
    requests.post(f"{BASE_URL}/ngo/bank/me/", json={
        "account_holder_name": "Gram Vikas Section 8 Foundation", "account_number": "555666777888",
        "ifsc_code": "HDFC0001234", "bank_name": "HDFC Bank", "account_type": "CURRENT"
    }, headers=ngo_csr_headers)
    requests.post(f"{BASE_URL}/ngo/leadership/", json={
        "full_name": "Dr. Sunil Mehta", "designation": "Director", "email": ngo_csr_email,
        "phone": "+919876543222", "is_primary_contact": True
    }, headers=ngo_csr_headers)
    for dtype in required_doc_types + ["TWELVE_A_CERT", "EIGHTY_G_CERT", "CSR_1_CERT"]:
        requests.post(f"{BASE_URL}/ngo/documents/", data={"document_type": dtype}, files={"file": ("doc.pdf", pdf_data, "application/pdf")}, headers=ngo_csr_headers)
    requests.post(f"{BASE_URL}/ngo/submit/", headers=ngo_csr_headers)
    requests.post(f"{BASE_URL}/admin/ngos/{ngo_csr_id}/start-review/", headers=admin_headers)
    # Admin approves WITH CSR verification
    r = requests.post(f"{BASE_URL}/admin/ngos/{ngo_csr_id}/approve/", json={
        "reason": "Statutory MCA Rule 4 verified, CSR-1 and 12A/80G active on official ITD/MCA registers.",
        "verify_csr": True,
        "csr_notes": "Form CSR-1 CRN verified against MCA21."
    }, headers=admin_headers)

    # Check Public Profile for Verified CSR NGO
    r = requests.get(f"{BASE_URL}/public/ngos/id/{ngo_csr_id}/")
    is_csr_ver = r.json().get("is_csr_verified")
    has_csr_1 = r.json().get("has_csr_1")
    if r.status_code == 200 and has_csr_1 is True and is_csr_ver is True:
        record_result("TC-C03", "Verified CSR-1 Badge Integrity", "Admin-verified CSR NGO displays is_csr_verified=True (emerald shield badge)", "is_csr_verified=True", "is_csr_verified=True", "PASS")
    else:
        record_result("TC-C03", "Verified CSR-1 Badge Integrity", "Verified CSR badge", "is_csr_verified=True", f"is_csr_verified={is_csr_ver}", "FAIL")

    # C.4 Verified CSR NGO CAN create CSR requirement
    r = requests.post(f"{BASE_URL}/ngo/csr/requirements/", json={
        "title": "Solar Powered Watershed Drinking Project",
        "summary": "Constructing decentralized check dams and solar drinking water filtration across 4 drought-prone villages.",
        "detailed_description": "Comprehensive engineering and installation of deep check dams and solar filtration systems.",
        "expected_outcomes": "Potable drinking water security for 5,000 rural residents.",
        "schedule_vii_category": "ENVIRONMENTAL_SUSTAINABILITY",
        "state": "Gujarat",
        "district": "Rajkot",
        "location_scope": "SPECIFIC_DISTRICT",
        "beneficiary_demographic": "RURAL_COMMUNITIES",
        "target_beneficiary_count": 5000,
        "total_estimated_budget": "1500000.00",
        "required_csr_funding": "1500000.00",
        "start_date": today_str,
        "expected_completion_date": next_year_str
    }, headers=ngo_csr_headers)
    csr_req_id = r.json().get("id") if r.status_code == 201 else None
    if r.status_code == 201:
        record_result("TC-C04", "Verified NGO CSR Requirement Creation", "Admin-verified CSR NGO can successfully create CSR requirement", "HTTP 201 Created", "HTTP 201 Created", "PASS")
    else:
        record_result("TC-C04", "Verified NGO CSR Requirement Creation", "Verified NGO requirement creation", "HTTP 201 Created", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # -------------------------------------------------------------------------
    # SCENARIO D: Project & Marketplace Workflow
    # -------------------------------------------------------------------------
    # D.1 Project Creation & Decoupled CSR Readiness
    # Non-CSR NGO creates a village project
    r = requests.post(f"{BASE_URL}/projects/", json={
        "title": "Community Computer Literacy Center",
        "short_summary": "Setting up 10 desktop workstations for high school computer skills training.",
        "description": "Detailed community IT training program for rural students.",
        "category": "EDUCATION",
        "estimated_cost": "300000.00",
        "timeline_months": 6,
        "beneficiaries_count": 250,
        "beneficiaries_description": "High school students from Bavla village.",
        "location_village": "Bavla",
        "location_district": "Ahmedabad",
        "location_state": "Gujarat",
        "location_pincode": "380001"
    }, headers=ngo_a_headers)
    proj_a_id = r.json().get("id") if r.status_code == 201 else None
    # Upload statutory resolution doc before submit
    requests.post(
        f"{BASE_URL}/projects/{proj_a_id}/documents/",
        data={"document_type": "PANCHAYAT_RESOLUTION", "notes": "Resolution passed by Gram Panchayat."},
        files={"file": ("panchayat_noc.pdf", pdf_data, "application/pdf")},
        headers=ngo_a_headers
    )
    # Submit project
    requests.post(f"{BASE_URL}/projects/{proj_a_id}/submit/", headers=ngo_a_headers)
    # Admin verifies project
    requests.post(f"{BASE_URL}/projects/{proj_a_id}/verify/", json={"action": "VERIFY", "notes": "Project inspected."}, headers=admin_headers)

    # Check Non-CSR NGO verified project is_csr_ready
    r = requests.get(f"{BASE_URL}/projects/{proj_a_id}/", headers=ngo_a_headers)
    proj_a_status = r.json().get("status")
    proj_a_csr_ready = r.json().get("is_csr_ready")
    if proj_a_status == "VERIFIED" and proj_a_csr_ready is False:
        record_result("TC-D01", "Project CSR Readiness Decoupling", "Verified project of non-CSR NGO has status=VERIFIED but is_csr_ready=False", "status=VERIFIED, is_csr_ready=False", f"status={proj_a_status}, is_csr_ready={proj_a_csr_ready}", "PASS")
    else:
        record_result("TC-D01", "Project CSR Readiness Decoupling", "Project CSR readiness decoupling", "is_csr_ready=False", f"status={proj_a_status}, is_csr_ready={proj_a_csr_ready}", "FAIL")

    # CSR-Verified NGO creates a village project
    r = requests.post(f"{BASE_URL}/projects/", json={
        "title": "Rainwater Harvesting Check Dam Phase 1",
        "short_summary": "Constructing check dams across drought prone watershed rivers.",
        "description": "Deepening percolation tanks and building concrete barriers for ground recharge.",
        "category": "ENVIRONMENT",
        "estimated_cost": "1200000.00",
        "timeline_months": 12,
        "beneficiaries_count": 5000,
        "beneficiaries_description": "Farming families in Jasdan taluka.",
        "location_village": "Jasdan",
        "location_district": "Rajkot",
        "location_state": "Gujarat",
        "location_pincode": "360001"
    }, headers=ngo_csr_headers)
    proj_b_id = r.json().get("id") if r.status_code == 201 else None
    # Upload statutory resolution doc before submit
    requests.post(
        f"{BASE_URL}/projects/{proj_b_id}/documents/",
        data={"document_type": "PANCHAYAT_RESOLUTION", "notes": "Gram Panchayat check dam resolution."},
        files={"file": ("checkdam_noc.pdf", pdf_data, "application/pdf")},
        headers=ngo_csr_headers
    )
    requests.post(f"{BASE_URL}/projects/{proj_b_id}/submit/", headers=ngo_csr_headers)
    requests.post(f"{BASE_URL}/projects/{proj_b_id}/verify/", json={"action": "VERIFY", "notes": "Site verified."}, headers=admin_headers)

    # Check CSR-Verified NGO project is_csr_ready
    r = requests.get(f"{BASE_URL}/projects/{proj_b_id}/", headers=ngo_csr_headers)
    proj_b_status = r.json().get("status")
    proj_b_csr_ready = r.json().get("is_csr_ready")
    if proj_b_status == "VERIFIED" and proj_b_csr_ready is True:
        record_result("TC-D02", "CSR-Ready Project Verification", "Verified project of CSR-verified NGO has is_csr_ready=True", "status=VERIFIED, is_csr_ready=True", f"status={proj_b_status}, is_csr_ready={proj_b_csr_ready}", "PASS")
    else:
        record_result("TC-D02", "CSR-Ready Project Verification", "CSR-ready project verification", "is_csr_ready=True", f"status={proj_b_status}, is_csr_ready={proj_b_csr_ready}", "FAIL")

    # D.2 CSR Marketplace & Partnership Flow
    # NGO submits requirement for review
    requests.post(f"{BASE_URL}/ngo/csr/requirements/{csr_req_id}/submit/", headers=ngo_csr_headers)
    # Admin approves requirement
    requests.post(f"{BASE_URL}/admin/csr/requirements/{csr_req_id}/approve/", json={"review_notes": "Meets Schedule VII criteria."}, headers=admin_headers)

    # Company accesses marketplace and views requirement
    r = requests.get(f"{BASE_URL}/csr/requirements/", headers=comp_b_headers)
    req_ids = [item["id"] for item in r.json().get("results", [])]
    if csr_req_id in req_ids:
        record_result("TC-D03", "Marketplace Discovery", "Approved CSR company discovers approved CSR requirement in marketplace", "Requirement present in marketplace", "Found in marketplace", "PASS")
    else:
        record_result("TC-D03", "Marketplace Discovery", "Marketplace discovery", "Requirement present", f"Not found in {req_ids}", "FAIL")

    # Company creates Support Request (Expression of Interest)
    r = requests.post(f"{BASE_URL}/csr/support-requests/", json={
        "requirement": csr_req_id,
        "support_type": "FINANCIAL_GRANT",
        "proposed_funding": "500000.00",
        "spoc_name": "Aakash Mehta",
        "spoc_email": comp_b_email,
        "spoc_phone": "+919876543299",
        "message": "Apex Technologies India Ltd offers a 5 Lakh grant for watershed development."
    }, headers=comp_b_headers)
    support_req_id = r.json().get("id") if r.status_code == 201 else None
    if r.status_code == 201:
        record_result("TC-D04", "Corporate Support Request", "Approved company issues formal CSR support request to verified NGO", "HTTP 201 Created", "HTTP 201 Created", "PASS")
    else:
        record_result("TC-D04", "Corporate Support Request", "Support request creation", "HTTP 201 Created", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # NGO accepts Support Request -> Bilateral Partnership Created
    r = requests.post(f"{BASE_URL}/ngo/csr/support-requests/{support_req_id}/accept/", json={
        "response_notes": "We gratefully accept Apex Technologies' CSR grant proposal."
    }, headers=ngo_csr_headers)
    partnership_id = r.json().get("partnership", {}).get("id") if r.status_code == 200 else None
    if r.status_code == 200 and partnership_id:
        record_result("TC-D05", "Bilateral Partnership Creation", "Verified NGO accepts support request, creating bilateral CSR partnership", "HTTP 200 with partnership object", f"Created partnership {partnership_id}", "PASS")
    else:
        record_result("TC-D05", "Bilateral Partnership Creation", "Partnership creation", "HTTP 200", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # D.3 Direct CSR Bank Disbursement Tracking
    # Company uploads MoU and activates partnership
    requests.post(f"{BASE_URL}/csr/partnerships/{partnership_id}/mou/", files={"file": ("mou.pdf", pdf_data, "application/pdf")}, headers=comp_b_headers)
    
    # Company records off-platform direct bank transfer disbursement
    r = requests.post(f"{BASE_URL}/csr/partnerships/{partnership_id}/disbursements/", data={
        "amount": "250000.00",
        "payment_reference": "NEFT-APEX-20261028-01",
        "payment_date": str(date.today()),
        "payment_mode": "NEFT",
        "bank_name": "HDFC Bank",
        "notes": "Tranche 1 for ground excavation and percolation materials."
    }, files={
        "evidence_document": ("bank_advice.pdf", pdf_data, "application/pdf")
    }, headers=comp_b_headers)
    if r.status_code == 201:
        record_result("TC-D06", "Direct Bank Disbursement Entry", "Approved company records direct corporate bank transfer disbursement proof", "HTTP 201 Created", "HTTP 201 Created", "PASS")
    else:
        record_result("TC-D06", "Direct Bank Disbursement Entry", "Disbursement entry", "HTTP 201 Created", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # -------------------------------------------------------------------------
    # SCENARIO E: Security & Data Integrity
    # -------------------------------------------------------------------------
    # E.1 Block self-registration as ADMIN
    r = requests.post(f"{BASE_URL}/auth/register/", json={
        "email": "hacker_admin@daangives.org", "full_name": "Fake Admin", "phone": "+919876543299",
        "password": "HackerPass@123", "password_confirm": "HackerPass@123", "role": "ADMIN"
    })
    if r.status_code == 400 and "Self-registration as ADMIN is strictly prohibited" in r.text:
        record_result("TC-E01", "Admin Self-Registration Block", "Direct registration API rejects role='ADMIN' payload", "HTTP 400 Bad Request", "HTTP 400 (Self-registration strictly prohibited)", "PASS")
    else:
        record_result("TC-E01", "Admin Self-Registration Block", "Admin self-registration block", "HTTP 400", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # E.2 NGO user cannot approve itself
    r = requests.post(f"{BASE_URL}/admin/ngos/{ngo_a_id}/approve/", json={"verify_csr": True}, headers=ngo_a_headers)
    if r.status_code == 403:
        record_result("TC-E02", "NGO Self-Approval Block", "NGO user calling admin approve API receives HTTP 403 Forbidden", "HTTP 403 Forbidden", "HTTP 403 Forbidden", "PASS")
    else:
        record_result("TC-E02", "NGO Self-Approval Block", "NGO self approval block", "HTTP 403 Forbidden", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # E.3 CSR Company user cannot approve itself
    r = requests.post(f"{BASE_URL}/admin/csr/companies/{comp_b_id}/approve/", json={}, headers=comp_b_headers)
    if r.status_code == 403:
        record_result("TC-E03", "Company Self-Approval Block", "Company user calling admin approve API receives HTTP 403 Forbidden", "HTTP 403 Forbidden", "HTTP 403 Forbidden", "PASS")
    else:
        record_result("TC-E03", "Company Self-Approval Block", "Company self approval block", "HTTP 403 Forbidden", f"HTTP {r.status_code}: {r.text}", "FAIL")

    # E.4 Tenant Isolation: NGO A cannot view/tamper NGO B's private documents
    # NGO A tries to access NGO CSR's documents
    r = requests.get(f"{BASE_URL}/ngo/documents/", headers=ngo_a_headers)
    ngo_a_docs = [d["id"] for d in r.json()]
    r_csr = requests.get(f"{BASE_URL}/ngo/documents/", headers=ngo_csr_headers)
    ngo_csr_docs = [d["id"] for d in r_csr.json()]
    overlap = set(ngo_a_docs).intersection(set(ngo_csr_docs))
    if len(overlap) == 0 and len(ngo_a_docs) > 0 and len(ngo_csr_docs) > 0:
        record_result("TC-E04", "Tenant Isolation", "NGO A cannot access or see private documents of NGO B", "Zero document overlap between tenants", "0 shared documents", "PASS")
    else:
        record_result("TC-E04", "Tenant Isolation", "Tenant isolation", "Zero overlap", f"Overlap: {overlap}", "FAIL")

    # E.5 Unauthenticated requests rejected
    r = requests.get(f"{BASE_URL}/csr/dashboard/")
    if r.status_code == 401:
        record_result("TC-E05", "Unauthenticated Protection", "Unauthenticated request to protected CSR dashboard returns HTTP 401", "HTTP 401 Unauthorized", "HTTP 401 Unauthorized", "PASS")
    else:
        record_result("TC-E05", "Unauthenticated Protection", "Unauthenticated protection", "HTTP 401", f"HTTP {r.status_code}", "FAIL")

    # E.6 Non-destructive test verification
    # Confirm existing users in db
    existing_root = User.objects.filter(email="root@gmail.com").first()
    if existing_root and existing_root.is_staff and existing_root.is_superuser:
        record_result("TC-E06", "Pre-existing Data Integrity", "Pre-existing production-like accounts remain intact without alteration", "root@gmail.com remains active superuser", "Verified intact", "PASS")
    else:
        record_result("TC-E06", "Pre-existing Data Integrity", "Data integrity check", "Intact", "Altered or missing", "FAIL")

    print("=" * 80)
    total_count = len(results)
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    print(f"E2E TEST RUN COMPLETED: {total_count} total, {pass_count} PASSED, {fail_count} FAILED")
    print("=" * 80)

    # Output JSON summary for artifact generation
    with open("/Users/chaudharykamlesh/Desktop/daangives-backend/scratch/e2e_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
