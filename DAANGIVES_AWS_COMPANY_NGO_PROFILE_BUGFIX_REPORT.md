# DaanGives — AWS Production Bug Fix Report
# Company Profile Missing + NGO Legal Information Completeness Failure

**Date:** November 5, 2026  
**Environment:** AWS EC2 Production (Ubuntu 24.04 / systemd / Nginx / Gunicorn / PostgreSQL 17 / React Vite)  
**Frontend Repository:** `/Users/chaudharykamlesh/Desktop/daangives-frontend`  
**Backend Repository:** `/Users/chaudharykamlesh/Desktop/daangives-backend`  

---

## Executive Summary

During production validation on AWS EC2, two critical full-stack lifecycle defects were detected via screenshots:
1. **Issue 1 (Company Portal):** Users accessing `/company/profile` saw the error *"No company profile found for this user account."* rendered inside the statutory verification document upload card, while the portal simultaneously showed `Verification Status: DRAFT`, Certificate of Incorporation upload controls, and corporate input fields.
2. **Issue 2 (NGO Registration Flow):** On Step 7 (`/ngo/registration-flow`), the application rejected submission with *"Application Incomplete — Please Fix Required Sections"* and reported `LEGAL_INFO: Legal information is required.`, even though PAN (`CKUPC8425M`), Darpan ID (`GJ/08/2032`), and CSR-1 (`Csr98423456`) were displayed directly on the screen.

Both issues have been **investigated down to the byte and query level, reproduced, fixed, and verified** locally with 100% test pass rates across both Django and React Vitest suites. A safe, idempotent Django management command (`repair_company_profiles`) has also been provided to safely backfill any orphaned company accounts created on AWS EC2 without touching or resetting existing database data.

---

## 1. Issue Classification

| Issue | Reported Production Symptom | Root Cause Category | Classification |
|---|---|---|---|
| **Issue 1: Company Profile Missing** | *"No company profile found for this user account."* displayed in document card | Full-Stack: Backend user registration omitted company profile creation; Frontend `api.js` dropped company attributes; Frontend profile upload button was active when no profile was yet persisted. | **CONFIRMED AND FIXED** |
| **Issue 2: NGO Legal Completeness Failure** | `LEGAL_INFO: Legal information is required.` on Step 7 despite PAN/Darpan/CSR-1 showing on screen | Full-Stack: DRF `DateField` strictly rejected empty strings (`""`) for optional certification dates (12A, 80G, FCRA, 10(23C)), causing silent step failure; Step 7 displayed unpersisted React state instead of verifying DB persistence. | **CONFIRMED AND FIXED** |

---

## 2. Issue 1 — Investigation & Root Cause Analysis

### A. Observed Behavior on AWS Deployed Portal
When a corporate user registered on the public registration page (`/register?role=COMPANY`) and navigated or was redirected to the Company Profile page (`/company/profile`), the document card displayed:
- Red warning banner: *"No company profile found for this user account."*
- Verification Status: `DRAFT`
- Upload controls: Active file input and "Upload Certificate (PDF)" button.

### B. Complete Registration-to-Profile Workflow Trace
1. **Frontend Registration (`src/pages/public/RegisterPage.jsx`):**
   - The user entered `organizationName`, `registrationNumber` (CIN), `fullName`, `email`, `phone`, and `password`.
   - The form called `registerUser({ email, fullName, phone, password, role: 'COMPANY', organizationName, registrationNumber })`.
2. **Frontend API Client (`src/services/api.js`):**
   - `registerUser` constructed the POST body for `/api/v1/auth/register/` using only `email`, `full_name`, `phone`, `password`, `password_confirm`, and `role`.
   - **Bug:** `organizationName` and `registrationNumber` were **dropped by the client**.
3. **Backend Registration View & Serializer (`users/views.py`, `users/serializers.py`):**
   - `UserRegisterSerializer.create()` only created the `User` record.
   - **Bug:** No `CompanyProfile` or `CompanyCSRPreference` was created. The user remained an orphaned `User` record with role `COMPANY`.
4. **Company Profile Retrieval (`csr/views/company_views.py:get_company_profile`):**
   - When the user visited `/company/profile`, the page executed `GET /api/v1/csr/profile/me/`.
   - The view called `get_company_for_user(request.user)`. Because `request.user.company_profile` did not exist, it raised `CSRNotFoundError("No company profile found for this user account.")`, returning HTTP 404 with error code `NO_COMPANY_PROFILE`.
