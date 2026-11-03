# DaanGives — NGO Portal Audit, Fix & Verification Report

**Date:** October 21, 2026  
**Environment:** Local Development  
**Frontend Path:** `/Users/chaudharykamlesh/Desktop/daangives-frontend`  
**Backend Path:** `/Users/chaudharykamlesh/Desktop/daangives-backend`  

---

## 1. Initial Audit Findings

A fresh, code-level re-audit of the NGO / Village / Sanstha Portal was conducted across the 10 specified areas prior to making any modifications.

### Audit Summary Matrix

| # | Inspection Area | Code Location | Initial Audit Observation | Status |
|---|-----------------|---------------|---------------------------|--------|
| 1 | `NgoDashboardPage.jsx` Missing Profile Handling | `src/pages/ngo/NgoDashboardPage.jsx` | Directly invoked `Promise.all([getNgoProfile(), ...])`. When an authenticated user logged in without an existing NGO profile (e.g. freshly registered), `getNgoProfile()` threw 404. The catch block populated `error` state, resulting in a blank dashboard layout with a raw red error banner (`"NGO profile not found."`) rather than rendering `<ProfileSetupRequired role="NGO" />`. | **Defect Confirmed (P1)** |
| 2 | `CreateProjectPage.jsx` Profile Guard | `src/pages/ngo/CreateProjectPage.jsx` | Completely lacked profile protection. Unprofiled NGO accounts could view, fill, and submit the proposal form, only failing late at API request submission with 400 Bad Request. | **Defect Confirmed (P1)** |
| 3 | Milestone Evidence Upload (Village Projects) | `src/pages/ngo/ProjectDetailPage.jsx` | Handled statutory document uploads (`DocumentUploadList`) and milestones (`MilestoneEditor`), but had no UI or modal to upload field execution photos or milestone evidence for `FUNDED` / `IN_PROGRESS` Village Projects. | **Defect Confirmed (P2)** |
| 4 | `ProjectPhoto` Model, Serializer & Endpoints | `projects/models.py`, `projects/views.py`, `projects/urls.py` | `ProjectPhoto` model existed in `models.py` (migrated in `0001_initial.py`) and was serialized in `ProjectDetailSerializer`, but views and URLs lacked upload (`POST /projects/<id>/photos/`) and delete (`DELETE /projects/<id>/photos/<photo_id>/`) endpoints. Services lacked `add_photo()` and `delete_photo()`. | **Defect Confirmed (P2)** |
| 5 | NGO Registration & Profile Completion | `src/pages/ngo/NgoRegistrationFlowPage.jsx`, `ngo/views.py` | 6-step registration flow (Basic Profile, Address, Legal, Banking, Leadership, Statutory Documents) is fully functional and guarded by backend status transitions (`DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`). | **Working as Expected** |
| 6 | Project Draft Editing, Submission & Resubmission | `projects/services.py`, `projects/views.py` | Draft creation, required-field checks, milestone definitions, document upload requirement (minimum 1 statutory doc), and submission/withdrawal logic all work properly. | **Working as Expected** |
| 7 | Status Transitions & Audit History | `ProjectVerificationHistory` | State machine transitions properly: `DRAFT` ↔ `SUBMITTED` → `UNDER_REVIEW` → `DOCS_PENDING` / `REJECTED` / `VERIFIED` → `FUNDED` → `IN_PROGRESS` → `COMPLETED`. Immutable audit logging tracks actor, timestamp, and notes. | **Working as Expected** |
| 8 | NGO Reports & CSR Partnerships | `NgoReportsPage.jsx`, `NgoCsrPartnershipsPage.jsx` | Distribution proofs and Section 135 CSR partnership workflows operate independently with verified permissions. | **Working as Expected** |
| 9 | Tenant Isolation & IDOR Protection | `projects/permissions.py`, `ngo/permissions.py` | Cross-organization access properly blocked; unauthorized users receive 403 Forbidden on other organizations' projects, documents, and banking records. | **Working as Expected** |
| 10 | Existing Test Suites & Migrations | Django backend & Vitest frontend | 410 Django backend tests and 168 frontend Vitest tests passed before changes. Zero pending unapplied migrations. | **Verified Clean Baseline** |

---

## 2. Confirmed Defects and Already-Working Features

### Confirmed Defects (Addressed in Scope)

