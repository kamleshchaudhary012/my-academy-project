# DaanGives — CSR Eligibility Rules Compliance Audit Report

**Date:** October 25, 2026  
**Audit Scope:** READ-ONLY Compliance, Statutory Consistency & Architectural Audit  
**Target Repositories:**  
- Backend: `/Users/chaudharykamlesh/Desktop/daangives-backend`  
- Frontend: `/Users/chaudharykamlesh/Desktop/daangives-frontend`  
**Governing Statutory Framework:**  
- Ministry of Corporate Affairs (MCA), Companies Act, 2013 (Section 135)  
- Companies (Corporate Social Responsibility Policy) Rules, 2014, as amended by:  
  - Companies (CSR Policy) Amendment Rules, 2021 (Notification G.S.R. 43(E) dated 22 January 2021)  
  - Companies (CSR Policy) Amendment Rules, 2022 (Notification G.S.R. 715(E) dated 20 September 2022)  
  - Companies (CSR Policy) Amendment Rules, 2025 (effective 14 July 2025)  
- Income Tax Act, 1961 (Sections 11, 12A, 12AB, 80G, and Section 10(23C) sub-clauses (iv), (v), (vi), and (via))

---

## 1. Executive Summary

A comprehensive, evidence-based, read-only compliance audit was conducted across the existing NGO CSR-1/CRN eligibility logic in the DaanGives platform. 

The audit evaluated whether the implemented data models, business rules, serializers, submission workflows, admin verification tools, CSR marketplace matching engines, and public presentation layers accurately reflect applicable Indian CSR regulations, specifically addressing recent MCA and Income Tax amendments (including the MCA21 V3 web-based Form CSR-1 standards effective July 2025).

### Key Audit Findings

1. **False Negative Risk (Section 10(23C) Omission):**  
   The current implementation in `NGOLegalInfo.is_csr_eligible` strictly requires **both** `has_12a` and `has_80g`. Under Rule 4(1)(a) and Rule 4(1)(d) of the Companies (CSR Policy) Rules, entities exempted under sub-clauses (iv), (v), (vi), or (via) of Section 10(23C) of the Income Tax Act (e.g. universities, educational institutions, hospitals, and philanthropic funds) are statutorily eligible implementing agencies without Section 12A/12AB registration. DaanGives has no fields for Section 10(23C), incorrectly disqualifying eligible entities (**CONFIRMED DEFECT**).

2. **False Positive Risk (Missing 3-Year Track Record Enforcement):**  
   Rule 4(1)(d) mandates that independent implementing agencies must possess an "established track record of at least three years in undertaking similar activities." Although `NGOProfile.year_established` is captured during onboarding, `is_csr_eligible` completely omits any track-record or age check. A brand-new organization (0–2 years old) holding a CSR-1 number and provisional tax exemption is evaluated as `is_csr_eligible = True` (**CONFIRMED DEFECT**).

3. **End-to-End Enforcement Disconnect (Critical Bypass Gap):**  
   While `NGOLegalInfo.is_csr_eligible` exists as a Python `@property` and is surfaced in admin review screens, **it is not enforced anywhere in the `csr` or `projects` domain services**. In `csr/services/requirement_service.py`, `csr/services/support_request_service.py`, and `csr/services/partnership_service.py`, any NGO user whose `NGOProfile.status == APPROVED` (even a grassroots entity with `has_csr_1 = False`, an un-registered village sanstha, or an entity with `is_csr_eligible == False`) can create CSR proposals, get listed in the CSR Marketplace, receive corporate expressions of interest, sign bilateral corporate CSR partnerships, and have corporate off-platform disbursements recorded (**CONFIRMED DEFECT**).

4. **Conflation of Self-Declaration with Verified Compliance:**  
   The public directory card (`NgoDirectoryPage.jsx`) and public profile header (`NgoPublicProfilePage.jsx`) display a prominent "CSR-1 Registered" badge solely based on the NGO's self-declared `has_csr_1` boolean. There is no independent `is_csr_verified` status or external MCA21 API validation flag. Self-declaration, document upload, and administrative verification are improperly coupled (**CONFIRMED DEFECT**).