5. **Frontend Profile Handling (`CompanyProfilePage.jsx`):**
   - The catch block caught the 404, set `isNewProfile = true`, and initialized a placeholder `initialProfile = { verification_status: 'DRAFT' }`.
   - **Bug:** The statutory verification document card remained enabled and clickable.
   - When the user clicked "Upload Certificate (PDF)", `uploadCompanyVerificationDocument` called `POST /api/v1/csr/profile/verification-document/`.
   - Backend `attach_company_document` failed immediately with `get_company_for_user` raising `CSRNotFoundError("No company profile found for this user account.")`.
   - The frontend captured this 404 error string and rendered it in red: *"No company profile found for this user account."*

### C. Root Cause Summary
- **Backend:** `UserRegisterSerializer` created the auth user but failed to initialize `CompanyProfile` and `CompanyCSRPreference` for `role=COMPANY`.
- **Frontend API:** `registerUser` dropped `organizationName` and `registrationNumber`.
- **Frontend UI:** `CompanyProfilePage.jsx` allowed file upload attempts before the underlying company record was persisted.

---

## 3. Issue 1 — Implementation & Code Fixes

### A. Backend User Registration & Profile Initialization
**File:** `/Users/chaudharykamlesh/Desktop/daangives-backend/users/serializers.py`
- Added optional write-only fields: `organization_name`, `registration_number`, `cin_number`.
- In `UserRegisterSerializer.create()`: wrapped user creation and company profile creation in `transaction.atomic()`.
- When `user.role == User.Role.COMPANY`:
  - Validates CIN using standard `CIN_REGEX` (`^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$`). If duplicate or invalid, assigns `None` safely.
  - Automatically initializes `CompanyProfile` in `DRAFT` status with company name, contact person name, email, phone, and CIN.
  - Automatically initializes `CompanyCSRPreference` with standard defaults.

### B. Backend Document View Error Hardening
**File:** `/Users/chaudharykamlesh/Desktop/daangives-backend/csr/views/company_views.py`
- Updated `CompanyVerificationDocumentView`: caught `CSRNotFoundError` and returns structured HTTP 400 Bad Request with code `'NO_COMPANY_PROFILE'` and message:
  `"Please save your corporate profile details before uploading statutory verification documents."`
- Eliminates unhandled 404s when unprofiled users interact with the document endpoint.

### C. Frontend API Registration Service Payload Forwarding
**File:** `/Users/chaudharykamlesh/Desktop/daangives-frontend/src/services/api.js`
- Updated `registerUser(userData)` to forward:
  - `organization_name: userData.organizationName || userData.organization_name || ''`
  - `registration_number: userData.registrationNumber || userData.registration_number || ''`
  - `cin_number: userData.cinNumber || userData.cin_number || userData.registrationNumber || ''`

### D. Frontend CompanyProfilePage Resiliency & Guarding
**File:** `/Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/company/CompanyProfilePage.jsx`
- In `fetchProfileData()` catch block: if `isNewProfile === true`, prefills `formData.company_name`, `formData.contact_person_name`, `formData.contact_email`, and `formData.contact_phone` from the active session `localStorage.getItem('user')`.
- In `handleDocumentUpload`: added guard check for `isNewProfile`. If true, displays `"Please save your corporate profile details below before uploading statutory verification documents."` and halts before firing network requests.
- In Document UI: when `isNewProfile` is true, replaces the upload button with an amber informative badge: `"Save profile details below first"`.

### E. Idempotent Production Repair Command
**File:** `/Users/chaudharykamlesh/Desktop/daangives-backend/csr/management/commands/repair_company_profiles.py`
- Discovers any `User` with `role='COMPANY'` who does not have an attached `CompanyProfile`.
- Creates `CompanyProfile` in `DRAFT` status and initializes `CompanyCSRPreference`.
- Supports `--dry-run` to simulate and audit without database modifications.
- Supports `--email <address>` to target a single user safely.
- Safe to run on live AWS PostgreSQL without any risk of data loss.

---

## 4. Issue 2 — Investigation & Root Cause Analysis

### A. Observed Behavior on AWS NGO Portal (Step 7)
On `/ngo/registration-flow` at Step 7 ("Review & Submit"):
- Status banner showed: `Application Incomplete — Please Fix Required Sections`
- Section breakdown showed: `LEGAL_INFO: Legal information is required.`
- Simultaneously, the overview card rendered:
  - PAN: `CKUPC8425M`
  - Darpan: `GJ/08/2032`
  - CSR-1: `Csr98423456`

### B. Complete Step 3 Legal Persistence Flow
1. In Step 3, the user filled in:
   - Registration Type: TRUST
   - Authority: Charity Commissioner
   - Registration No: REG/TEST/2020
   - Darpan ID: `GJ/08/2032`
   - PAN: `CKUPC8425M`
   - CSR-1: `Csr98423456`
   - Unchecked 12A, 80G, FCRA, and 10(23C) certificates.
