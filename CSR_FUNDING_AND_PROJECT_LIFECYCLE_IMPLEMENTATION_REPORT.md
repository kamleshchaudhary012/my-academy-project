# DaanGives — Phase 6: CSR Funding, Payment Tracking, MoU, Project Monitoring & Reporting Implementation Report

**Document Date:** October 28, 2026  
**Environment:** Local Development Only (`http://localhost:5173` / `http://localhost:8000`)  
**Backend:** `/Users/chaudharykamlesh/Desktop/daangives-backend`  
**Frontend:** `/Users/chaudharykamlesh/Desktop/daangives-frontend`  
**Delivery Scope:** Full bilateral CSR lifecycle: *Verified NGO → Approved CSR Company → Project Discovery → EOI → Partnership → MoU Execution → Funding Commitment → Direct Bank Transfer Tracking → Payment Confirmation → Project Milestones → Utilisation Evidence → Impact Reporting*.

---

## 1. Executive Summary & Implementation Inventory

Phase 6 completes the end-to-end operational lifecycle of the DaanGives CSR Connect platform. Under statutory Section 135 and Schedule VII rules, DaanGives enforces strict separation between information ledgering and financial custody. **All corporate funding transfers flow directly from the CSR Company's bank account to the NGO's verified bank account via NEFT/RTGS/IMPS. DaanGives holds zero funds, operates no escrow, and introduces no payment gateways.**

### Component Audit Inventory

| Component / Subsystem | Status | Audit Findings & Phase 6 Enhancements |
| :--- | :--- | :--- |
| **CSR Data Models (`CSRPartnership`, `CSRDisbursement`, `CSRExpense`, `PartnershipMilestone`, `CSRGrantChangeRequest`)** | `EXISTS` | Highly comprehensive relational design with DB check constraints, unique constraints, and indices in place. Zero schema migrations required. |
| **Direct Bank Transfer Ledger (`CSRDisbursement`)** | `PARTIALLY_IMPLEMENTED` | Existed in model & service layer, but frontend submitted field aliases (`payment_reference`, `disbursement_notes`) which were dropped by the backend serializer. Serializer now seamlessly maps aliases. Added terminal partnership guards. |
| **MoU & Partnership Document Workflow** | `PARTIALLY_IMPLEMENTED` | Corporate partner had an upload endpoint (`CompanyPartnershipUploadMouView`), but recipient NGOs lacked an equivalent endpoint. Activated bilateral symmetry by implementing `NgoPartnershipUploadMouView` and frontend document download/upload UI. |
| **Deliverable Evidence & Milestones** | `PARTIALLY_IMPLEMENTED` | Milestones existed but lacked evidence document download URLs, overdue tracking badges, and actor role enforcement. Enforced role separation: companies cannot submit deliverable evidence for NGOs, and NGOs cannot verify their own deliverables. |
| **Financial Reconciliation Dossier** | `EXISTS` | Robust multi-dimensional reconciliation in `financial_service.py`. Enriched with milestone audit history and strict status verification. |
| **Lifecycle Notifications** | `PARTIALLY_IMPLEMENTED` | Milestones and requirements had notifications; disbursement tracking lacked email templates and event handlers. Created HTML/plain-text email templates and wired notification handlers for disbursement events. |
| **Ground Expense & Invoice Utilisation** | `EXISTS` | Robust invoice tracking and admin/corporate review workflows existed in `CSRExpense` and `financial_service.py`. Added terminal partnership safety checks. |
| **Executive Dashboards & Analytics** | `PARTIALLY_IMPLEMENTED` | Metrics existed but needed clear factual separation between committed funding, reported bank transfers, verified transfers, acknowledged receipts, and ground expenditure. Updated Admin, Company, and NGO dashboards. |

---

## 2. Architecture & Design Principles