5. **Submission Blocker for Grassroots NGOs:**  
   In `NGODocument.REQUIRED_DOCUMENT_TYPES` and `ngo/services/submission_service.py`, `TWELVE_A_CERT` and `EIGHTY_G_CERT` are hardcoded as unconditionally mandatory for all NGOs attempting to submit an application (`DRAFT -> SUBMITTED`), even though `has_12a` and `has_80g` are voluntary for non-CSR charitable societies and village sansthas seeking general crowdfunding (**CONFIRMED DEFECT**).

---

## 2. Existing Implementation & Exact Code References

### 2.1 Model Layer: `NGOLegalInfo.is_csr_eligible` & Fields
- **File:** [`ngo/models.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/models.py)
- **Lines 500–506 (Organisation Type Enum):**
  ```python
  class OrgType(models.TextChoices):
      TRUST     = 'TRUST',     _('Public/Private Trust')
      SOCIETY   = 'SOCIETY',   _('Registered Society')
      SECTION_8 = 'SECTION_8', _('Section 8 Company')
      NPO       = 'NPO',       _('Not For Profit Organisation')
      OTHER     = 'OTHER',     _('Other')
  ```
- **Lines 623–642 (CSR-1 Fields):**
  ```python
  has_csr_1 = models.BooleanField(
      default=False,
      help_text=_('Whether the NGO holds an MCA Form CSR-1 registration / CSR Registration Number (CRN).'),
  )
  csr_registration_number = models.CharField(
      max_length=50,
      blank=True,
      default='',
      validators=[validate_csr_number],
      help_text=_('Form CSR-1 registration number (CRN) issued by MCA (e.g. CSR00012345). Required if has_csr_1=True. NGO+Admin only.'),
  )
  csr_registration_date = models.DateField(
      null=True,
      blank=True,
      help_text=_('Date of Form CSR-1 registration with MCA. Optional. NGO+Admin only.'),
  )
  ```
- **Lines 660–676 (Eligibility Property):**
  ```python
  @property
  def is_csr_eligible(self):
      """
      Determines statutory baseline eligibility for corporate CSR funding.
      Under MCA Rule 4(2) of Companies (CSR Policy) Rules:
      An implementing agency must be a Registered Trust, Society, or Section 8 Company,
      and must possess an MCA-issued CSR-1 Registration Number (CRN),
      and hold valid 12A and 80G tax exemptions.
      """
      eligible_org_types = {self.OrgType.TRUST, self.OrgType.SOCIETY, self.OrgType.SECTION_8}
      return bool(
          self.organisation_type in eligible_org_types
          and self.has_csr_1
          and self.csr_registration_number
          and self.has_12a
          and self.has_80g
      )
  ```
- **Lines 40–50 (CRN Regex Validator):**
  ```python
  def validate_csr_number(value):
      if not value:
          return
      if not re.match(r'^CSR\d{7,12}$', value.strip().upper()):
          raise ValidationError(
              _('Invalid CSR-1 registration number format. Expected format: CSR followed by 7 to 12 digits (e.g. CSR00012345).'),
          )
  ```

### 2.2 Serializers & Data Normalization
- **File:** [`ngo/serializers.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/serializers.py)
  - `NGOLegalInfoSerializer` (lines 72, 98, 102): exposes `is_csr_eligible` as `read_only=True`. Normalizes `csr_registration_number` to uppercase in `to_internal_value`. Enforces that `csr_registration_number` cannot be empty when `has_csr_1=True`.
  - `NGOPublicSerializer` (lines 530, 584–585): exposes `has_csr_1` to public directory consumers directly from `obj.legal_info.has_csr_1`.

