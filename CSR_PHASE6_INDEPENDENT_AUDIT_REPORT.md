# DaanGives — Phase 6 Independent Audit & End-to-End Validation Report

**Audit Date:** November 3, 2026  
**Auditor:** Independent Technical Auditor  
**Environment:** Local Development Only (`http://localhost:5173` / `http://localhost:8000`)  
**Backend:** `/Users/chaudharykamlesh/Desktop/daangives-backend`  
**Frontend:** `/Users/chaudharykamlesh/Desktop/daangives-frontend`  
**Deliverable File:** `CSR_PHASE6_INDEPENDENT_AUDIT_REPORT.md`  
**Previous Reference Document:** `CSR_FUNDING_AND_PROJECT_LIFECYCLE_IMPLEMENTATION_REPORT.md`

---

## Executive Summary & Final Verdict

**FINAL VERDICT: PASS — READY FOR LOCAL END-TO-END TESTING.**

An exhaustive independent technical audit was conducted across the backend services, serializers, models, views, templates, frontend components, and database integrity constraints. All statutory CSR funding, payment tracking, bilateral MoU execution, deliverable milestone evidence, and multi-dimensional financial reconciliation workflows are robustly implemented and strictly isolated.

### Key Statutory and Financial Audit Highlights:
1. **Zero Financial Custody (Direct Bank Transfer Rail):** The platform manages legal commitments, bank transfer references (UTR), transfer slips, verification workflows, and beneficiary confirmations without touching customer funds. No payment gateways (Razorpay/Stripe), escrow accounts, wallets, or platform-held monies are introduced.
2. **Multi-Dimensional Financial Decoupling:** The platform strictly enforces mathematical and logical separation between *Committed Funding* $\neq$ *Reported Corporate Wire* $\neq$ *Admin-Verified Transfers* $\neq$ *NGO-Acknowledged Receipts* $\neq$ *Ground Expenses*.
3. **Disputed Payment Isolation:** Disputed transfers are rigorously quarantined and never counted towards acknowledged receipts or reconciliation.
4. **Tenant Isolation & Role Safeguards:** Cross-tenant IDOR attacks are blocked at service and view layers. NGOs cannot verify their own deliverables; corporate sponsors cannot submit deliverable evidence on behalf of NGOs.
5. **Concurrency & Atomicity:** Database row locking (`select_for_update()`) and atomic transactions protect financial totals from race conditions.

---

## 1. Financial Integrity Audit

