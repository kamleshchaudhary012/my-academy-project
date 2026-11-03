# DaanGives — Form CSR-1 / CRN Foundation Implementation Report

**Date:** October 23, 2026  
**Status:** Completed & Tested (Local Development)  
**Authority:** Ministry of Corporate Affairs (MCA), Companies (CSR Policy) Amendment Rules, 2021 (Rule 4(2))

---

## 1. Executive Summary

Based on the findings in `NGO_AUTOMATIC_VERIFICATION_READINESS_AUDIT.md`, the platform previously lacked any database fields, serializers, document types, form inputs, admin verification views, or tests for **MCA Form CSR-1 / CRN (CSR Registration Number)**.

Under Rule 4(2) of the Companies (Corporate Social Responsibility Policy) Rules 2014 (as amended in 2021), every implementing agency (Registered Public Trust, Registered Society, or Section 8 Company) seeking to undertake corporate CSR activities or receive corporate CSR funding must be registered with the central government in Form CSR-1 and possess a unique CSR Registration Number (CRN).

This task established the end-to-end CSR-1 / CRN foundation across backend and frontend systems without disrupting non-CSR charitable NGOs, without auto-approving or auto-rejecting entities, and while maintaining strict backward compatibility.

---

## 2. Changed Files & Modifications

### A. Backend (`daangives-backend`)

| File Path | Description of Changes |
| :--- | :--- |
| [`ngo/models.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/models.py) | • Added regex validator `validate_csr_number(value)` enforcing `^CSR\d{7,12}$`.<br>• Added fields `has_csr_1`, `csr_registration_number`, and `csr_registration_date` to `NGOLegalInfo`.<br>• Added `@property is_csr_eligible`: confirms Section 8/Trust/Society + CSR-1 + 12A + 80G.<br>• Updated `NGOLegalInfo.clean()` to mandate CRN when `has_csr_1=True`.<br>• Updated `NGOLegalInfo.save()` to normalize CRN to uppercase and trim spaces.<br>• Added `CSR_1_CERT = 'CSR_1_CERT'` to `NGODocument.DocumentType`. |
| [`ngo/services/submission_service.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/services/submission_service.py) | • Updated `validate_ngo_application_completeness`: when `legal.has_csr_1` is True, conditionally enforces `csr_registration_number` and active `CSR_1_CERT` certificate.<br>• Preserves non-CSR NGOs: NGOs not claiming CSR-1 are never blocked. |
| [`ngo/serializers.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/serializers.py) | • Added `has_csr_1`, `csr_registration_number`, `csr_registration_date`, and read-only `is_csr_eligible` to `NGOLegalInfoSerializer`.<br>• Enforced uppercase normalization in `to_internal_value` and verified status locking in `validate`.<br>• Added `has_csr_1` to `NGOPublicSerializer`. |
| [`ngo/migrations/0004_ngolegalinfo_csr_registration_date_and_more.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/migrations/0004_ngolegalinfo_csr_registration_date_and_more.py) | • Single Django migration applying the 3 legal info fields and extending document type enum choices. Applied cleanly to database. |
| [`ngo/tests/test_legal_apis.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/tests/test_legal_apis.py) | • Added 6 unit tests (tests 26–31) verifying CRUD, CRN regex validation, conditional field enforcement, org-type eligibility logic, and uppercase normalization. |
| [`ngo/tests/test_submission_apis.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/tests/test_submission_apis.py) | • Added 3 integration tests (tests 48–50) verifying application completeness blocks missing CSR certificate only when CSR-1 is claimed, and passes for non-CSR NGOs. |
| [`ngo/tests/test_admin_apis.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/tests/test_admin_apis.py) | • Added `test_09b_csr1_data_visible_in_admin_detail` verifying admin inspection endpoint displays CSR-1 fields and `is_csr_eligible`. |
| [`ngo/tests/test_public_apis.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/tests/test_public_apis.py) | • Updated `test_34_public_response_matches_public_serializer_schema` with `has_csr_1`.<br>• Added `test_34b_public_response_includes_has_csr_1`. |

---

### B. Frontend (`daangives-frontend`)

| File Path | Description of Changes |
| :--- | :--- |
| [`src/pages/ngo/NgoRegistrationFlowPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoRegistrationFlowPage.jsx) | • **Step 3 (Legal Info):** Added statutory checkbox "Has Form CSR-1 / CRN Registration", CRN input with formatting helper, date picker, and legal guidance notice.<br>• **Step 6 (Documents):** Dynamically includes `CSR_1_CERT` in upload list when `legal.has_csr_1` is true.<br>• **Step 7 (Review):** Displays CSR-1 status and CRN in Legal completeness review card. |
| [`src/pages/ngo/NgoProfilePage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoProfilePage.jsx) | • Added `CSR_1_CERT` label to `DOC_TYPE_LABELS`.<br>• Added Form CSR-1 / CRN status row with status indicator, CRN number, and registration date.<br>• Added CSR Funding Eligibility row showing Corporate CSR readiness. |
| [`src/pages/admin/AdminNgoVerificationPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/admin/AdminNgoVerificationPage.jsx) | • Verification table displays inline `CSR-1` badge next to Darpan ID.<br>• Tab C (Legal Information): Displays Form CSR-1 / CRN and statutory CSR grant eligibility indicator with criteria breakdown. |
| [`src/pages/public/NgoPublicProfilePage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/public/NgoPublicProfilePage.jsx) | • Added `CSR-1 Registered` badge to public NGO header when `has_csr_1=True`. |
| [`src/pages/public/NgoDirectoryPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/public/NgoDirectoryPage.jsx) | • Added `CSR-1` to the Compliance & Exemptions tags on public directory cards. |
| [`src/test/pages/Csr1CrnImplementation.test.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/test/pages/Csr1CrnImplementation.test.jsx) | • 5 new Vitest unit and integration tests covering registration flow, document handling, NGO profile, admin inspection, and public profile badges. |