1. **[P1] Missing Profile Guard on NGO Dashboard (`NgoDashboardPage.jsx`):**
   - *Expected:* When an NGO user accesses the dashboard without having completed an NGO profile, render `<ProfileSetupRequired role="NGO" />` inside the layout with a clear call-to-action redirecting to `/ngo/registration-flow`.
   - *Actual:* Directly requested profile/bank/address endpoints, caught 404, and rendered a raw error alert on an empty dashboard.
   - *Fix:* Integrated `useProfileGuard('ngo')` and rendered `<ProfileSetupRequired role="NGO" />` when `profileStatus === 'missing'`.

2. **[P1] Unprotected Create Project Page (`CreateProjectPage.jsx`):**
   - *Expected:* Village project proposal creation requires an established NGO profile. If no profile exists, prompt the user with `ProfileSetupRequired` before they invest time filling in village proposal details.
   - *Actual:* Rendered form without checks; failed only on draft submission.
   - *Fix:* Added `useProfileGuard('ngo')` and rendered `<ProfileSetupRequired role="NGO" title="NGO Profile Required to Post Projects" />` when missing.

3. **[P2] Missing Backend Endpoints for `ProjectPhoto` Upload & Delete:**
   - *Expected:* Authorized NGO representatives can upload and delete milestone evidence photos for funded village projects with file size (max 5MB), mime type (JPG, PNG, WebP), and status (`FUNDED`, `IN_PROGRESS`, `COMPLETED`) validation.
   - *Actual:* `ProjectPhoto` model existed, but no service methods, views, or URL routes existed to upload or delete photos.
   - *Fix:* Added `ProjectService.add_photo`, `ProjectService.delete_photo`, `ProjectService.list_photos`, `ProjectPhotoUploadView`, `ProjectPhotoDeleteView`, and URL patterns.

4. **[P2] Missing Village Project Milestone Evidence UI (`ProjectDetailPage.jsx`):**
   - *Expected:* Eligible Village Projects (`FUNDED`, `IN_PROGRESS`, `COMPLETED`) should display an evidence photo gallery with an upload modal for NGO owners.
   - *Actual:* Only statutory documents and milestones were displayed; no evidence photo gallery or upload modal was present.
   - *Fix:* Built `EvidencePhotoList.jsx`, integrated into `ProjectDetailPage.jsx`, and connected with `uploadProjectPhoto` and `deleteProjectPhoto` in `projects.js`.

### Already-Working Features Verified
- **NGO Multi-Step Registration:** 6 distinct sections with draft auto-saving, validation, document uploading (PDF/JPG/PNG), and final submission.
- **Project Proposal Submission:** Full validation requiring at least 1 uploaded statutory document (e.g. Panchayat resolution) before allowing status transition to `SUBMITTED`.
- **Administrative Project Verification:** Admin queue, `ADD_TO_VERIFY`, `REQUEST_CHANGES`, `REJECT` (with mandatory notes), and `VERIFY` (CSR Ready).
- **Tenant Isolation:** Rigorous IDOR protection across all project and NGO profile endpoints.
- **CSR Integration:** Milestone disbursement tracking and MoU evidence tracking under `/api/v1/csr/` remain completely intact.

---

## 3. Exact Files Changed and Explanation

### Frontend (`/Users/chaudharykamlesh/Desktop/daangives-frontend`)

1. **[`src/pages/ngo/NgoDashboardPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/NgoDashboardPage.jsx):**
   - Imported `useProfileGuard` and `ProfileSetupRequired`.
   - Replaced unhandled 404 error catch with `profileStatus === 'missing'` guard.
   - Renders `<ProfileSetupRequired role="NGO" />` inside `NgoLayout` when the NGO profile does not exist.

2. **[`src/pages/ngo/CreateProjectPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/CreateProjectPage.jsx):**
   - Integrated `useProfileGuard('ngo')` and `ProfileSetupRequired`.
   - Displays loading spinner while checking profile status.
   - Renders `<ProfileSetupRequired role="NGO" />` if status is `'missing'`, preventing unprofiled users from filling or submitting project drafts.

3. **[`src/services/api/projects.js`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/services/api/projects.js):**
   - Added `uploadProjectPhoto(projectId, formData)` (multipart POST to `/api/v1/projects/:id/photos/`).
   - Added `deleteProjectPhoto(projectId, photoId)` (DELETE to `/api/v1/projects/:id/photos/:photo_id/`).