| Check Description | Audit Verdict | Inspected Files & Functions | Actual Evidence / Test Details |
| :--- | :---: | :--- | :--- |
| **1.1 Committed funding separated from reported transfers** | **PASS** | `csr/services/financial_service.py` (`calculate_partnership_financial_status`), `csr/models.py` (`CSRPartnership.agreed_funding_amount`) | Committed funding is immutable to transfer reports. Verified in `test_01` and `test_09`: Agreed commitment remained ₹5,00,000 while reported transfers accumulated independently. |
| **1.2 Reported transfers separated from Admin-verified transfers** | **PASS** | `csr/services/financial_service.py` (`review_csr_disbursement`), `csr/models.py` (`CSRDisbursementReviewStatus`) | Transfers initially enter `PENDING_REVIEW`. `total_verified_disbursement` sums only where `review_status == 'VERIFIED'`. Unreviewed transfers do not increase verified balances. |
| **1.3 Admin-verified transfers separated from NGO-confirmed receipts** | **PASS** | `csr/services/financial_service.py` (`acknowledge_csr_disbursement`), `csr/models.py` (`CSRNgoAcknowledgementStatus`) | Admin verification does not imply beneficiary credit. NGO must explicitly acknowledge. `total_acknowledged_receipt` sums only where `ngo_acknowledgement_status == 'ACKNOWLEDGED'`. |
| **1.4 Ground expenses tracked independently** | **PASS** | `csr/models.py` (`CSRExpense`), `csr/services/financial_service.py` (`report_csr_expense`, `review_csr_expense`) | Ground project expenses and invoice vouchers are ledgered in `CSRExpense` with separate categories and invoice duplicate detection (`duplicate_invoice`). |
| **1.5 Multiple instalments calculate correctly** | **PASS** | `csr/services/financial_service.py` (`record_csr_disbursement`, lines 138-144) | Tranches accumulate atomically using `Sum('amount')`. Tested with 3 tranches (₹1.5L, ₹2L, ₹1.5L); cumulative reported sum equaled ₹5,00,000. |
| **1.6 Remaining commitment balances accurate** | **PASS** | `csr/services/financial_service.py` (line 748) | Outstanding commitment is derived as `max(Decimal('0.00'), committed_amount - total_verified_disbursement)`. Never goes negative. |
| **1.7 Duplicate UTR references handled safely** | **PASS** | `csr/services/financial_service.py` (lines 106-114) | Re-submission of an identical non-rejected UTR within the partnership raises `CSRValidationError(code="duplicate_transfer_reference")`. Submissions with rejected status can be corrected. |
| **1.8 Terminal partnerships reject prohibited transactions** | **PASS** | `csr/services/financial_service.py` (`record_csr_disbursement`, `report_csr_expense`, `create_grant_change_request`) | `CANCELLED` and `TERMINATED` partnerships reject disbursements, expenses, and grant change requests with `CSRStateError(code="invalid_partnership_state")`. |
| **1.9 Concurrency & race condition safety** | **PASS** | `csr/services/financial_service.py` (lines 91-95) | Calls execute inside `with transaction.atomic():` and acquire exclusive row locks using `CSRPartnership.objects.select_for_update()`. Prevents lost updates during parallel transfers. |
| **1.10 Decimal-safe arithmetic** | **PASS** | `csr/services/financial_service.py`, `csr/serializers/financial_serializers.py` | All calculations use `Decimal` with 2 decimal places. Floating-point types are strictly prohibited in financial math. |

---

## 2. Payment Security Audit

| Check Description | Audit Verdict | Inspected Files & Functions | Actual Evidence / Test Details |
| :--- | :---: | :--- | :--- |
| **2.1 Only correct CSR Company can report transfers** | **PASS** | `csr/services/financial_service.py` (`_is_company_participant`, lines 59-65), `csr/views/financial_views.py` (`CSRPartnershipDisbursementListView`) | Third-party company `attacker@rivalcorp.com` attempting to report transfer on Tata Steel's partnership was rejected with `CSRUnauthorizedError`. |
| **2.2 Only associated NGO can confirm receipt or dispute** | **PASS** | `csr/services/financial_service.py` (`_is_ngo_participant`, lines 68-74), `csr/views/financial_views.py` (`CSRDisbursementAcknowledgeView`) | Rival NGO `attacker@otherngo.org` attempting to acknowledge or dispute a transfer was blocked with `CSRUnauthorizedError`. |
| **2.3 Only authorised Admin users can review transfers** | **PASS** | `csr/services/financial_service.py` (`review_csr_disbursement`, lines 178-179) | Non-admin users attempting to review wire evidence are blocked with `admin_required`. |
| **2.4 Private payment evidence isolation** | **PASS** | `csr/models.py` (`disbursement_evidence_doc_path`), `csr/views/financial_views.py` (lines 88-90) | Document paths use unguessable UUIDs (`csr_docs/disbursements/<id>/<uuid>.pdf`). Direct API endpoints return `404 Not Found` for unauthorized tenants. |
| **2.5 Uploaded proof does not imply confirmed payment** | **PASS** | `csr/services/financial_service.py` (`calculate_partnership_financial_status`) | New transfers enter `PENDING_REVIEW` and `PENDING_ACKNOWLEDGEMENT`. Dossier categorizes them as unverified and unacknowledged. |
| **2.6 No fake bank verification claimed** | **PASS** | `daangives-frontend/src/pages/company/CompanyPartnershipDetailPage.jsx` (line 1139) | Explicit notice to users: *"System status of 'Evidence Reviewed' reflects documentary audit of bank advice counterfoils on file, not automated bank API rail confirmation."* |
| **2.7 Direct bank transfer model preserved** | **PASS** | Whole repository audit | Zero payment gateways, Razorpay APIs, or escrow holding logic found. Funds flow strictly corporate bank $\rightarrow$ NGO bank. |