### 2.3 Application Completeness & Document Enforcement
- **File:** [`ngo/services/submission_service.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/services/submission_service.py)
  - Lines 101–103: validates that if `legal.has_csr_1` is True, `csr_registration_number` must be populated.
  - Lines 143–155: dynamically appends `CSR_1_CERT` to required documents if `legal.has_csr_1` is True.
  - **Defect:** Lines 143 & `ngo/models.py:826–837`: `NGODocument.REQUIRED_DOCUMENT_TYPES` contains `TWELVE_A_CERT` and `EIGHTY_G_CERT` as hardcoded unconditionally required documents, preventing non-CSR charitable NGOs from submitting applications if they lack 12A/80G.

### 2.4 Admin Inspection & Review Screens
- **Backend:** [`ngo/admin_views.py:102–116`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/admin_views.py) (`NGOAdminDetailView` serializes full `NGOLegalInfo` including `is_csr_eligible`).
- **Frontend:** [`src/pages/admin/AdminNgoVerificationPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/admin/AdminNgoVerificationPage.jsx)
  - Lines 629–633: Queue table renders inline badge `<span className="bg-indigo-100 text-indigo-800">CSR-1</span>` whenever `ngo.legal_info?.has_csr_1` is True.
  - Lines 833–841: Tab C displays `is_csr_eligible` status with descriptive banner:  
    `✓ Eligible for Corporate CSR Funding (Trust/Society/Sec8 + CSR-1 + 12A + 80G)` vs  
    `⚠ Standard Donations Only (Not eligible for CSR grants until Trust/Society/Sec 8 + CSR-1 + 12A + 80G are satisfied)`.

### 2.5 CSR Connect Domain Services (`csr` App)
- **File:** [`csr/services/requirement_service.py:40–61`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/csr/services/requirement_service.py)
  ```python
  def _validate_ngo_user(user):
      ...
      if ngo_profile.status != NGOProfile.Status.APPROVED:
          raise CSROwnershipError("NGO account is not approved for CSR operations.", code="ngo_not_approved")
      if not getattr(ngo_profile, 'is_active', False):
          raise CSROwnershipError("NGO account is inactive.", code="ngo_inactive")
      return ngo_profile
  ```
  **Grave Disconnect:** Only checks `ngo_profile.status == APPROVED`. It does **not** check `ngo_profile.legal_info.is_csr_eligible` or `ngo_profile.legal_info.has_csr_1`!
- **File:** [`csr/services/verification_service.py:214–248`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/csr/services/verification_service.py)
  `approve_requirement()` transitions a proposal to `OPEN_FOR_CSR` without verifying the underlying organization's statutory CSR eligibility.
- **File:** [`csr/services/support_request_service.py:273–325`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/csr/services/support_request_service.py)
  `accept_support_request()` generates a bilateral `CSRPartnership` without verifying that the receiving entity holds a valid Form CSR-1 or is CSR eligible.
- **File:** [`csr/services/partnership_service.py:374–400`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/csr/services/partnership_service.py)
  `record_off_platform_disbursement()` allows recording corporate CSR financial disbursements to NGOs that do not meet Rule 4 criteria.

### 2.6 Projects Domain Services (`projects` App)
- **File:** [`projects/models.py:25`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/models.py)
  Defines `ProjectStatus.VERIFIED = 'VERIFIED', _('Verified & Ready for CSR')`.
- **File:** [`projects/services.py:482–532`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/services.py)
  `verify_project()` approves projects into `ProjectStatus.VERIFIED` without verifying whether `project.organization.legal_info.is_csr_eligible` is True.

---

## 3. Legal Requirements Mapped Against Current Code