### 2.1 The Direct Bank Transfer Principle
1. **Zero Financial Custody:** DaanGives does not intermediate money. There is no Razorpay checkout, no wallet, and no escrow.
2. **Three-Way Handshake for Wire Transfers:**
   - **Step 1 (Corporate Wire):** CSR Company initiates an external wire from its corporate treasury to the NGO's verified bank account and records the transaction on DaanGives with the bank UTR reference, transfer date, and wire advice receipt.
   - **Step 2 (Evidence Review):** Authorised platform admin or designated reviewer validates the wire advice against corporate audit standards.
   - **Step 3 (Beneficiary Acknowledgement):** The recipient NGO verifies credit in its bank statement and explicitly confirms receipt (or raises a formal dispute with mandatory justification).
3. **Multi-Dimensional Financial Truth:**
   Platform reports track six distinct numbers rather than conflating them:
   - `Agreed Grant Commitment` (Legal obligation under signed MoU)
   - `Reported Corporate Wire` (Self-declared by Company)
   - `Admin-Verified Transfer` (Verified against bank transfer slip)
   - `NGO-Acknowledged Receipt` (Confirmed credited in NGO bank account)
   - `Reported Project Expense` (Ground expenditure claimed by NGO)
   - `Verified Eligible Expense` (Audited ground expenditure backed by invoices)

---

## 3. Detailed Phase 6 Enhancements

### 3.1 CSR Funding Commitment & Direct Bank Transfer Tracking
- **Serializer Compatibility:** Updated `CSRDisbursementCreateSerializer` to handle frontend alias fields `payment_reference` (mapping to `transfer_reference`) and `disbursement_notes` (mapping to `notes`).
- **Terminal Partnership Protection:** Added guards in `record_csr_disbursement` and `report_csr_expense` preventing any financial entries against `CANCELLED` or `TERMINATED` partnerships.
- **Mandatory Transfer Evidence:** Disbursement creation strictly enforces upload of bank transfer slips / UTR receipts.
- **Mandatory Dispute Justification:** Acknowledging disbursements with status `DISPUTED` requires explanatory notes in both backend service and frontend UI.

### 3.2 Bilateral MoU Workflow
- **Symmetric Upload:** Created `NgoPartnershipUploadMouView` (`/api/v1/ngo/csr/partnerships/<id>/upload-mou/`), enabling NGOs to upload the signed bilateral agreement and activate the partnership.
- **Downloadable Executed Documents:** Exposed `signed_mou_url` in `CSRPartnershipDetailSerializer` so both corporate and NGO teams can securely view and download executed contracts.
- **Frontend MoU Management:**
  - `NgoCsrPartnershipsPage.jsx` renders "Download Signed MoU (PDF)" when executed, and an "Upload Signed MoU (PDF)" file control when `PENDING_MOU`.
  - `CompanyPartnershipDetailPage.jsx` provides an immediate download link for the executed MoU.

### 3.3 Deliverable Milestones & Utilisation Evidence
- **Deliverable Proof Download:** Exposed `evidence_document_url` in `PartnershipMilestoneSerializer` and rendered downloadable links in frontend milestone cards.
- **Role Separation Safeguards:**
  - Corporate partners cannot submit milestone evidence on behalf of NGOs.
  - NGOs cannot approve or verify their own milestones.
- **Overdue Milestone Identification:** Added dynamic `is_overdue` boolean calculation based on `target_completion_date` and `status != VERIFIED`.

### 3.4 Email & In-App Notifications
- Added `CSRNotificationEventType` constants:
  - `CSR_DISBURSEMENT_REPORTED`
  - `CSR_DISBURSEMENT_ACKNOWLEDGED`
  - `CSR_DISBURSEMENT_DISPUTED`
  - `CSR_DISBURSEMENT_VERIFIED`
  - `CSR_DISBURSEMENT_REJECTED`
- Created responsive HTML and plain-text email templates in `csr/templates/emails/csr/`:
  - `disbursement_reported.html` & `.txt`
  - `disbursement_acknowledged.html` & `.txt`
  - `disbursement_reviewed.html` & `.txt`