---

## 3. MoU & Partnership Document Workflow Audit

| Check Description | Audit Verdict | Inspected Files & Functions | Actual Evidence / Test Details |
| :--- | :---: | :--- | :--- |
| **3.1 NGO & Company upload permissions** | **PASS** | `csr/views/company_views.py` (`CompanyPartnershipUploadMouView`), `csr/views/ngo_views.py` (`NgoPartnershipUploadMouView`) | Bilateral symmetry: Both company and NGO can upload the executed bilateral MoU to activate the partnership. |
| **3.2 Document download permissions** | **PASS** | `csr/serializers/partnership_serializers.py` (`CSRPartnershipDetailSerializer.get_signed_mou_url`), `daangives-frontend/src/pages/company/CompanyPartnershipDetailPage.jsx` | `signed_mou_url` is exposed through authenticated participant-scoped detail views. |
| **3.3 Partnership ownership & tenancy** | **PASS** | `csr/services/partnership_service.py` (`_is_participant`, lines 37-47) | Non-participants attempting to activate or upload an MoU receive `CSRNotFoundError`. |
| **3.4 Audit history & document tracking** | **PASS** | `csr/services/partnership_service.py` (lines 237-244) | Every MoU upload logs a `CSRAuditEntityType.PARTNERSHIP` record in `CSRVerificationHistory` with timestamp and actor ID. |
| **3.5 MoU signing representation** | **PASS** | `csr/serializers/partnership_serializers.py`, frontend pages | Clearly documented: System records offline executed agreement; does not claim digital e-Sign or DSC verification. |
| **3.6 Funding actions follow MoU rules** | **PASS** | `csr/services/partnership_service.py` (`create_partnership_from_request`, `activate_partnership`) | Status progression strictly enforces `PENDING_MOU` $\rightarrow$ `ACTIVE`. Financial disbursements cannot precede partnership agreement. |

---

## 4. Milestones and Deliverable Evidence Audit

| Check Description | Audit Verdict | Inspected Files & Functions | Actual Evidence / Test Details |
| :--- | :---: | :--- | :--- |
| **4.1 NGO can submit evidence only for own project** | **PASS** | `csr/services/milestone_service.py` (`get_milestone`, `_is_milestone_participant`) | Participant scoping restricts milestone access strictly to the owning NGO and corporate partner. |
| **4.2 Company cannot submit evidence on behalf of NGO** | **PASS** | `csr/services/milestone_service.py` (lines 213-216) | Explicit check: Corporate partner attempting to call `submit_evidence` raises `CSRUnauthorizedError(code="unauthorized_submitter")`. |
| **4.3 Anti-Self-Verification: NGO cannot verify own deliverables** | **PASS** | `csr/services/milestone_service.py` (lines 269-272) | Explicit check: Executing NGO attempting to verify its own milestone raises `CSRUnauthorizedError(code="unauthorized_reviewer")`. |
| **4.4 Overdue milestone calculation** | **PASS** | `csr/serializers/milestone_serializers.py` (`get_is_overdue`, lines 87-90) | Verified in `test_09`: Milestones where `status != VERIFIED` and `target_completion_date < today` evaluate `is_overdue = True`. |
| **4.5 Evidence file privacy** | **PASS** | `csr/models.py` (`milestone_evidence_doc_path`), `csr/services/milestone_service.py` | Media stored under unguessable UUID directory tree; URLs served only to authenticated participants. |

---

## 5. Notifications and Reporting Audit