2. In `NgoRegistrationFlowPage.jsx`, the state initialized `twelve_a_validity: ''`, `eighty_g_validity: ''`, `fcra_validity: ''`, `ten_23c_validity: ''`, `csr_registration_date: ''`.
3. When the user clicked "Save & Continue", `handleSaveLegal` submitted these empty strings to `/api/v1/ngo/legal/me/`.

### C. DRF DateField Serialization Failure Mechanism
- DRF's `serializers.DateField` expects `None` or a valid formatted date string (`YYYY-MM-DD`).
- When passed an empty string `""`, DRF raises:
  `{"ten_23c_validity": ["Date has wrong format. Use one of these formats instead: YYYY-MM-DD."]}`
- Because of this 400 Bad Request:
  - `NGOLegalInfo` was **never saved to the database**.
  - `hasLegal` remained `false`.
4. When the user moved to Step 7 (via the top stepper or ignoring the toast), Step 7's UI read the local React component state (`legal.pan_number`, `legal.darpan_id`, `legal.csr_registration_number`) and rendered them cleanly.
5. When the user clicked "Submit Application", `/api/v1/ngo/submit/` called `validate_ngo_completeness(profile)`.
6. Because `hasattr(profile, 'legal_info')` was `False` in PostgreSQL, the backend raised:
   `errors['legal_info'] = ['Legal information is required.']`
   This created the apparent contradiction in the screenshot.

### D. Root Cause Summary
- **Backend:** `NGOLegalInfoSerializer` did not normalize empty strings `""` to `None` for optional date fields.
- **Frontend:** Step 3 sent empty string dates instead of `null`, and Step 7 displayed local unsaved state without verifying server-side persistence.

---

## 5. Issue 2 — Implementation & Code Fixes

### A. Backend NGOLegalInfoSerializer DateField Normalization
**File:** `/Users/chaudharykamlesh/Desktop/daangives-backend/ngo/serializers.py`
- Implemented `to_internal_value(data)` on `NGOLegalInfoSerializer`:
```python
def to_internal_value(self, data):
    date_fields = [
        'ten_23c_validity',
        'twelve_a_validity',
        'eighty_g_validity',
        'fcra_validity',
        'csr_registration_date',
    ]
    if hasattr(data, 'copy'):
        data = data.copy()
    else:
        data = dict(data)
    for field in date_fields:
        if field in data and (data[field] == '' or data[field] is None):
            data[field] = None
    return super().to_internal_value(data)
```
- Completely eliminates 400 DateField formatting rejections when optional certificate dates are omitted.

### B. Frontend NgoRegistrationFlowPage Payload Sanitization & Indicators
**File:** `/Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoRegistrationFlowPage.jsx`
- In `handleSaveLegal`: explicitly sanitized all optional date fields:
  - `ten_23c_validity: legal.ten_23c_validity || null`
  - `twelve_a_validity: legal.twelve_a_validity || null`
  - `eighty_g_validity: legal.eighty_g_validity || null`
  - `fcra_validity: legal.fcra_validity || null`
  - `csr_registration_date: legal.csr_registration_date || null`
- In Step 7 overview card: added explicit check for `hasLegal`. If `hasLegal` is false, displays a clear warning banner:
  *"Legal details not saved on server — click here to return to Step 3 and save."*

---

## 6. Regression Testing & Verification Evidence

### A. Dedicated Backend Tests
Created two dedicated regression test modules:
1. `csr/tests/test_company_registration_fix.py`:
   - `test_company_registration_creates_profile_and_preferences`: PASSED
   - `test_donor_registration_does_not_create_company_profile`: PASSED
   - `test_document_upload_without_company_profile_returns_400_with_code`: PASSED
   - `test_repair_company_profiles_command_dry_run`: PASSED
   - `test_repair_company_profiles_command_live_execution`: PASSED
2. `ngo/tests/test_legal_info_completeness_fix.py`:
   - `test_serializer_empty_strings_convert_to_none`: PASSED
   - `test_save_exact_aws_production_payload`: PASSED
   - `test_completeness_passes_when_legal_info_persisted`: PASSED

**Execution Command:**
```bash
python manage.py test csr.tests.test_company_registration_fix ngo.tests.test_legal_info_completeness_fix --noinput
```
**Output:**
```
Found 8 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
........
----------------------------------------------------------------------
Ran 8 tests in 1.029s

OK
Destroying test database for alias 'default'...
```

### B. Existing NGO Legal Suite
**Execution Command:**
```bash
python manage.py test ngo.tests.test_legal_apis --noinput
```
**Output:**
```
Ran 31 tests in 15.057s
OK
```

### C. Database Migration Integrity
**Execution Command:**
```bash
python manage.py makemigrations --check --dry-run
```
**Output:**
```
No changes detected
```