4. **[`src/components/projects/EvidencePhotoList.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/components/projects/EvidencePhotoList.jsx) *(NEW)*:**
   - Responsive photo gallery displaying on-site milestone progress photos with captions and dates.
   - Lightbox modal for full-resolution inspection.
   - Upload evidence modal with client-side file format (JPG, PNG, WebP) and size validation (max 5MB).
   - Only enables upload actions for owner users on eligible projects (`FUNDED`, `IN_PROGRESS`, `COMPLETED`).
   - Handles loading states, delete confirmation, and parent refresh callbacks.

5. **[`src/pages/ngo/ProjectDetailPage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/ngo/ProjectDetailPage.jsx):**
   - Imported and rendered `EvidencePhotoList` component.
   - Tied photo updates into existing `fetchProject` refresh handler.

6. **[`src/test/pages/VillageProjects.test.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/test/pages/VillageProjects.test.jsx):**
   - Updated `CreateProjectPage` test to await async profile resolution.

7. **[`src/test/pages/ProfilePagesFix.test.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/test/pages/ProfilePagesFix.test.jsx):**
   - Added automated tests verifying `NgoDashboardPage` and `CreateProjectPage` render `ProfileSetupRequired` when `GET /api/v1/ngo/profile/me/` returns 404.

8. **[`src/test/pages/VillageProjectEvidence.test.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/test/pages/VillageProjectEvidence.test.jsx) *(NEW)*:**
   - 9 new unit tests verifying `EvidencePhotoList`: status eligibility checks, upload modal interactions, 5MB file size limits, extension validation, photo deletion, and permissions.

---

### Backend (`/Users/chaudharykamlesh/Desktop/daangives-backend`)

1. **[`projects/services.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/services.py):**
   - Added `ProjectService.add_photo(user, project_id, file_obj, caption)`:
     - Validates user ownership or admin privileges.
     - Enforces project status rule: only `FUNDED`, `IN_PROGRESS`, or `COMPLETED`.
     - Enforces file size limit: <= 5MB.
     - Enforces image extensions (`jpg`, `jpeg`, `png`, `webp`) and MIME types.
     - Creates and stores `ProjectPhoto`.
   - Added `ProjectService.delete_photo(user, project_id, photo_id)`:
     - Validates ownership and removes photo file from storage and database.
   - Added `ProjectService.list_photos(user, project_id)`.

2. **[`projects/views.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/views.py):**
   - Added `ProjectPhotoUploadView` (`GET`, `POST` with `MultiPartParser`, `FormParser`).
   - Added `ProjectPhotoDeleteView` (`DELETE`).
   - Imported `ProjectPhotoSerializer`.

3. **[`projects/urls.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/urls.py):**
   - Registered `path('<uuid:id>/photos/', ProjectPhotoUploadView.as_view(), name='project_photo_upload')`.
   - Registered `path('<uuid:id>/photos/<uuid:photo_id>/', ProjectPhotoDeleteView.as_view(), name='project_photo_delete')`.