| Check Description | Audit Verdict | Inspected Files & Functions | Actual Evidence / Test Details |
| :--- | :---: | :--- | :--- |
| **5.1 Correct notification recipients** | **PASS** | `csr/services/notification_service.py` (`notify_disbursement_reported`, `notify_disbursement_acknowledged`, `notify_disbursement_reviewed`) | `CSR_DISBURSEMENT_REPORTED` targets NGO (`lead@vidya.example.org`); `CSR_DISBURSEMENT_ACKNOWLEDGED` targets Company (`csr_lead@tatasteel.com`). |
| **5.2 Zero cross-tenant leakage** | **PASS** | `csr/services/notification_service.py`, `csr/templates/emails/csr/` | Email context contains only project title, partnership link, and UTR. No passwords, private tokens, or sensitive bank account details are exposed. |
| **5.3 Financial dashboard calculations match database** | **PASS** | `csr/views/admin_views.py` (`AdminAnalyticsView`), `csr/views/company_views.py` (`CompanyDashboardView`), `csr/views/ngo_views.py` (`NgoDashboardView`) | Verified in `test_12`: Admin analytics, Company dashboard, and NGO dashboard derive metrics via pure SQL aggregates matching database rows. |
| **5.4 Disputed transfers excluded from confirmed receipts** | **PASS** | `csr/services/financial_service.py` (`calculate_partnership_financial_status`, lines 734-735, 766-768) | Disputed transfers are isolated in `total_disputed_receipt` and strictly excluded from `total_acknowledged_receipt`. |
| **5.5 Committed, transferred, verified, acknowledged & spent amounts distinct** | **PASS** | `csr/services/financial_service.py` (`get_partnership_reconciliation_dossier`) | All 6 quantities are reported as distinct keys in the API response with independent aggregate queries. |

---

## 6. End-to-End Test Execution Results

### 6.1 Test Setup & Local Test Accounts
All tests were executed against the local PostgreSQL test database using dedicated local accounts:

| Role | Account Name | Email Address | Statutory Verification State |
| :--- | :--- | :--- | :--- |
| **Platform Administrator** | CSR Oversight Staff | `platform_admin@daangives.org` | Active Staff / Superuser |
| **Recipient NGO** | Vidya Foundation | `lead@vidya.example.org` | Approved, 12A/80G, CSR-1 Verified |
| **Corporate CSR Partner** | Tata Steel CSR Trust | `csr_lead@tatasteel.com` | Approved MCA CIN/PAN |
| **Rival NGO (Attacker)** | Rival NGO | `attacker@otherngo.org` | Approved (Different Tenant) |
| **Rival Company (Attacker)** | Rival Corp | `attacker@rivalcorp.com` | Approved (Different Tenant) |
| **Unapproved Company** | Pending Corp | `pending_comp@example.com` | Pending Verification |
| **CSR-Ineligible NGO** | Ineligible NGO | `ineligible_ngo@example.org` | Missing CSR-1 & Tax Exemption |

---

### 6.2 Test Matrix: `csr.tests.test_phase6_independent_audit`

**Command:**
```bash
python manage.py test csr.tests.test_phase6_independent_audit --keepdb
```

**Results:** **12 / 12 Tests Passed (OK in 7.769s)**

```
Found 12 test(s).
Using existing test database for alias 'default'...
System check identified no issues (0 silenced).
..........INFO 2026-11-03 13:38:17,869 notification_service CSR Notification dispatched successfully. Subject='Corporate Bank Transfer Reported - CSR Initiative a67c62', Recipient='lead@vidya.example.org'
INFO 2026-11-03 13:38:17,875 notification_service CSR Notification dispatched successfully. Subject='NGO Receipt Update: ACKNOWLEDGED - CSR Initiative a67c62', Recipient='csr_lead@tatasteel.com'
..
----------------------------------------------------------------------
Ran 12 tests in 7.769s

OK
Preserving test database for alias 'default'...
```

#### Individual Test Case Results:
1. `test_01_complete_e2e_csr_funding_and_reporting_journey`: **PASS**  
   *Verified complete 11-step journey: NGO Project Creation $\rightarrow$ Corporate EOI $\rightarrow$ Partnership Formation $\rightarrow$ MoU Activation $\rightarrow$ Bank Transfer Reporting $\rightarrow$ Admin Evidence Verification $\rightarrow$ NGO Bank Credit Confirmation $\rightarrow$ Deliverable Evidence Submission $\rightarrow$ Corporate Review $\rightarrow$ Reconciliation Dossier.*