- Transactional hooks dispatched via `transaction.on_commit` to guarantee no emails are dispatched on database rollback.

### 3.5 Executive Dashboards & Analytics
- **Admin Analytics (`AdminAnalyticsView`):** Aggregates across the entire platform:
  - `total_committed_funding`, `total_transfers_reported`, `total_transfers_verified`, `total_acknowledged_receipts`, `total_pending_acknowledgement`, `total_disputed_transfers`, `total_remaining_commitment`, `total_expenses_reported`, `total_expenses_verified`, `total_milestones`, `verified_milestones`.
- **Company Dashboard (`CompanyDashboardView`):** Tracks corporate commitments, disbursed wires, pending acknowledgements, disputed transfers, and remaining balance.
- **NGO Dashboard (`NgoDashboardView`):** Displays committed grant allocations, reported incoming wires, acknowledged receipts, and unspent balances.

---

## 4. Payment and MoU Status State Machines

### 4.1 Partnership Lifecycle
```
PENDING_MOU ──(Upload Executed MoU)──► ACTIVE ──(Milestones Met & Reconciled)──► COMPLETED
      │                                  │
      ├──(Mutual Termination)────────────┴──► TERMINATED / CANCELLED
```

### 4.2 Corporate Disbursement Wire Lifecycle
```
[External Bank Transfer: Company -> NGO Bank Account]
                        │
                        ▼
            PENDING_REVIEW (Reported by Company with UTR & Receipt)
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
        VERIFIED (Admin Verified)  REJECTED (Admin Rejected)
           │
           ▼
     PENDING_ACK (Waiting for NGO bank statement check)
           │
     ┌─────┴─────────────────────────┐
     ▼                               ▼
ACKNOWLEDGED (Credit confirmed)   DISPUTED (Discrepancy / Funds not received)
```

---

## 5. Security, Tenancy & IDOR Safeguards

1. **Strict Object-Level Tenancy (IDOR Prevention):**
   Every view retrieves objects strictly through `_is_partnership_participant(request.user, partnership)` or role-scoped queries (`company__user=request.user` or `ngo__user=request.user`). Third parties receive `404 Not Found` or `403 Forbidden`.
2. **Role Separation:**
   - Only NGOs can submit project expenses and milestone evidence.
   - Only Companies can report corporate wire disbursements and review milestone completion.
   - Only Admins can approve grant commitment modifications and verify disbursement slips.
3. **Statutory CSR Eligibility Enforcement:**
   Creating a CSR partnership commitment requires the NGO to possess verified CSR-1 registration, 12A/80G certification, and an approved profile.
4. **Data Isolation of Private Banking Credentials:**
   Company users can never view raw NGO bank credentials through API responses; fund transfers occur outside the platform using verified bilateral treasury instructions.

---

## 6. Files Changed or Added

### Backend Repository
- **Modified:**
  - `csr/serializers/financial_serializers.py` — Alias mapping in `CSRDisbursementCreateSerializer`.
  - `csr/serializers/partnership_serializers.py` — Added `signed_mou_url` to `CSRPartnershipDetailSerializer`.
  - `csr/serializers/milestone_serializers.py` — Added `evidence_document_url` and `is_overdue` to `PartnershipMilestoneSerializer`.
  - `csr/services/financial_service.py` — Terminal state guards, disbursement notifications, audit timeline enrichment.
  - `csr/services/milestone_service.py` — Role enforcement (anti-self-verification, anti-company-evidence-submission).
  - `csr/services/notification_service.py` — Added disbursement notification handlers and event dispatchers.
  - `csr/views/admin_views.py` — Enriched `AdminAnalyticsView`.
  - `csr/views/company_views.py` — Enriched `CompanyDashboardView`.
  - `csr/views/ngo_views.py` — Enriched `NgoDashboardView`, implemented `NgoPartnershipUploadMouView`.
  - `csr/ngo_urls.py` — Registered `csr-ngo-partnership-upload-mou`.