---

## 3. Statutory Verification & Business Rules Enforced

1. **Format Validation:**
   - MCA CRNs must match the official pattern: `^CSR\d{7,12}$` (e.g., `CSR00012345`).
   - Normalizes automatically to uppercase and strips leading/trailing whitespace.
2. **Conditional Applicability (Non-Blocking Registration):**
   - CSR-1 registration is **optional** during initial NGO onboarding. Small village sansthas, community trusts, and general charitable societies can register, verify, and receive individual public donations without Form CSR-1.
   - If an NGO checks `has_csr_1 = True`:
     - `csr_registration_number` becomes mandatory.
     - `CSR_1_CERT` (Form CSR-1 Registration Certificate) becomes mandatory before final application submission.
3. **Statutory Corporate CSR Eligibility (`is_csr_eligible`):**
   - Per MCA Rule 4(2), an organization is eligible for Corporate CSR partnerships only if:
     1. `organisation_type` is `TRUST`, `SOCIETY`, or `SECTION_8`.
     2. `has_csr_1` is `True` and has a valid `csr_registration_number`.
     3. `has_12a` is `True` (Income Tax Section 12A/12AB registration).
     4. `has_80g` is `True` (Income Tax Section 80G tax exemption).
   - This prevents non-eligible entities from claiming corporate CSR grants while keeping the evaluation transparent to both NGO and platform administrators.
4. **Human-in-the-Loop Verification:**
   - Entering a CSR-1 number or uploading a certificate does **NOT** automatically approve or alter the NGO's verification status.
   - Preserves state compliance officers' manual review authority in the Admin Verification console.

---

## 4. Test Verification Results

### Backend (`daangives-backend`)
- **Django Migrations Check:**
  ```bash
  ./env_daan/bin/python manage.py makemigrations --check
  Output: No changes detected (OK)
  ```
- **Targeted Test Execution:**
  ```bash
  ./env_daan/bin/python manage.py test ngo.tests.test_legal_apis ngo.tests.test_submission_apis ngo.tests.test_admin_apis ngo.tests.test_public_apis
  Output: Ran 135 tests in 49.437s — OK (135/135 Passed)
  ```
- **Specific Test Breakdown:**
  - `ngo.tests.test_legal_apis`: 31/31 passed (including tests 26–31 for CSR-1 format, org-type eligibility, CRN normalization)
  - `ngo.tests.test_submission_apis`: 50/50 passed (including tests 48–50 for CSR-1 certificate validation)
  - `ngo.tests.test_admin_apis`: 14/14 passed (including test 09b for admin CSR-1 inspection)
  - `ngo.tests.test_public_apis`: 40/40 passed (including tests 34 and 34b for public serializer schema)

### Frontend (`daangives-frontend`)
- **CSR-1 Vitest Suite:**
  ```bash
  npx vitest run src/test/pages/Csr1CrnImplementation.test.jsx
  Output: 5 passed (5 tests) in 216ms
  ```
- **Full Frontend Regression Suite:**
  ```bash
  npx vitest run
  Output: 44 test files passed, 184 passed (184 tests) in 5.78s
  ```
- **Production Build:**
  ```bash
  npm run build
  Output: built in 310ms (0 errors)
  ```

---

## 5. Scope Boundaries Maintained

- **Local Development Only:** Zero deployments, zero production modifications.
- **No External Paid APIs:** Did not purchase API services or register external credentials.
- **No Database Resets:** Existing database records preserved with clean additive migrations (`0004`).
- **No Sensitive Crypto Modifications:** PAN and bank account encryption and masking logic remained untouched.
- **No Auto-Approvals:** Preserved existing state administrative workflows and verification history audit trails.

---

## 6. Remaining Work (Roadmap for Phase 8 / External Verification)

When authorized to integrate automated external verification providers (e.g., MCA V3 / Surepass / Karza / Setu):
1. Add environment variables for external provider API keys (`CSR1_VERIFY_API_KEY`, `CSR1_VERIFY_PROVIDER_URL`).
2. Implement a dedicated service `ngo/services/mca_service.py` to query MCA records by CRN number and match registered entity names against `NGOLegalInfo.legal_name`.
3. Store raw provider responses securely in `NGOVerificationHistory.metadata` with webhook/polling status transitions.
4. Add automated badge "MCA Verified" upon successful external API matching.