| Statutory Requirement | Legal Authority & Section | DaanGives Implementation | Compliance Classification | Finding & Impact |
| :--- | :--- | :--- | :--- | :--- |
| **Mandatory Form CSR-1 Registration** | Rule 4(2), Companies (CSR Policy) Rules, 2014; effective 01/04/2021 | `has_csr_1` boolean, `csr_registration_number` charfield, regex `^CSR\d{7,12}$`, `CSR_1_CERT` doc | **COMPLIANT (Baseline)** | Captures MCA CRN format and certificate upload. |
| **Eligible Entity Structures** | Rule 4(1)(a), (b), (c), (d), Companies (CSR Policy) Rules, 2014 | `eligible_org_types = {TRUST, SOCIETY, SECTION_8}` | **POTENTIAL RISK** | Labels `TRUST` as `Public/Private Trust`. Private trusts are strictly ineligible under Section 135. Excludes Statutory Bodies. |
| **Income Tax Exemptions: 12A/12AB vs 10(23C)** | Rule 4(1)(a) & (d), amended via G.S.R. 715(E) (20/09/2022) & July 2025 Rules | Rigid `and self.has_12a and self.has_80g` | **CONFIRMED DEFECT** | Fails to recognize Section 10(23C) sub-clauses (iv), (v), (vi), (via). Excludes eligible universities, hospitals, and philanthropic trusts (False Negative). |
| **Section 80G Requirement** | Rule 4(1)(a) & (d) ("...registered under section 12A and approved under section 80G...") | Required for all `TRUST`, `SOCIETY`, `SECTION_8` | **COMPLIANT** for 12A route; **CONFIRMED DEFECT** when applied to 10(23C) entities | Entities under Section 10(23C) are exempt without needing separate 12A/80G. |
| **3-Year Track Record Rule** | Rule 4(1)(d), Companies (CSR Policy) Rules, 2014 | `year_established` stored in `NGOProfile`, but omitted in `is_csr_eligible` | **CONFIRMED DEFECT** | Newly created NGOs (<3 years old) not established by the donor or government are marked CSR-eligible (False Positive). |
| **Statutory / Government Entities** | Rule 4(1)(b) & (c), Companies (CSR Policy) Rules, 2014 | Not modeled in `OrgType`; no exemption logic | **REQUIRES LEGAL CONFIRMATION** | Bodies created by Acts of Parliament/State Legislature do not require 3-year track record or 12A/80G. |
| **Enforcement in CSR Project/Matching Lifecycle** | Section 135(5) Companies Act, 2013 | Completely absent in `csr/services/` and `projects/services/` | **CONFIRMED DEFECT** | Approved non-CSR NGOs can create proposals, be matched, and receive CSR funding (Direct Bypass). |
| **Verification vs Self-Declaration Distinction** | MCA Form CSR-1 V3 web-based portal rules (14/07/2025) | Public badges display based on self-declared `has_csr_1` | **CONFIRMED DEFECT** | Public and donors misled by self-declared status prior to audit/verification. |

---

## 4. Entity-Type Eligibility Matrix

Under Section 135 and Rule 4 of the Companies (CSR Policy) Rules, 2014 (as amended up to July 2025):

| Entity Type | CSR Eligibility Category | Statutory Prerequisite 1 | Statutory Prerequisite 2 | Form CSR-1 / CRN Required? | 3-Year Track Record Required? | Supported in DaanGives? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Section 8 Company (Independent)** | Rule 4(1)(d) | Registered under Section 12A/12AB **AND** approved under 80G, **OR** Section 10(23C) | Valid MCA Incorporation (CIN) | **YES** (Mandatory) | **YES** (At least 3 years) | **PARTIALLY** (Missing 10(23C) and 3-yr track record check) |
| **Registered Public Trust (Independent)** | Rule 4(1)(d) | Registered under Section 12A/12AB **AND** approved under 80G, **OR** Section 10(23C) | Registered under state trust law / Charity Commissioner | **YES** (Mandatory) | **YES** (At least 3 years) | **PARTIALLY** (Does not exclude private trusts; missing 10(23C) and 3-yr check) |
| **Registered Society (Independent)** | Rule 4(1)(d) | Registered under Section 12A/12AB **AND** approved under 80G, **OR** Section 10(23C) | Registered under Societies Registration Act, 1860 | **YES** (Mandatory) | **YES** (At least 3 years) | **PARTIALLY** (Missing 10(23C) and 3-yr track record check) |
| **Company-Established Non-Profit** | Rule 4(1)(a) | Registered under Section 12A/12AB **AND** 80G, **OR** Section 10(23C) | Established singly or jointly by funding corporate | **YES** (Mandatory) | **NO** (Exempt from 3-year track record) | **NO** (No relationship field linking corporate to founded foundation) |
| **Government-Established Non-Profit** | Rule 4(1)(b) | Established by Central Government or State Government | Public statutory charter / GO | **YES** (Mandatory) | **NO** (Exempt from 3-year track record) | **NO** (No category or flag) |
| **Statutory Entity / Body Corporate** | Rule 4(1)(c) | Established under an Act of Parliament or State Legislature | Legislative Act citation | **YES** (Mandatory) | **NO** (Exempt from 3-year track record & 12A/80G) | **NO** (Marked as `OTHER`, completely excluded) |
| **Private Family / Benevolent Trust** | Ineligible | Private trust under Indian Trusts Act, 1882 | Ineligible under Section 135 | Ineligible | Ineligible | **RISK** (Lumped under `TRUST` in UI/model) |
| **Village / Gram Sanstha (Informal)** | Ineligible | Not a registered Public Trust, Society, or Sec 8 Company | Local village committee / SHG | Ineligible for direct CSR grant | Ineligible | **CONFIRMED DEFECT** (Can be verified as "Ready for CSR" in `projects`) |

