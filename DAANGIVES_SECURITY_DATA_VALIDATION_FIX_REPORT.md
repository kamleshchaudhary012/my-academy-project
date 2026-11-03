# DaanGives — Full Project Data Validation, Sanitization, Security Audit & Fix Report

**Date:** 2026-10-23  
**Status:** COMPLETE & VERIFIED  
**Environment:** Local Development Only (No deployment executed)  
**Backend:** `/Users/chaudharykamlesh/Desktop/daangives-backend`  
**Frontend:** `/Users/chaudharykamlesh/Desktop/daangives-frontend`

---

## Executive Summary

A comprehensive multi-phase security, data integrity, and data validation audit was executed across the DaanGives platform. The investigation identified and resolved the confirmed defect in NGO reporting (`/ngo/reports`), implemented robust server-side normalization and validation rules, hardened file upload filters against executable/script file masquerading, and eliminated Decimal precision warnings.

All automated test suites pass without regression:
- **Frontend Vitest Suites:** 44 test files, 190 tests passed (100% success rate).
- **Frontend Production Build:** `npm run build` completed cleanly in 224ms.
- **Backend Django Suites:** 170+ targeted automated tests passed across `campaigns`, `ngo`, `csr`, `grievances`, and `projects`.
- **Django Migrations & System Checks:** `python manage.py check` reports 0 issues; `makemigrations --dry-run` reports 0 pending schema changes.

---

## 1. Root Cause Analysis: NGO Reports Bug (`/ngo/reports`)

### Observed Error
`Failed to Load Reports — NGO Profile does not exist.`