- **Created:**
  - `csr/templates/emails/csr/disbursement_reported.html` & `.txt`
  - `csr/templates/emails/csr/disbursement_acknowledged.html` & `.txt`
  - `csr/templates/emails/csr/disbursement_reviewed.html` & `.txt`
  - `csr/tests/test_funding_and_project_lifecycle.py` — 23 comprehensive automated tests.

### Frontend Repository
- **Modified:**
  - `src/services/api.js` — Added `uploadNgoPartnershipMou` method.
  - `src/pages/ngo/csr/NgoCsrPartnershipsPage.jsx` — Bilateral MoU upload/download buttons, milestone evidence links, dispute validation.
  - `src/pages/company/CompanyPartnershipDetailPage.jsx` — MoU download link, milestone deliverable evidence link.

---

## 7. Database Migrations Assessment

**Zero migrations required.**  
Running `python manage.py makemigrations --check` returned:
```
No changes detected
```
All required relational fields (`signed_mou_document`, `transfer_reference`, `evidence_document`, `review_status`, `ngo_acknowledgement_status`, `target_completion_date`, `completed_date`) were already modeled in `CSRPartnership`, `CSRDisbursement`, `CSRExpense`, `PartnershipMilestone`, and `CSRVerificationHistory`. Preserving existing database tables ensured zero data risk and full backward compatibility.

---

## 8. Test Execution and Verification Results

### 8.1 New CSR Funding & Project Lifecycle Test Suite
**Command:** `python manage.py test csr.tests.test_funding_and_project_lifecycle --keepdb`
**Result:** **23 / 23 Tests Passed (OK)** in 14.59s.

| Test Case | Scenario Verified | Status |
| :--- | :--- | :--- |
| `test_01` | Statutory CSR eligibility requirement for partnership creation | **PASSED** |
| `test_02` | Unapproved company cannot form CSR partnerships | **PASSED** |
| `test_03` | Minimum commitment bounds (₹1,000 threshold) | **PASSED** |
| `test_04` | Unauthorised user cannot propose grant commitment change | **PASSED** |
| `test_05` | Grant change requests enforce justifications and upper bounds | **PASSED** |
| `test_06` | Authorized admin can approve grant commitment change | **PASSED** |
| `test_07` | Tenancy isolation: NGO can view its own bank details; company cannot | **PASSED** |
| `test_08` | Company reports off-platform wire with UTR transfer reference | **PASSED** |
| `test_09` | Wire transfer evidence document (slip/receipt) is mandatory | **PASSED** |
| `test_10` | IDOR prevention: third-party company cannot report disbursement | **PASSED** |
| `test_11` | Admin reviews and verifies corporate wire transfer | **PASSED** |
| `test_12` | NGO acknowledges receipt after verifying bank credit | **PASSED** |
| `test_13` | NGO disputes unreceived bank transfer with mandatory justification | **PASSED** |
| `test_14` | Multi-tranche disbursements accumulate and track outstanding commitment | **PASSED** |
| `test_15` | Bilateral MoU upload activates partnership and exposes download URL | **PASSED** |
| `test_16` | NGO uploads executed bilateral MoU via dedicated API endpoint | **PASSED** |
| `test_17` | NGO submits milestone deliverable evidence and notes | **PASSED** |
| `test_18` | Company reviews and verifies deliverable milestone completion | **PASSED** |
| `test_19` | Anti-self-verification: NGO cannot verify its own milestones | **PASSED** |
| `test_20` | Financial reconciliation dossier aggregates multi-dimensional lifecycle | **PASSED** |
| `test_21` | Dashboard metrics cleanly separate committed, transferred, and acknowledged funds | **PASSED** |
| `test_22` | Admin analytics view calculates overall CSR project and funding metrics | **PASSED** |
| `test_23` | Terminal partnership states block further disbursement and expense reporting | **PASSED** |