---

## 5. Confirmed Defects, False Positives & False Negatives

### Confirmed Defects (CD)

1. **CD-01: Enforcement Bypass in `csr` Domain Services**  
   - **Location:** `csr/services/requirement_service.py:45–53`, `csr/services/support_request_service.py:70–78`, `csr/services/partnership_service.py:97–100`  
   - **Nature:** Direct API or UI actions allow any `APPROVED` NGO to post CSR requirements, participate in bilateral CSR partnerships, and receive off-platform CSR disbursements even if `is_csr_eligible == False` or `has_csr_1 == False`.  
   - **Impact:** Corporates using DaanGives could unknowingly enter CSR partnerships with non-compliant entities, causing statutory violations under Section 135(5).

2. **CD-02: Premature Public Directory Badges Based on Self-Declaration**  
   - **Location:** `ngo/serializers.py:530, 584–585`, `NgoPublicProfilePage.jsx:198`, `NgoDirectoryPage.jsx:349`  
   - **Nature:** Directly exposes `has_csr_1` from `NGOLegalInfo` to public endpoints without checking whether the CSR-1 certificate has been audited or approved by administrators.  
   - **Impact:** Misrepresents non-verified organizations to external donors as "CSR-1 Registered".

3. **CD-03: Submission Wizard Blocks Legitimate Non-CSR NGOs (12A/80G Lock)**  
   - **Location:** `ngo/models.py:826–837` (`REQUIRED_DOCUMENT_TYPES`), `ngo/services/submission_service.py:143–163`  
   - **Nature:** Hardcodes `TWELVE_A_CERT` and `EIGHTY_G_CERT` as mandatory documents for all NGOs attempting to submit an application, preventing grassroots non-profits without tax exemptions from completing onboarding.  
   - **Impact:** Contradicts the platform's stated commitment to onboard community trusts and village sansthas for public crowdfunding.

4. **CD-04: Village Projects Verified as "Ready for CSR" Without CSR Eligibility**  
   - **Location:** `projects/services.py:482–532` (`verify_project`) & `projects/models.py:25`  
   - **Nature:** Admin verification changes project status to `VERIFIED` ("Verified & Ready for CSR") without verifying whether the posting organization possesses a verified CSR-1 or meets Rule 4 criteria.  
   - **Impact:** Village projects posted by non-eligible informal groups are showcased as CSR-ready.

### False Negative Eligibility Risks (FN)

1. **FN-01: Exclusion of Section 10(23C) Exempt Institutions**  
   - **Nature:** Universities, higher education institutes (Section 10(23C)(vi)), charitable hospitals (Section 10(23C)(via)), and approved funds (Section 10(23C)(iv)/(v)) holding valid CSR-1 numbers are excluded because `is_csr_eligible` requires `self.has_12a == True`.

### False Positive Eligibility Risks (FP)

1. **FP-01: Zero Check on 3-Year Track Record (Rule 4(1)(d))**  
   - **Nature:** An NGO established in 2025 or 2026 holding a CSR-1 number and provisional 12A/80G evaluates to `is_csr_eligible = True`. Under Rule 4(1)(d), it is prohibited from acting as an independent implementing agency until completing 3 years of operations.

2. **FP-02: Inability to Disqualify Private Trusts**  
   - **Nature:** `OrgType.TRUST` is defined as `Public/Private Trust`. If a private family trust registers, submits a provisional 12A order, and inputs a CRN, the system treats it as fully eligible.

---

## 6. Frontend / Backend Enforcement Gaps