2. `test_02_negative_unapproved_company_cannot_execute_csr_commitments`: **PASS**  
   *Unapproved company blocked from forming partnership (`code="company_not_approved"`).*
3. `test_03_negative_ineligible_ngo_cannot_form_csr_partnership`: **PASS**  
   *Ineligible NGO without CSR-1/12A/80G blocked from partnership (`code="ngo_csr_ineligible"`).*
4. `test_04_negative_cross_tenant_idor_reporting_and_acknowledgement`: **PASS**  
   *Rival company cannot report disbursements; rival NGO cannot acknowledge transfers; dossier access blocked.*
5. `test_05_negative_sub_zero_amount_and_duplicate_utr_handling`: **PASS**  
   *Zero/negative amounts rejected; duplicate UTR within partnership blocked (`code="duplicate_transfer_reference"`).*
6. `test_06_negative_disputed_payment_workflow_and_receipt_isolation`: **PASS**  
   *Disputed transfer flags status `DISPUTED`; disputed funds excluded from confirmed receipts; dispute without reason rejected.*
7. `test_07_milestone_role_separation_safeguards`: **PASS**  
   *Corporate partner cannot submit deliverable evidence; NGO cannot review its own deliverable.*
8. `test_08_terminal_partnership_blocks_prohibited_transactions`: **PASS**  
   *Terminated partnership rejects disbursements, expenses, and grant change requests (`code="invalid_partnership_state"`).*
9. `test_09_multiple_instalments_and_overdue_milestones`: **PASS**  
   *3 tranches (₹1.5L, ₹2L, ₹1.5L) track distinct statuses; overdue milestone dynamically flags `is_overdue = True`.*
10. `test_10_transactional_concurrency_and_audit_history`: **PASS**  
    *Sequential disbursements lock partnership row and write audit history with actor ID and metadata.*
11. `test_11_notification_privacy_and_isolation`: **PASS**  
    *Notifications routed strictly to intended bilateral partners; zero credential leakage in email payloads.*
12. `test_12_dashboard_and_analytics_kpi_consistency`: **PASS**  
    *Admin analytics, Company dashboard, and NGO dashboard return non-conflated metrics matching database.*

---

## 7. Full Regression Test Verification

### 7.1 Backend Phase 6 Lifecycle Test Suite
**Command:**
```bash
python manage.py test csr.tests.test_funding_and_project_lifecycle --keepdb
```
**Result:** **23 / 23 Tests Passed (OK in 14.503s)**

### 7.2 Backend CSR Domain Regression Suite
**Command:**
```bash
python manage.py test csr.tests.test_services_financial csr.tests.test_views_financial csr.tests.test_services_milestone csr.tests.test_ngo_csr_dashboard_bugfix csr.tests.test_views_ngo csr.tests.test_views_company csr.tests.test_csr_e2e_security csr.tests.test_csr_e2e_lifecycle --keepdb
```
**Result:** **165 / 165 Tests Passed (OK in 64.930s)**

### 7.3 Django System & Migration Checks
**Commands:**
```bash
python manage.py check
python manage.py makemigrations --check
```
**Results:**
- `System check identified no issues (0 silenced).`
- `No changes detected` (100% schema preserved, 0 unapplied migrations).

### 7.4 Frontend Vitest Suite
**Command:**
```bash
cd daangives-frontend && npm test -- --run
```
**Result:** **45 / 45 Test Files Passed, 196 / 196 Tests Passed (OK in 5.90s)**

### 7.5 Frontend Production Build
**Command:**
```bash
cd daangives-frontend && npm run build
```
**Result:** **Built successfully in 255ms with 0 errors.**

---

## 8. Manual Browser Verification Guide (Local Development)

To test through the browser at `http://localhost:5173` and `http://localhost:8000`:

### Step 1: NGO Bilateral MoU Execution
1. Log in as NGO lead (`lead@vidya.example.org`).
2. Navigate to `http://localhost:5173/ngo/csr/partnerships`.
3. Locate the partnership in `Pending MoU` status.
4. Click **"Upload Signed MoU (PDF)"**, select any PDF agreement, and submit.
5. **Expected Result:** The partnership status badge transitions from `Pending MoU` to `Active / Signed`, and the **"Download MoU"** button appears.

### Step 2: Corporate Bank Transfer Reporting (Direct Wire)
1. Log in as Company CSR manager (`csr_lead@tatasteel.com`).
2. Navigate to `http://localhost:5173/company/csr/partnerships/<id>`.
3. Under the Financial Tracking card, click **"Report Bank Transfer (NEFT/RTGS)"**.
4. Enter Amount (e.g. `200000.00`), UTR Number (`AXISP00293849102`), Mode (`RTGS`), Date, and attach bank transfer slip.
5. Click **"Submit Transfer Advice"**.
6. **Expected Result:** Transfer appears in the ledger with badge `Pending Admin Review`. Cumulative reported disbursed increases by ₹2,00,000, while verified and acknowledged amounts remain ₹0.

### Step 3: Admin Wire Evidence Review
1. Log in as Admin (`platform_admin@daangives.org`).
2. Navigate to `http://localhost:5173/admin/csr/oversight`.
3. Under Disbursements, locate the reported wire and review the attached transfer slip.
4. Click **"Verify Transfer"** with review notes.
5. **Expected Result:** Disbursement status updates to `Verified`.

### Step 4: NGO Bank Credit Confirmation & Dispute
1. Return to NGO session (`http://localhost:5173/ngo/csr/partnerships`).
2. Click **"Acknowledge Receipt"**, attach optional receipt slip, and submit.
3. **Expected Result:** Disbursement status updates to `Acknowledged`. Acknowledged receipts balance updates to ₹2,00,000.
4. **Dispute Test:** On a separate reported tranche, click **"Dispute Transfer"**, enter required reason (*"Funds not found in account"*), and submit.
5. **Expected Result:** Status updates to `Disputed`. A warning banner appears on both Company and NGO consoles.

### Step 5: Deliverable Milestone Evidence & Review
1. In NGO view, locate Milestone 1 (`Pending Submission`).
2. Click **"Submit Deliverable Evidence"**, attach progress PDF, enter notes, and submit. Status transitions to `Submitted`.
3. In Company view, click **"Review Deliverable"** on Milestone 1. Click **"Verify Milestone"**. Status transitions to `Verified`.

---

## 9. Security & Risk Analysis

| Risk Category | Inherent Risk | Implemented Control | Residual Risk |
| :--- | :--- | :--- | :---: |
| **Financial Escrow & Regulatory** | Severe | Platform holds ₹0 and operates zero payment gateways. Funds transfer directly via bank-to-bank NEFT/RTGS. | **NONE** |
| **Cross-Tenant IDOR** | High | All view handlers and service functions enforce object-level tenancy checks (`_is_partnership_participant`). Unauthorised access returns 404 or 403. | **LOW** |
| **Self-Verification Fraud** | High | Service-level rules prevent NGOs from verifying their own deliverables and companies from reporting deliverables for NGOs. | **LOW** |
| **Double-Spending / Duplicate UTR** | Medium | Duplicate UTR submissions within a partnership are blocked unless the prior record was formally rejected. | **LOW** |
| **Concurrency / Lost Updates** | Medium | Atomic transactions and row locking (`select_for_update`) ensure cumulative disbursements recalculate without race conditions. | **LOW** |
| **Document Privacy** | Medium | Media uploaded to unguessable UUID directory tree; URLs accessible only via authenticated participant-scoped queries. | **LOW** |

---

## 10. Final Audit Conclusion

The Phase 6 implementation of DaanGives CSR Connect is technically sound, secure, and compliant with statutory Section 135 principles. The platform successfully supports the full operational journey from project discovery to bilateral MoU execution, direct corporate bank transfer tracking, administrative verification, beneficiary receipt confirmation, deliverable milestone auditing, and multi-dimensional financial reconciliation.

