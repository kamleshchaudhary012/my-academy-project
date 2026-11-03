# DaanGives — Grievance Attachment PDF 404 Resolution Report

**Date:** October 12, 2026  
**Repositories:**
- Frontend: `/Users/chaudharykamlesh/Desktop/daangives-frontend`
- Backend: `/Users/chaudharykamlesh/Desktop/daangives-backend`

---

## 1. Root Cause of the 404

### Primary Cause
When a grievance ticket detail was requested from `/api/v1/grievances/tickets/<id>/`, Django REST Framework's `GrievanceTicketDetailSerializer` was instantiated **without passing the serializer context** (`context={'request': request}`). 
Without the request in context:
- `serializers.FileField` on `attachment` serialized as a raw relative path:
  `"/media/grievance_attachments/DaanGives_Receipt_bf0ff45c-ab1a-407b-a469-30e8d8fb28bf.pdf"`.
- When rendered in frontend single-page application links (`<a href={ticket.attachment} target="_blank">`), clicking the link caused the web browser to resolve the relative URL against the active frontend origin:
  `http://localhost:5173/media/grievance_attachments/DaanGives_Receipt_bf0ff45c-ab1a-407b-a469-30e8d8fb28bf.pdf`.
- Because the Vite SPA dev server does not handle `/media/*` routes, Vite served `index.html`, and React Router matched no route, returning the frontend's **`404 Page Not Found`**.

### Security & Serving Architecture Cause
- In production (`DEBUG=False`), Django's static media server does not serve `/media/` files by default.
- Moreover, serving grievance dispute documents directly via raw unauthenticated `/media/` paths would create an IDOR vulnerability, allowing unauthenticated third parties or competitor organizations to download private dispute evidence, PAN details, and 80G tax receipts without authentication.

---

## 2. Exact Database Record and Persisted Attachment Path

| Property | Value |
|---|---|
| **Model** | `grievances.models.GrievanceTicket` |
| **Field** | `attachment` (`FileField(upload_to='grievance_attachments/')`) |
| **Ticket Reference** | `GRV-202610-00002` |
| **Ticket UUID** | `8404b0f3-1e8e-4372-849e-ff9f3b36ea6a` |
| **Title** | `ticket from company` |
| **Description** | `Hello please check my 80G file inside it wrong have ?` |
| **Category** | `RECEIPT_80G` (80G Tax Receipt) |
| **Status** | `IN_REVIEW` |
| **Priority** | `HIGH` |
| **Ticket Creator** | `kjchaudhary480@gmail.com` (UUID: `533cce4d-46fa-4191-a281-2dd22c6f3ce7`, Role: `COMPANY`) |
| **Target NGO** | `None` |
| **CSR Partnership** | `None` |
| **Assigned Officer** | `None` |
| **Stored DB Path** | `grievance_attachments/DaanGives_Receipt_bf0ff45c-ab1a-407b-a469-30e8d8fb28bf.pdf` |
| **Exact Storage Path** | `/Users/chaudharykamlesh/Desktop/daangives-backend/media/grievance_attachments/DaanGives_Receipt_bf0ff45c-ab1a-407b-a469-30e8d8fb28bf.pdf` |

---

## 3. Physical Existence of the Original File

- **Does the file physically exist?** **YES**.
- **Verification Method:** Verified through Python `os.path.exists()`, Django storage `ticket.attachment.storage.exists()`, and filesystem `ls -la`.
- **Filesize:** `4,098 bytes` (`-rw-r--r--@ 1 chaudharykamlesh staff 4098 Oct 12 18:18`).
- **File Integrity:** Valid ReportLab 1.4 PDF binary format (`%PDF-1.4 ReportLab Generated PDF document (opensource)`).
- **Origin of File:** The file is an authentic 80G receipt PDF that the company user previously downloaded from DaanGives and attached to ticket `GRV-202610-00002` when filing the grievance. It was uploaded successfully and is completely intact.

---

## 4. Files Changed