```
+----------------------------------------------------------------------------------------------------+
|                                    DAANGIVES CSR ENFORCEMENT AUDIT                                 |
+----------------------------------------------------------------------------------------------------+
| Workflow Stage            | Frontend Representation           | Backend Model / Property | Service Enforcement |
+---------------------------+-----------------------------------+--------------------------+---------------------+
| 1. NGO Registration       | Checkbox + CRN text input         | Regex ^CSR\d{7,12}$      | Completeness only   |
| 2. Admin Review           | Tab C: "Eligible for CSR Funding" | Evaluates is_csr_eligible| Advisory only       |
| 3. Proposal Creation      | Unrestricted for all NGOs         | No check on eligibility  | MISSED (Open to all)|
| 4. Marketplace Discovery  | Shows all OPEN_FOR_CSR proposals  | No filter on CRN/eligibility| MISSED (No filter)|
| 5. CSR Partnership Setup  | Allows any approved NGO to accept | No check on eligibility  | MISSED (Bypass)     |
| 6. Off-Platform Disburse  | Records corporate payment         | No check on eligibility  | MISSED (Bypass)     |
| 7. Public Profile / Cards | Badges "CSR-1 Registered"         | Exposes raw self-declared| MISSED (No audit)   |
+----------------------------------------------------------------------------------------------------+
```

### Critical Gaps:
- **Gap 1 (View/Service Isolation):** `is_csr_eligible` is implemented solely on `NGOLegalInfo` as a read-only property. It is completely disconnected from `csr/services/` and `projects/services/`.
- **Gap 2 (Direct API Bypass):** A client can issue a `POST /api/v1/ngo/csr/requirements/` directly using standard NGO JWT credentials. As long as `NGOProfile.status == APPROVED`, the proposal is created regardless of whether `has_csr_1` is True or False.
- **Gap 3 (Admin Review Queue Bias):** In `AdminNgoVerificationPage.jsx:630`, the queue table displays `CSR-1` next to Darpan ID based on the NGO's initial form input, giving the reviewer the false impression that the organization is officially certified before documents are even inspected.

---

## 7. Existing Tests, Missing Tests & Actual Test Execution

### 7.1 Actual Executed Test Results (READ-ONLY Verification)

1. **Targeted Backend Legal & CSR-1 Test Suite:**
   - Command: `python manage.py test ngo.tests.test_legal_apis`
   - Result: **31 / 31 Passed (OK)** in 15.18s
   - Coverage: Tests 26–31 verify CRN storage, uppercase normalization, rejection of invalid CRN strings, locking after submission, and baseline `is_csr_eligible` computation.

2. **Targeted Backend Milestone & Reports Suite:**
   - Command: `python manage.py test campaigns.test_ngo_milestone_views`
   - Result: **49 / 49 Passed (OK)** in 22.41s
   - Coverage: Verified reverse profile lookup handling and status-aware error responses.

3. **Frontend CSR-1 Vitest Suite:**
   - Command: `npx vitest run src/test/pages/Csr1CrnImplementation.test.jsx`
   - Result: **5 / 5 Passed (OK)** in 991ms
   - Coverage: Verified Step 3 form inputs, Step 6 document list, profile display, admin inspection Tab C, and public profile badge.

### 7.2 Missing Test Coverage (High-Priority Test Gaps)

1. **CSR Proposal Creation Guard:** No automated test verifies that an NGO with `has_csr_1=False` or `is_csr_eligible=False` is rejected when calling `POST /api/v1/ngo/csr/requirements/`.
2. **CSR Partnership & EOI Guard:** No automated test verifies that an ineligible NGO is blocked from accepting support requests (`POST /api/v1/ngo/csr/support-requests/<id>/accept/`).
3. **Marketplace Ineligibility Filter:** No test verifies whether proposals from ineligible or deregistered NGOs are excluded from `GET /api/v1/csr/requirements/`.
4. **Section 10(23C) Permutations:** Zero tests for Section 10(23C) exemption handling.
5. **3-Year Track Record Guard:** Zero tests verifying rejection of implementing agencies under 3 years of age.
6. **False-Claim Public Badge Security:** Zero tests verifying that unapproved NGOs or NGOs with invalid certificates cannot present the `CSR-1 Registered` badge on public pages.

---

## 8. Prioritised Recommendations (P0 / P1 / P2)

### Priority P0 — Critical Legal Compliance & Anti-Bypass (Immediate Architectural Fixes)

1. **Enforce `is_csr_eligible` in CSR Service Layer:**  
   Update `csr/services/requirement_service.py` (`create_requirement` and `submit_requirement`) and `csr/services/support_request_service.py` (`accept_support_request`) to assert that the NGO holds valid statutory CSR eligibility before permitting proposal creation or bilateral partnership execution.