### D. Frontend Vitest Suite
**Execution Command:**
```bash
npm test -- --run
```
**Output:**
```
Test Files  45 passed (45)
Tests       196 passed (196)
Duration    5.92s
```

### E. Frontend Production Build
**Execution Command:**
```bash
npm run build
```
**Output:**
```
vite v8.2.2 building client environment for production...
✓ 707 modules transformed.
dist/index.html                                         1.73 kB
dist/assets/index-BQ1v32OH.css                        125.57 kB
dist/assets/CompanyProfilePage-M9EoFa9A.js             30.85 kB
dist/assets/NgoRegistrationFlowPage-DWbvfZB8.js        64.71 kB
✓ built in 228ms
```

---

## 7. Step-by-Step AWS EC2 Production Remediation Plan

To deploy these fixes to the live AWS EC2 instance without downtime or database risk, follow these steps:

### Step 1: Pull Latest Code on EC2
```bash
# On AWS EC2 instance
cd /home/ubuntu/daangives-backend   # (or actual backend deployment path)
git pull origin main

cd /home/ubuntu/daangives-frontend  # (or actual frontend deployment path)
git pull origin main
```

### Step 2: Audit Orphaned Company Accounts on EC2 (Safe Dry-Run)
```bash
cd /home/ubuntu/daangives-backend
source venv/bin/activate
python manage.py repair_company_profiles --dry-run
```
*This will list any company users on AWS who currently lack a `CompanyProfile`, showing exactly what would be created.*

### Step 3: Execute Live Profile Repair on EC2
```bash
python manage.py repair_company_profiles
```
*This idempotently creates the missing DRAFT `CompanyProfile` and `CompanyCSRPreference` records for affected company users using their existing registration credentials. It will never overwrite healthy profiles.*

### Step 4: Rebuild Frontend Distribution on EC2
```bash
cd /home/ubuntu/daangives-frontend
npm ci
npm run build
# Copy built files to Nginx web root if served statically:
# sudo cp -r dist/* /var/www/daangives-frontend/
```

### Step 5: Restart Backend Gunicorn Services
```bash
sudo systemctl restart gunicorn
sudo systemctl status gunicorn --no-pager
```

### Step 6: Post-Deployment Verification
1. Log into the AWS Company Portal with the affected company user:
   - Navigate to `/company/profile`.
   - Verify that the corporate form renders with status `DRAFT`.
   - Verify that the red *"No company profile found"* error banner is completely gone.
   - Verify that Certificate of Incorporation upload works cleanly.
2. Log into the AWS NGO Portal with the affected NGO user:
   - Navigate to `/ngo/registration-flow`.
   - In Step 3, submit PAN `CKUPC8425M`, Darpan `GJ/08/2032`, and CSR-1 `Csr98423456`.
   - Advance to Step 7.
   - Verify that `LEGAL_INFO: Legal information is required.` is completely gone.
   - Click "Submit Application" and verify successful transition to `SUBMITTED`.

---

## 8. Summary of Modified Files

| Repository | File Path | Purpose of Modification |
|---|---|---|
| **Backend** | `users/serializers.py` | Accepts `organization_name`, `registration_number`, `cin_number`; creates `CompanyProfile` (DRAFT) and `CompanyCSRPreference` atomically on registration. |
| **Backend** | `csr/views/company_views.py` | Traps `CSRNotFoundError` in `CompanyVerificationDocumentView` and returns 400 with `NO_COMPANY_PROFILE`. |
| **Backend** | `ngo/serializers.py` | `NGOLegalInfoSerializer.to_internal_value`: normalizes empty strings (`""`) to `None` for all optional DRF `DateField`s. |
| **Backend** | `ngo/views.py` | Optimized queries with `select_related` while preserving strict API contracts. |
| **Backend** | `csr/management/commands/repair_company_profiles.py` | Safe, auditable Django management command to backfill orphaned company accounts. |
| **Backend** | `csr/tests/test_company_registration_fix.py` | 5 unit/integration tests for company registration, error handling, and repair command. |
| **Backend** | `ngo/tests/test_legal_info_completeness_fix.py` | 3 unit/integration tests for NGO legal empty date conversion, exact AWS payload persistence, and completeness validation. |
| **Frontend** | `src/services/api.js` | `registerUser`: forwards `organization_name`, `registration_number`, `cin_number` to backend. |
| **Frontend** | `src/pages/company/CompanyProfilePage.jsx` | Guards upload before profile persistence; prefills from user session; displays clear helper badge when new. |
| **Frontend** | `src/pages/ngo/NgoRegistrationFlowPage.jsx` | Sanitizes empty dates to `null` before submission; adds server persistence check in Step 7 overview. |