### 8.2 Backend CSR Regression Test Suite
**Command:** `python manage.py test csr.tests.test_services_financial csr.tests.test_views_financial csr.tests.test_services_milestone csr.tests.test_ngo_csr_dashboard_bugfix csr.tests.test_views_ngo csr.tests.test_views_company csr.tests.test_csr_e2e_security --keepdb`  
**Result:** **164 / 164 Tests Passed (OK)**.

### 8.3 Frontend Automated Test Suite
**Command:** `cd daangives-frontend && npm test -- --run`  
**Result:** **45 / 45 Test Files Passed, 196 / 196 Tests Passed (OK)** in 5.77s.

### 8.4 Frontend Production Build
**Command:** `cd daangives-frontend && npm run build`  
**Result:** Build succeeded with **0 errors**.

---

## 9. Remaining Blockers & Out-of-Scope Items

1. **Banking Open APIs (Account Aggregator / Direct Webhooks):**
   Currently, corporate wire transfers are self-reported with UTR reference numbers and bank slips, and verified via beneficiary acknowledgement. Live bank-to-bank webhook integrations (e.g. ICICI Corporate E-Banking or HDFC Treasury API) require corporate banking credentials and are out-of-scope for local development.
2. **Aadhaar e-Sign / Digital Signature Certificate (DSC):**
   MoUs are currently executed offline and uploaded as signed PDF documents. Integration with an authorized e-Sign provider (e.g. Leegality / CDAC) is not implemented in this phase.
3. **Production Object Storage:**
   File attachments use local Django media storage in local development; production deployment requires configuration with private Amazon S3 / Google Cloud Storage buckets with signed expiration URLs.

---

## 10. Manual Browser Verification Guide

1. **MoU Bilateral Activation:**
   - Log in as NGO (`lead@vidya.example.org`) -> Navigate to `http://localhost:5173/ngo/csr/partnerships`.
   - On a `PENDING_MOU` partnership, click **"Upload Signed MoU (PDF)"**, select a signed contract PDF, and submit.
   - Verify partnership badge immediately transitions to `ACTIVE`.
   - Click **"Download Signed MoU (PDF)"** and verify document opens.
2. **Report Corporate Bank Transfer:**
   - Log in as Company (`csr_spoc@tatapower.com`) -> Navigate to `http://localhost:5173/company/csr/partnerships/<id>`.
   - Scroll to "Report Bank Transfer (NEFT/RTGS)", input UTR reference number (e.g. `AXISP00293849102`), transfer date, amount, and attach transfer slip PDF.
   - Submit and verify the disbursement appears in the ledger with badge `PENDING_REVIEW`.
3. **Admin Evidence Verification:**
   - Log in as Admin (`admin@daangives.org`) -> Navigate to `http://localhost:5173/admin/csr/oversight`.
   - Inspect reported disbursement, review attached wire slip, and click **"Verify Transfer"**.
   - Verify status updates to `VERIFIED`.
4. **NGO Receipt Confirmation:**
   - Return to NGO account -> Open the partnership detail view.
   - Notice the incoming transfer. Click **"Acknowledge Receipt"** with notes "Received in Axis Bank account".
   - Verify transfer status becomes `ACKNOWLEDGED`.
   - Test the dispute path: Click **"Dispute Transfer"**, enter required reason ("Payment not found in bank statement"), submit, and verify status updates to `DISPUTED`.
5. **Project Milestone Evidence & Review:**
   - In NGO view, find milestone in `PENDING_SUBMISSION`. Click **"Submit Deliverable Evidence"**, attach photo/report, enter notes, and submit. Status transitions to `SUBMITTED`.
   - In Company view, click **"Review Deliverable"** on the submitted milestone, enter review comments, and click **"Verify Milestone"**. Status transitions to `VERIFIED`.

---

## 11. Final Assessment

The complete DaanGives NGO-to-CSR lifecycle is fully operational and compliant with Indian CSR statutory governance. Bilateral commitments, external direct wire tracking, recipient acknowledgement, milestone deliverable verifications, and multi-dimensional financial reconciliation operate in complete alignment without touching escrow or platform-held funds.