2. **Decouple Public Badges from Self-Declaration:**  
   Introduce an administrative verification flag `csr_verified` (or require `status == APPROVED` AND admin document approval) before rendering the `CSR-1 Registered` badge in `NGOPublicSerializer`, `NgoPublicProfilePage`, and `NgoDirectoryPage`.
3. **Fix Document Submission Blocker for Grassroots NGOs:**  
   Make `TWELVE_A_CERT` and `EIGHTY_G_CERT` in `NGODocument.REQUIRED_DOCUMENT_TYPES` conditional on `legal.has_12a` and `legal.has_80g`, matching the existing conditional implementation for `CSR_1_CERT` and `FCRA_CERT`.

### Priority P1 — Regulatory Accuracy (Rule 4 Alignment)

1. **Incorporate Section 10(23C) in `NGOLegalInfo`:**  
   Add fields `has_10_23c`, `ten_23c_subclause` (choices: iv, v, vi, via), `ten_23c_order_number`, and `ten_23c_validity`. Update `is_csr_eligible` to evaluate `(has_10_23c or (has_12a and has_80g))`.
2. **Incorporate 3-Year Track Record Check for Rule 4(1)(d):**  
   In `is_csr_eligible`, compute the entity's operational age from `profile.year_established` (or registration date) and require `age >= 3` for independent trusts, societies, and Section 8 companies.
3. **Clarify Trust Typology (Exclude Private Trusts):**  
   Update `OrgType.TRUST` label from `Public/Private Trust` to `Registered Public Charitable Trust` and add validation ensuring private trusts cannot claim CSR eligibility.
4. **Guard Project Status in `projects` App:**  
   In `projects/services.py:verify_project`, require `project.organization.legal_info.is_csr_eligible == True` before transitioning project status to `VERIFIED` ("Verified & Ready for CSR").

### Priority P2 — Enhanced Governance & Verification

1. **Model Government & Statutory Entities (Rule 4(1)(b) & (c)):**  
   Add `STATUTORY_BODY` and `GOVERNMENT_ENTITY` to `OrgType` with specialized eligibility rules bypassing the 3-year track record and 12A/80G requirements.
2. **External MCA21 V3 API Integration Readiness:**  
   Implement a background verification worker to validate entered CRNs directly against the MCA portal / authorized aggregator (Surepass/Setu/Karza) once credentials become available.

---

## 9. Smallest Safe Correction for Each Confirmed Defect

### Correction 1 (CD-01): Enforce CSR Eligibility in `requirement_service.py`
```python
# In csr/services/requirement_service.py -> _validate_ngo_user()
def _validate_ngo_user(user):
    ...
    if ngo_profile.status != NGOProfile.Status.APPROVED:
        raise CSROwnershipError("NGO account is not approved for CSR operations.", code="ngo_not_approved")
    
    # Smallest safe check: ensure statutory CSR eligibility
    legal = getattr(ngo_profile, 'legal_info', None)
    if not legal or not legal.is_csr_eligible:
        raise CSROwnershipError(
            "Organization does not meet statutory CSR eligibility requirements (Form CSR-1 / Section 135 criteria).",
            code="ngo_not_csr_eligible",
        )
    return ngo_profile
```

### Correction 2 (CD-02): Restrict Public CSR-1 Badge to Verified Entities
```python
# In ngo/serializers.py -> NGOPublicSerializer
def get_has_csr_1(self, obj):
    # Only expose CSR-1 badge if NGO is APPROVED and legal_info has valid CSR-1
    if obj.status != NGOProfile.Status.APPROVED:
        return False
    legal = getattr(obj, 'legal_info', None)
    return bool(legal and legal.has_csr_1 and legal.csr_registration_number)
```

### Correction 3 (CD-03): Make 12A and 80G Documents Conditional in `submission_service.py`
```python
# In ngo/models.py -> NGODocument
# Remove TWELVE_A_CERT and EIGHTY_G_CERT from REQUIRED_DOCUMENT_TYPES base list:
REQUIRED_DOCUMENT_TYPES = [
    DocumentType.TRUST_DEED,
    DocumentType.REGISTRATION_CERT,
    DocumentType.PAN_CARD,
    DocumentType.DARPAN_CERTIFICATE,
    DocumentType.AUDITED_FINANCIALS,
    DocumentType.BANK_PASSBOOK,
    DocumentType.CANCELLED_CHEQUE,
    DocumentType.REPRESENTATIVE_ID,
]
# In submission_service.py -> validate_ngo_completeness():
# Already contains conditional appends:
if legal.has_12a and NGODocument.DocumentType.TWELVE_A_CERT not in required_docs:
    required_docs.append(NGODocument.DocumentType.TWELVE_A_CERT)
if legal.has_80g and NGODocument.DocumentType.EIGHTY_G_CERT not in required_docs:
    required_docs.append(NGODocument.DocumentType.EIGHTY_G_CERT)
```