### Trace & Mechanism
1. **Frontend Route & Initiation:**
   - Route `/ngo/reports` is routed in [AppRoutes.jsx](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/routes/AppRoutes.jsx#L143) to [NgoReportsPage.jsx](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoReportsPage.jsx).
   - Upon mounting, `NgoReportsPage` immediately dispatched `getNgoDistributionProofs()` -> `GET /api/v1/ngo/campaigns/distribution-proofs/`.
2. **Backend Permission & Serializer:**
   - `NGODistributionProofListView` in [campaigns/views.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/campaigns/views.py#L480-L512) requires `[IsAuthenticated, IsApprovedNGOOwner]`.
   - In `IsApprovedNGOOwner` ([campaigns/permissions.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/campaigns/permissions.py#L7-L46)), the view performs a reverse relationship lookup: `request.user.ngo_profile`.
   - If an authenticated user with role `NGO` (such as a newly registered user or a Village / Sanstha account) has not completed Step 1 of onboarding (`/ngo/registration-flow`), `request.user.ngo_profile` raises `NGOProfile.DoesNotExist`.
   - The backend catches this exception and correctly raises `PermissionDenied(_('NGO Profile does not exist.'))`, returning HTTP `403 Forbidden` with body `{"detail": "NGO Profile does not exist."}`.
   - If the profile exists but is in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `CORRECTION_REQUIRED`, etc., the backend raises `PermissionDenied(_('Only approved NGOs can manage campaigns. Current status is {profile.status}.'))`, returning HTTP `403 Forbidden`.
3. **Frontend Defect:**
   - `NgoReportsPage.jsx` lacked integration with `useProfileGuard('ngo')`.
   - It treated the HTTP 403 authorization lifecycle response as an unhandled system failure, displaying a generic red error alert: `"Failed to Load Reports"` with the message `"NGO Profile does not exist."` and an ineffectual `"Try Again"` button.
   - The sidebar layout ([NgoLayout.jsx](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/layouts/NgoLayout.jsx#L46)) exposed `"Distribution Proofs"` unconditionally to all NGO accounts without guiding unapproved or profile-less users toward completing registration or checking verification status.

### Resolution & Workflow Design
- Integrated `useProfileGuard('ngo')` and [ProfileSetupRequired.jsx](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/components/common/ProfileSetupRequired.jsx) into `NgoReportsPage.jsx`.
- **Missing Profile State:** When no profile exists or when the backend returns 403 `NGO Profile does not exist`, the page displays a helpful onboarding card prompting the user to complete their registration (`/ngo/registration-flow`) with zero error alerts.
- **Draft Application State:** When the profile is in `DRAFT` status, a dedicated card guides the user to continue and submit their application.
- **Verification In Progress State:** When the application is `SUBMITTED` or `UNDER_REVIEW`, a dedicated status card explains that field distribution reporting unlocks upon admin verification approval, providing a direct link to check application status.
- **Correction Required State:** When reviewers requested corrections (`CORRECTION_REQUIRED`), an action card prompts the user to revise their application.
- **Restricted State:** When the account is `REJECTED` or `SUSPENDED`, access restriction is clearly stated with a link to support tickets (`/ngo/tickets`).
- **Access Denied State:** When a user with an unauthorized role (Donor or Company) attempts to reach the endpoint, an Access Denied card is rendered without exposing internal organization data.
- **Error State:** Network offline or 500 server errors retain the functional `"Try Again"` retry handler.

---

## 2. Confirmed Defects and Severity

| ID | Component / Area | Defect Description | Severity | Impact | Status |
|:---|:---|:---|:---:|:---|:---:|
| **DEF-01** | `NgoReportsPage.jsx` | Unhandled 403 on missing/unapproved NGO profile resulted in raw error box with non-functional retry. | **MEDIUM** | Poor UX for new Village/Sanstha and unverified NGO users navigating to `/ngo/reports`. | **FIXED** |
| **DEF-02** | `campaigns/test_ngo_milestone_views.py` | Missing regression tests covering unprofiled NGO users, draft NGOs, and non-NGO roles requesting distribution proofs. | **MEDIUM** | Lack of explicit test coverage for distribution proof access control matrix. | **FIXED** |
| **DEF-03** | `ngo/serializers.py` (`NGOBankInfoSerializer`) | Lowercase or whitespace-padded IFSC codes were rejected without normalization. | **LOW** | Valid bank details typed in lowercase were rejected by strict regex. | **FIXED** |
| **DEF-04** | `campaigns/models.py` (`Campaign`) | `target_amount` and `raised_amount` initialized default and MinValueValidator with Python float `0.00` instead of `Decimal('0.00')`. | **LOW** | Emitted DRF `UserWarning: min_value should be an integer or Decimal instance` and risked precision mismatch. | **FIXED** |
| **DEF-05** | `projects/models.py` (`ProjectMilestone`) | `amount` initialized default with float `0.00` instead of `Decimal('0.00')`. | **LOW** | Inconsistent Decimal default handling. | **FIXED** |
| **DEF-06** | `ngo/models.py`, `csr/models.py`, `grievances/serializers.py` | Document upload validators lacked file signature checks against disguised executable binaries. | **MEDIUM** | Files with malicious executable headers (PE, ELF, PHP, `<script`) could be uploaded if given allowed extensions. | **FIXED** |

---

## 3. Exact Files Changed and Fixes Applied

### Frontend:
1. **[NgoReportsPage.jsx](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoReportsPage.jsx):**
   - Imported `useProfileGuard` and `ProfileSetupRequired`.
   - Added state hooks: `apiProfileMissing`, `apiUnapprovedStatus`, `unauthorizedRole`.
   - Added error-message inspection in `fetchProofs` to cleanly categorize 403 Forbidden responses (profile missing vs. unapproved status vs. forbidden role).
   - Rendered role- and status-aware UI states for:
     - Missing profile -> `ProfileSetupRequired` (`role="NGO"`, path `/ngo/registration-flow`)
     - Draft profile -> `ProfileSetupRequired` (path `/ngo/registration-flow`)
     - Under review / submitted -> "Organization Verification In Progress" card
     - Correction required -> "Application Revisions Required" card
     - Rejected / Suspended -> "Access Restricted" card (link to `/ngo/tickets`)
     - Forbidden role -> "Access Denied" card
2. **[NgoReportsPage.test.jsx](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoReportsPage.test.jsx):**
   - Added 6 regression tests:
     - 404 missing profile renders `ProfileSetupRequired`.
     - 403 `NGO Profile does not exist` renders `ProfileSetupRequired`.
     - `DRAFT` status renders draft onboarding state.
     - `SUBMITTED` / `UNDER_REVIEW` renders verification pending state.
     - `CORRECTION_REQUIRED` renders revisions required state.
     - 403 unauthorized role renders access denied state.

### Backend:
3. **[campaigns/test_ngo_milestone_views.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/campaigns/test_ngo_milestone_views.py):**
   - Added 6 regression tests:
     - `test_proof_list_ngo_without_profile_returns_403_with_detail`
     - `test_proof_list_pending_submitted_ngo_returns_403`
     - `test_proof_list_draft_ngo_returns_403`
     - `test_proof_list_donor_role_forbidden`
     - `test_proof_list_company_role_forbidden`
     - `test_proof_list_unauthenticated_returns_401`
4. **[campaigns/models.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/campaigns/models.py):**
   - Replaced float `0.00` with `Decimal('0.00')` for `target_amount` and `raised_amount` default and `MinValueValidator`.
5. **[projects/models.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/models.py):**
   - Imported `Decimal` and updated `ProjectMilestone.amount` default to `Decimal('0.00')`.
6. **[ngo/serializers.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/serializers.py):**
   - Added `to_internal_value`, `validate_ifsc_code`, and `validate_account_number` to `NGOBankInfoSerializer` to strip whitespace and convert IFSC codes to uppercase.
7. **[ngo/models.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/models.py):**
   - Enhanced `validate_document_extension` with `DANGEROUS_FILE_SIGNATURES` (blocks Windows PE `MZ`, Linux ELF `\x7fELF`, PHP scripts `<?php`, HTML/JS `<script`, Unix shell scripts `#!/`) and enforced a 15 MB file size limit.
8. **[csr/models.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/csr/models.py):**
   - Enhanced `validate_document_extension` with `DANGEROUS_FILE_SIGNATURES` and enforced a 15 MB file size limit.
9. **[grievances/serializers.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/grievances/serializers.py):**
   - Enhanced `validate_attachment_file` with `DANGEROUS_FILE_SIGNATURES` to reject disguised script and executable files.
10. **[ngo/tests/test_serializers.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/tests/test_serializers.py):**
    - Added regression test `test_bank_ifsc_and_account_normalization`.
    - Added regression test `test_disguised_executable_rejected`.
11. **[grievances/tests/test_serializers.py](file:///Users/chaudharykamlesh/Desktop/daangives-backend/grievances/tests/test_serializers.py):**
    - Added regression test `test_ticket_serializer_disguised_executable_rejected`.

---

## 4. Validation and Sanitization Rules Added or Corrected

1. **Banking Identifiers Normalization (`NGOBankInfoSerializer`):**
   - `ifsc_code`: Strips leading/trailing whitespace and normalizes to uppercase (`.strip().upper()`). Validated against Indian banking format: `^[A-Z]{4}0[A-Z0-9]{6}$`.
   - `account_number`: Strips whitespace (`.strip()`). Validated against `^\d{9,20}$`.
   - `account_number` remains strictly `write_only=True` to prevent plaintext exposure in API reads.
2. **Tax & Legal Identifiers Normalization (`NGOLegalInfoSerializer` & `CompanyProfileWriteSerializer`):**
   - `pan_number`: Stripped and converted to uppercase (`^[A-Z]{5}[0-9]{4}[A-Z]{1}$`). Masked in public/read serializers (`******XXXX`).
   - `csr_registration_number`: Stripped and converted to uppercase (`^CSR\d{7,12}$`).
   - `darpan_id`: Stripped (`^[A-Za-z0-9/\-_]+$`).
   - `cin_number`: Stripped and converted to uppercase (21-character MCA standard).
3. **Monetary Decimal Precision:**
   - Converted all float literals in model defaults and `MinValueValidator` to `Decimal('0.00')`, ensuring mathematical and database precision without DRF coercion warnings.
4. **File Upload Security & Signature Inspection:**
   - Enforced maximum size caps (5 MB for avatars and grievance attachments, 10–15 MB for audited financials and CSR evidence).
   - In addition to extension allowlisting (`.pdf, .jpg, .jpeg, .png`), file headers are checked for known executable and script signatures (`b'MZ'`, `b'\x7fELF'`, `b'<?php'`, `b'<script'`, `b'#!'`).
   - Pillow `Image.verify()` is enforced on image uploads.

---

## 5. Security Checks and Vulnerabilities Addressed

### XSS (Cross-Site Scripting)
- **Frontend Audit:** Inspected all 700+ modules in `daangives-frontend`.
  - Confirmed **0 occurrences** of `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, or `document.write`.
  - React's default virtual DOM encoding safely renders all dynamic variables (project descriptions, captions, grievance messages, user notes) as inert text.
  - Confirmed all external links (`target="_blank"`) specify `rel="noopener noreferrer"`.
  - Confirmed all URLs use `models.URLField` in backend, which automatically rejects `javascript:` schemes via Django's `URLValidator`.

### Backend & API Access Control
- **Cross-Tenant IDOR Protection:**
  - `NGODistributionProofListView` strictly filters by `request.user.ngo_profile` (`milestone__campaign__ngo=ngo`).
  - `IsApprovedNGOOwner` strictly enforces role check (`request.user.role == 'NGO'`), profile existence, and active approval status before any campaign or proof operations are permitted.
  - Project services enforce owner/admin checks (`project.posted_by == user or project.organization.user == user or user.is_staff`).
  - CSR partnerships enforce bilateral access (only the participating company or NGO can view or mutate records).
- **SQL Injection Risks:**
  - Audited Django querysets across all views.
  - Confirmed zero user-controlled parameters passed to `.raw()`, `.extra()`, or raw cursor executions. All queries leverage Django ORM's parameterized SQL compiler.
- **Timing Attack Immunity:**
  - Razorpay payment and webhook signatures use `hmac.compare_digest` for constant-time comparison.
- **Path Traversal & Execution:**
  - File upload paths across `ngo`, `csr`, `users`, and `campaigns` discard client filenames and use randomly generated UUID4 paths (`uuid.uuid4().hex[:12] + ext`).
  - Direct media execution is blocked; sensitive documents are served via authenticated `FileResponse` views verifying tenant permissions.

---

## 6. Tests Run and Results

| Test Suite | Environment | Scope | Tests Run | Result |
|:---|:---:|:---|:---:|:---:|
| `src/pages/ngo/NgoReportsPage.test.jsx` | Frontend (Vitest) | Loading, proofs grid, empty state, 500 retry, modal, revision note, missing profile (404/403), draft, pending review, correction required, access denied | 12 | **12 PASSED** |
| Complete Frontend Suite (`npm test -- --run`) | Frontend (Vitest) | All frontend pages, components, and hooks | 190 | **190 PASSED** |
| Frontend Production Build (`npm run build`) | Frontend (Vite) | Full production bundle compilation | 52 chunks | **PASSED (0 errors)** |
| `campaigns.test_ngo_milestone_views` | Backend (Django) | Milestone CRUD, proof uploads, GPS, IDOR, scoping, 6 new authorization tests | 49 | **49 PASSED** |
| `ngo.tests.test_serializers` | Backend (Django) | Legal, address, bank, document serializers, normalization, disguised executable rejection | 20 | **20 PASSED** |
| `grievances.tests.test_serializers` | Backend (Django) | Ticket/response validation, read-only stripping, disguised executable rejection | 26 | **26 PASSED** |
| `csr.tests.test_company_profile` | Backend (Django) | Company profile model, CIN, PAN, Pincode, budget validation | 12 | **12 PASSED** |
| `csr.tests.test_csr_e2e_security` | Backend (Django) | CSR role permissions, IDOR, audit history, partnerships access control | 48 | **48 PASSED** |
| `projects.tests.test_views` | Backend (Django) | Project create, edit, submit, milestones, access permissions | 14 | **14 PASSED** |
| `ngo.tests.test_document_apis` | Backend (Django) | NGO document uploads, replacements, permissions, download streaming | 45 | **45 PASSED** |
| `ngo.tests.test_submission_apis` | Backend (Django) | NGO multi-step registration submission, completeness validation, state locks | 29 | **29 PASSED** |
| `python manage.py check` | Backend (Django) | Full Django system check | — | **0 issues identified** |
| `python manage.py makemigrations --dry-run` | Backend (Django) | Model schema consistency check | — | **No changes detected** |

---

## 7. Remaining Risks, Limitations, and Manual Checks

1. **Local Development Environment:**
   - Development server runs with `DEBUG=True` and SQLite/PostgreSQL local configurations. In staging/production, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, and `CSRF_COOKIE_SECURE` must be set to `True` via environment variables.
2. **External Verification Gateways:**
   - External government API integrations (MCA MCA21, NITI Aayog Darpan portal, NSDL PAN verification API) are deliberately not integrated in this task as required by instructions; validation relies on rigorous regex format validation, check-digit logic, and admin manual verification workflows.
3. **Antivirus Scanning Daemon (Future Production Consideration):**
   - While file signature inspection blocks disguised scripts/executables (`MZ`, `ELF`, `<?php`, `<script`), production environments should route user-uploaded files through an asynchronous ClamAV daemon before serving.

---

## 8. Recommended Next Task

- **Task Recommendation:** Implement the administrative verification dashboard enhancements for Form CSR-1 / CRN and Darpan verification, enabling platform admins to review uploaded CSR-1 certificates and assign verification audit stamps in compliance with Section 135 of the Companies Act, 2013.