### Backend (`daangives-backend`)

1. **`grievances/views.py`**:
   - Added `user_has_ticket_attachment_access(user, ticket)` to enforce multi-tenant participant access rules.
   - Added `GrievanceAttachmentAuthentication(JWTAuthentication)` supporting both `Authorization: Bearer <token>` and `?token=<jwt>` query parameters for authenticated inline viewing in browser tabs.
   - Created `GrievanceTicketAttachmentView` (`/api/v1/grievances/tickets/<id>/attachment/`) returning `FileResponse` with `Content-Disposition: inline` and strict security headers (`X-Content-Type-Options: nosniff`, `Cache-Control: private, no-cache, no-store`).
   - Created `GrievanceResponseAttachmentView` (`/api/v1/grievances/responses/<id>/attachment/`) with internal note protection (non-admin accounts cannot view attachments attached to internal notes).
   - Passed `context={'request': request}` into `GrievanceTicketDetailSerializer` and `GrievanceResponseSerializer` in `GrievanceTicketDetailView`.

2. **`grievances/serializers.py`**:
   - Added `attachment_url`, `attachment_name`, and `attachment_available` serializer fields to `GrievanceTicketSerializer` and `GrievanceResponseSerializer`.
   - Updated `to_representation` to map `attachment` directly to the secure endpoint URL (`/api/v1/grievances/tickets/<id>/attachment/`), preventing exposure of raw filesystem/media paths.
   - `attachment_available` performs an existence check (`storage.exists()`), dynamically reporting whether the file exists on server storage.

3. **`grievances/urls.py`**:
   - Added routes for `tickets/<uuid:id>/attachment/` and `responses/<uuid:id>/attachment/`.

4. **`grievances/tests/test_attachments.py`**:
   - Created dedicated unit/integration test suite covering Admin access, owner access, target NGO access, unauthorized cross-org denial, anonymous denial, query-token auth, and missing file handling.

### Frontend (`daangives-frontend`)

1. **`src/services/api/grievances.js`**:
   - Added `resolveAttachmentUrl(attachmentUrl)`: guarantees that attachment URLs are resolved against the backend host (`API_BASE_URL`), never resolving against frontend port `5173`.
   - Added `fetchGrievanceAttachment(attachmentUrl, filename, download)`: fetches protected document blobs using the authenticated session and opens or downloads the file.

2. **`src/components/grievances/GrievanceAttachment.jsx`**:
   - Created shared component across all ticket detail views.
   - Displays clear "View Attachment" action, document icon, filename, and file type badge (e.g. `PDF`).
   - When `attachmentAvailable === false`: renders a distinct "Attachment unavailable" alert without an active clickable link.
   - Inline error display if download/preview fails.

3. **Ticket Detail Pages**:
   - `src/pages/admin/AdminTicketDetailPage.jsx`: Integrated `GrievanceAttachment` in ticket header and response thread.
   - `src/pages/ngo/NgoTicketDetailPage.jsx`: Integrated `GrievanceAttachment` in ticket header and response thread.
   - `src/pages/company/CompanyTicketDetailPage.jsx`: Integrated `GrievanceAttachment` in ticket header and response thread.
   - `src/pages/donor/TicketDetailPage.jsx`: Integrated `GrievanceAttachment` in ticket header and response thread.

4. **`src/components/grievances/GrievanceAttachment.test.jsx`**:
   - Created unit tests verifying rendering of available attachments, unavailable states, compact mode, and authenticated click handling.

---

## 5. Access Control and Privacy Enforcement