### Correction 4 (CD-04 & FP-01): Add Track Record and Section 10(23C) to `is_csr_eligible`
```python
# In ngo/models.py -> NGOLegalInfo
@property
def is_csr_eligible(self):
    eligible_org_types = {self.OrgType.TRUST, self.OrgType.SOCIETY, self.OrgType.SECTION_8}
    if self.organisation_type not in eligible_org_types:
        return False
    if not (self.has_csr_1 and self.csr_registration_number):
        return False
    
    # Tax exemption check: 10(23C) OR (12A AND 80G)
    has_10_23c = getattr(self, 'has_10_23c', False)
    tax_exempt = has_10_23c or (self.has_12a and self.has_80g)
    if not tax_exempt:
        return False
    
    # 3-year track record check (Rule 4(1)(d))
    current_year = timezone.now().year
    year_est = getattr(self.ngo, 'year_established', None)
    if year_est and (current_year - year_est < 3):
        return False
        
    return True
```

---

## 10. Official Source Links & Unresolved Legal Questions

### 10.1 Authoritative Statutory Sources
1. **Ministry of Corporate Affairs (MCA) — Section 135 & CSR Rules:**  
   - [Companies Act, 2013 — Section 135 (Corporate Social Responsibility)](https://www.mca.gov.in/Ministry/pdf/CompaniesAct2013.pdf)  
   - [Companies (CSR Policy) Amendment Rules, 2021 — Notification G.S.R. 43(E) dated 22 Jan 2021](https://www.mca.gov.in/Ministry/pdf/CSRAmendmentRules_22012021.pdf)  
   - [Companies (CSR Policy) Amendment Rules, 2022 — Notification G.S.R. 715(E) dated 20 Sept 2022](https://www.mca.gov.in/bin/ebook/dms/getdocument?doc=MTc5MTg1MTAx&docCategory=Notifications&type=open)  
   - [Companies (CSR Policy) Amendment Rules, 2025 — Notified July 14, 2025](https://www.mca.gov.in)  
   - [MCA e-Form CSR-1 Instruction Kit & Help Documentation](https://www.mca.gov.in/MinistryV2/companyformsdownload.html)
2. **Income Tax Department — Charitable Exemption Framework:**  
   - [Income Tax Act, 1961 — Section 12A / 12AB (Registration of Trusts)](https://incometaxindia.gov.in)  
   - [Income Tax Act, 1961 — Section 80G (Deductions on Donations)](https://incometaxindia.gov.in)  
   - [Income Tax Act, 1961 — Section 10(23C) Sub-clauses (iv), (v), (vi), and (via)](https://incometaxindia.gov.in)

### 10.2 Questions Requiring Confirmation from a Qualified Indian CSR / Legal Professional
1. **Handling of Provisional vs Final 12A/80G Approvals (Form 10AC):**  
   Under the Taxation and Other Laws (Relaxation and Amendment of Certain Provisions) Act, 2020, new non-profits receive provisional 3-year registrations (Form 10AC) before obtaining full 5-year regular registrations. Does possession of provisional 12A/80G fulfill Rule 4(1)(d) if the entity has separately operated for 3 years, or is regular approval required for corporate CSR eligibility?
2. **Status of State-Level Statutory Boards & Development Authorities:**  
   Should state statutory bodies (e.g. Gujarat Rural Development Agency, Forest Development Corporations) register on DaanGives as NGOs, or should they be onboarded via a distinct statutory authority role exempt from Form CSR-1?
3. **Company-Founded Foundations (Rule 4(1)(a)):**  
   If a participating CSR Company establishes a dedicated charitable foundation on DaanGives, can that foundation execute CSR activities for that company without fulfilling the 3-year track record, and how should this corporate linkage be verified on-platform?