4. **[`projects/tests/test_photo_evidence.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/projects/tests/test_photo_evidence.py) *(NEW)*:**
   - 10 automated test cases verifying authentication, IDOR prevention, status eligibility constraints, format/size validation, and deletion permissions.

---

## 4. API / Model / Migration Changes

- **Models:** Reused existing `ProjectPhoto` model in `projects/models.py`. No new model classes were needed.
- **Migrations:** None required (`makemigrations --check` returned `No changes detected`). The `ProjectPhoto` table was already created in `projects/migrations/0001_initial.py`.
- **API Endpoints:**
  - `GET  /api/v1/projects/<uuid:id>/photos/` — List evidence photos for project.
  - `POST /api/v1/projects/<uuid:id>/photos/` — Upload evidence photo (`file`, optional `caption`).
  - `DELETE /api/v1/projects/<uuid:id>/photos/<uuid:photo_id>/` — Delete evidence photo.
- **API Contracts:** `ProjectDetailSerializer` continues to return nested `photos` matching the frontend expectations.

---

## 5. Commands Executed and Actual Results

| Command Line | Directory | Result |
|--------------|-----------|--------|
| `./env_daan/bin/python manage.py makemigrations --check` | `daangives-backend` | `No changes detected` (Exit code 0) |
| `./env_daan/bin/python manage.py test projects.tests.test_photo_evidence` | `daangives-backend` | `Ran 10 tests in 3.640s. OK` (Exit code 0) |
| `./env_daan/bin/python manage.py test projects` | `daangives-backend` | `Ran 50 tests in 17.715s. OK` (Exit code 0) |
| `./env_daan/bin/python manage.py test ngo projects` | `daangives-backend` | `Ran 420 tests in 152.172s. OK` (Exit code 0) |
| `npm test -- src/test/pages/VillageProjects.test.jsx --run` | `daangives-frontend` | `19 passed (19 tests) in 624ms` (Exit code 0) |
| `npm test -- src/test/pages/ProfilePagesFix.test.jsx --run` | `daangives-frontend` | `14 passed (14 tests) in 991ms` (Exit code 0) |
| `npm test -- src/test/pages/VillageProjectEvidence.test.jsx --run` | `daangives-frontend` | `9 passed (9 tests) in 738ms` (Exit code 0) |
| `npm test -- --run` | `daangives-frontend` | `43 test files passed, 179 passed (179 tests) in 5.62s` (Exit code 0) |
| `npm run build` | `daangives-frontend` | Vite production bundle built successfully in 251ms (Exit code 0) |

---

## 6. Test Counts, Failures and Limitations

### Test Metrics
- **Backend Test Count:** 420 passed (370 in `ngo`, 50 in `projects`). 0 failures, 0 errors.
- **New Backend Tests:** 10 new tests in `projects/tests/test_photo_evidence.py`.
- **Frontend Test Count:** 179 passed across 43 test suites. 0 failures.
- **New Frontend Tests:** 9 new tests in `VillageProjectEvidence.test.jsx` + 2 new tests in `ProfilePagesFix.test.jsx`.
- **Frontend Production Build:** Successful (0 TypeScript/lint/bundler errors).

### Limitations
- The active SQLite/PostgreSQL development database was preserved strictly without running ad-hoc data deletion or injecting fake data. All test operations were performed using Django's isolated test database runner and Vitest's MSW in-memory mocks.

---

## 7. Manual Browser Checks

- **Automated Browser Subagent Attempt:**
  The subagent attempted automated navigation via Playwright. However, the environment's Playwright driver installation failed to download the arm64 driver binary due to 404 responses from the upstream azureedge mirrors (`https://playwright.azureedge.net/builds/driver/playwright-1.57.0-mac-arm64.zip`).
- **Dev Servers Status:**
  Both local development servers were confirmed running and healthy:
  - Frontend: `http://localhost:5173` (Vite dev server returning HTTP 200).
  - Backend: `http://localhost:8000/api/v1/` (Django dev server active).
- **Manual Verification Steps for Reviewer in Desktop Browser:**
  1. Open `http://localhost:5173/login` and log in with an NGO account.
  2. Navigate to `http://localhost:5173/ngo/dashboard`. If the account has no NGO profile, observe `<ProfileSetupRequired role="NGO" />`.
  3. Navigate to `http://localhost:5173/ngo/projects/create`. If the account has no NGO profile, observe `<ProfileSetupRequired role="NGO" />`.
  4. With an approved NGO account, navigate to an active project at `http://localhost:5173/ngo/projects/<id>`.
  5. If the project status is `FUNDED` or `IN_PROGRESS`, click "Upload Milestone Photo", select a JPG/PNG (< 5MB), enter a caption, and verify the photo appears in the evidence gallery and persists across reload.

---

## 8. Remaining NGO Portal Tasks and Dependencies

1. **Production CDN / S3 Storage Integration:**
   In local development, `file` fields upload to local `MEDIA_ROOT`. For production staging, configure AWS S3 or Cloudinary storage backend in `settings.py`.
2. **Admin-CSR Marketplace Milestone Sync:**
   Village project milestones and CSR disbursement milestones currently operate in coordinated but separate models (`projects.ProjectMilestone` and `csr.CSRMilestone`). The subsequent CSR marketplace phase will cross-link these two records once a project is formally partnered.
3. **Notification Hooks for Evidence Uploads:**
   Optional email / webhook notification to corporate partners when an NGO uploads milestone execution evidence.

---

## 9. Recommended Next Step

Proceed to **Phase 7.3 / CSR Marketplace Integration**:
Connect verified Village Projects (`status=VERIFIED`) with corporate requirements and partner matching workflows under `/csr/marketplace/`.