| Caller Role / Identity | Ticket Access (`GRV-202610-00002`) | Enforcement Behavior |
|---|---|---|
| **Platform Administrator (`is_staff` / `role=ADMIN`)** | **ALLOWED** | Full access to review ticket details and stream attachment. |
| **Ticket Creator (`kjchaudhary480@gmail.com` - Company)** | **ALLOWED** | Owner access to view and download their submitted attachment. |
| **Assigned Support Officer (`assigned_to`)** | **ALLOWED** | Investigating officer access to dispute attachment. |
| **Target NGO Participant (`target_ngo.user`)** | **DENIED** for this ticket | For ticket `GRV-202610-00002`, `target_ngo` is `None`. Unrelated NGOs cannot access this document. (If a ticket specifies a `target_ngo`, only that specific NGO account is permitted). |
| **Unrelated NGO / Company Account** | **DENIED (403 Forbidden)** | Cannot view or guess ticket attachments belonging to other organizations. |
| **Anonymous / Unauthenticated** | **DENIED (401 Unauthorized)** | Credentials required. |
| **Internal Administrative Notes** | **RESTRICTED TO STAFF** | Non-admin users cannot access attachments attached to staff-only internal notes. |

---

## 6. Verification Commands and Results

### 1. Backend Grievance Attachment Security Test Suite
```bash
./env_daan/bin/python manage.py test grievances.tests.test_attachments
```
**Result:**
```
Found 10 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
..........
----------------------------------------------------------------------
Ran 10 tests in 6.056s

OK
Destroying test database for alias 'default'...
```

### 2. Full Backend Grievance App Suite
```bash
./env_daan/bin/python manage.py test grievances
```
**Result:**
```
Ran 233 tests in 109.599s

OK
```

### 3. Full Backend Regression Test Suite
```bash
./env_daan/bin/python manage.py test
```
**Result:**
```
Ran 1658 tests in 747.283s

OK
```

### 4. Frontend Unit & Component Tests
```bash
npm test -- --run
```
**Result:**
```
Test Files  39 passed (39)
Tests       139 passed (139)
Duration    5.00s
```

### 5. Frontend Production Build
```bash
npm run build
```
**Result:**
```
vite v8.2.2 building client environment for production...
✓ 706 modules transformed.
✓ built in 221ms with 0 errors
```

---

## 7. Manual Browser Verification Steps

Since browser automation is not attached to this workspace instance, manual verification steps are provided below:

### Admin Verification
1. Start backend server: `python manage.py runserver 8000`.
2. Start frontend server: `npm run dev` (running on `http://localhost:5173`).
3. Log in as an administrator (e.g. `root@gmail.com` or platform admin).
4. Navigate to `http://localhost:5173/admin/complaints`.
5. Open ticket `GRV-202610-00002` ("ticket from company").
6. Verify the Attachment section displays:
   - Filename: `DaanGives_Receipt_bf0ff45c-ab1a-407b-a469-30e8d8fb28bf.pdf`
   - Badge: `PDF`
   - Action: "View Attachment" and download icon.
7. Click "View Attachment".
8. **Expected result:** The 80G receipt PDF opens in a new tab inline with ReportLab formatted receipt contents. No 404 occurs.

### Authorized Company Owner Verification
1. Log in as `kjchaudhary480@gmail.com` (Company user).
2. Navigate to `/company/tickets/8404b0f3-1e8e-4372-849e-ff9f3b36ea6a`.
3. Verify "View Attachment" is present and opens the valid PDF.

### Cross-Organization Access Denial Verification
1. Log in as any NGO account (e.g. `chaudharykamlesh185@gmail.com`).
2. Try opening `http://localhost:8000/api/v1/grievances/tickets/8404b0f3-1e8e-4372-849e-ff9f3b36ea6a/attachment/`.
3. **Expected result:** `403 Forbidden` with `"You do not have permission to access this grievance attachment."`

---

## 8. Missing File Recovery Status

- **Status:** **No recovery needed.**
- The original file `DaanGives_Receipt_bf0ff45c-ab1a-407b-a469-30e8d8fb28bf.pdf` exists intact under `/Users/chaudharykamlesh/Desktop/daangives-backend/media/grievance_attachments/`.
- No replacement file was fabricated.
- If a future ticket record ever references a physically removed file, the system safely detects this via `storage.exists()` and displays a clear `Attachment unavailable` state with error code `ATTACHMENT_FILE_MISSING`.
