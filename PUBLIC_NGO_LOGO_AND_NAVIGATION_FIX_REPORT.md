# DaanGives — Public NGO Logo Rendering and Public Navigation Refinement Report

**Date:** October 12, 2026  
**Repositories:**
- Frontend: `/Users/chaudharykamlesh/Desktop/daangives-frontend`
- Backend: `/Users/chaudharykamlesh/Desktop/daangives-backend`

---

## 1. Executive Summary & Root Cause Analysis

### A. The Broken NGO Logo
- **Observed Behavior:** On the public homepage (`http://localhost:5173/`), the verified `Trust seva` NGO card showed a broken image icon even though an official logo had been uploaded via the NGO portal.
- **Investigation of Persisted Asset:**
  - Database Model: `NGOProfile` (`id: e5bccfb2-60e0-4d42-8c70-b830924d1267`).
  - Stored Path in Database: `ngo_logos/e5bccfb2-60e0-4d42-8c70-b830924d1267/3adb6816-a3c8-4346-973d-3569f8bad7d3.jpg`.
  - Stored File on Disk: `/Users/chaudharykamlesh/Desktop/daangives-backend/media/ngo_logos/e5bccfb2-60e0-4d42-8c70-b830924d1267/3adb6816-a3c8-4346-973d-3569f8bad7d3.jpg`.
  - File Size: `1,175,002 bytes` (valid JPEG).
  - Backend Serving: Direct `curl http://127.0.0.1:8000/media/...` returned `HTTP/1.1 200 OK Content-Type: image/jpeg`.
- **Root Causes:**
  1. **Missing Request Context in Public Serializers:** In `ngo/public_views.py`, `NGOPublicListView`, `NGOPublicSlugDetailView`, and `NGOPublicUUIDDetailView` invoked `NGOPublicSerializer(page, many=True)` without passing `context={'request': request}`. In DRF, when `request` is omitted from context, `ImageField.to_representation` outputs a relative path (`/media/...`) rather than an absolute URL (`http://localhost:8000/media/...`).
  2. **Missing Dev Proxy in Vite Config:** `vite.config.js` had no dev server proxy configured for `/media`. When the browser requested relative `/media/...` on `http://localhost:5173`, Vite's SPA fallback served `index.html` with `Content-Type: text/html`.
  3. **Raw `<img>` Tag in HomePage without Error Fallback:** In `HomePage.jsx`, the card used a raw `<img src={ngo.logo} />` without `AvatarImage` or an `onError` handler. When the browser attempted to decode HTML as an image, it failed and displayed a broken image placeholder.
  4. **Lack of Disk Existence Validation:** If a logo file was removed or missing on disk, serializers continued returning the path string rather than returning `null`.

### B. Public Navigation Refinement
- **Previous Navigation Items:** `Home`, `Browse Projects`, `Village Directory`, `CSR Portal`, `Log In`, `Register`.
- **Required & Implemented Navigation:** `Home`, `Browse Projects`, `Village Directory`, `For Companies`, `Log In`, `Register`.
- **Destination:** Pointed `For Companies` to the existing corporate CSR discovery route `/csr` (`CsrLandingPage`), preserving deep links and active state highlighting.
- **Layout Isolation:** Confirmed that authenticated NGO (`NgoLayout`), Company (`CompanyLayout`), and Admin (`AdminLayout`) workspaces remain strictly isolated from public marketing navigation and footers.

### C. Review of Homepage Trust Claims
- Refined unverified or exaggerated marketing copy:
  - `"100% Direct"` badge replaced with restrained `"Direct Collaboration"` / `"Verified Partner"`.
  - `"Instant 80G Receipts"` replaced with accurate statutory capability `"Statutory Compliance"`.
  - `"Every organization is verified against Darpan ID, 12A/80G status, and registered bank credentials"` replaced with `"Listed organizations undergo administrative review of Darpan ID, statutory registrations, and organization details"`.
  - `"Zero Intermediary Deductions"` replaced with `"Transparent Partner Engagement"`.
  - `"Audited & Verified Non-Profits"` replaced with `"Verified Partner Directory"`.
  - `"View Full Profile & Audits"` replaced with `"View Organization Profile"`.

---

## 2. Changed Files

### Frontend (`daangives-frontend`)
1. **[`vite.config.js`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/vite.config.js):**
   - Configured dev server reverse proxy for `/api` and `/media` forwarding to `http://localhost:8000`.
2. **[`src/services/api.js`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/services/api.js):**
   - Enhanced `getMediaUrl(path)` to support leading whitespace trimming, `blob:`, `data:`, relative `/media/...`, and absolute URLs.
3. **[`src/components/common/AvatarImage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/components/common/AvatarImage.jsx):**
   - Added support for `objectFit="contain"` (defaulting to contain for logos), reset `imgError` on `src` changes via `useEffect`, and ensured fallback initials/avatar render cleanly on missing or failing images (`onError`).
4. **[`src/pages/public/HomePage.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/pages/public/HomePage.jsx):**
   - Replaced raw `<img>` tag with `AvatarImage` (`objectFit="contain"`, white background, clean border).
   - Refined trust claims and governance copy to match actual platform capabilities.
5. **[`src/components/common/Header.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/components/common/Header.jsx):**
   - Updated desktop navigation and mobile drawer: changed `CSR Portal` to `For Companies` linking to `/csr`.
6. **[`src/test/pages/NgoProfileRoutingAndLayout.test.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/test/pages/NgoProfileRoutingAndLayout.test.jsx):**
   - Updated assertion to match `For Companies`.
7. **[`src/test/pages/NgoLogoAndPublicNavigation.test.jsx`](file:///Users/chaudharykamlesh/Desktop/daangives-frontend/src/test/pages/NgoLogoAndPublicNavigation.test.jsx):**
   - Added 9 unit tests covering valid logos, fallback initials, `onError` handling, `getMediaUrl`, navigation links, and workspace layout isolation.

### Backend (`daangives-backend`)
1. **[`ngo/serializers.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/serializers.py):**
   - Overrode `to_representation` in `NGOPublicSerializer` and `NGOProfileSerializer` to verify that `logo` and `cover_image` exist on storage via `storage.exists()`. If missing on disk, `data['logo'] = None` (never marks missing files as uploaded).
2. **[`ngo/public_views.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/public_views.py):**
   - Passed `context={'request': request}` to `NGOPublicSerializer` across `NGOPublicListView`, `NGOPublicSlugDetailView`, and `NGOPublicUUIDDetailView`.
3. **[`ngo/views.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/views.py):**
   - Passed `context={'request': request}` in `NGOProfileMeView` (`get` and `patch`).
4. **[`ngo/tests/test_serializers.py`](file:///Users/chaudharykamlesh/Desktop/daangives-backend/ngo/tests/test_serializers.py):**
   - Added unit tests verifying valid logo URLs with request context, missing files returning `None`, and null logos returning `None`.

---

## 3. Actual Test Commands and Results

### 1. Backend Serializer Tests
```bash
./env_daan/bin/python manage.py test ngo.tests.test_serializers.TestNGOPublicSerializer
```
**Result:**
```
Found 4 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
....
----------------------------------------------------------------------
Ran 4 tests in 0.512s

OK
Destroying test database for alias 'default'...
```

### 2. Backend Public API Tests
```bash
./env_daan/bin/python manage.py test ngo.tests.test_public_apis
```
**Result:**
```
Ran 34 tests in 5.474s
OK
```

### 3. Frontend Dedicated Logo & Navigation Suite
```bash
npx vitest run src/test/pages/NgoLogoAndPublicNavigation.test.jsx
```
**Result:**
```
 ✓ src/test/pages/NgoLogoAndPublicNavigation.test.jsx (9 tests) 142ms
   ✓ 1. AvatarImage renders valid logo URL with object-fit contain
   ✓ 2. AvatarImage handles NGO with no logo with clean initials fallback
   ✓ 3. AvatarImage handles inaccessible or missing image file via onError fallback
   ✓ 4. getMediaUrl helper correctly resolves relative, absolute, data, and blob URLs
   ✓ 5. Public Navigation displays refined items: Home, Browse Projects, Village Directory, For Companies
   ✓ 6. HomePage renders verified NGO cards with AvatarImage and restrained trust claims
   ✓ 7. Authenticated NGO workspace layout isolates from public marketing navigation
   ✓ 8. Authenticated Company workspace layout isolates from public marketing navigation
   ✓ 9. Authenticated Admin suite isolates from public marketing navigation

 Test Files  1 passed (1)
      Tests  9 passed (9)
```

### 4. Full Frontend Suite
```bash
npm test -- --run
```
**Result:**
```
 Test Files  41 passed (41)
      Tests  158 passed (158)
   Duration  5.14s
```

### 5. Frontend Production Build
```bash
npm run build
```
**Result:**
```
vite v8.2.2 building client environment for production...
✓ 706 modules transformed.
✓ built in 227ms with 0 errors
```

---

## 4. Verification Evidence & Browser Testing

### A. Curl Test on Vite Dev Proxy
```bash
curl -I http://localhost:5173/media/ngo_logos/e5bccfb2-60e0-4d42-8c70-b830924d1267/3adb6816-a3c8-4346-973d-3569f8bad7d3.jpg
```
**Response:**
```http
HTTP/1.1 200 OK
content-type: image/jpeg
content-length: 1175002
content-disposition: inline; filename="3adb6816-a3c8-4346-973d-3569f8bad7d3.jpg"
server: WSGIServer/0.2 CPython/3.14.6
```
Proxies cleanly to Django and delivers the authentic image file (1.17 MB).

### B. Public API Logo Representation
```bash
curl -s http://localhost:8000/api/v1/public/ngos/ | grep -o '"logo":"[^"]*"'
```
**Output:**
```json
"logo":"http://localhost:8000/media/ngo_logos/e5bccfb2-60e0-4d42-8c70-b830924d1267/3adb6816-a3c8-4346-973d-3569f8bad7d3.jpg"
```

### C. Manual Browser Verification Procedure
1. Navigate to `http://localhost:5173/`:
   - Inspect the navbar: `Home`, `Browse Projects`, `Village Directory`, `For Companies`, `Log In`, `Register`.
   - Click `For Companies`: confirms navigation to `http://localhost:5173/csr` (`CsrLandingPage`).
   - Observe the featured NGO cards: `Trust seva` displays its genuine uploaded logo with `object-fit: contain` on a clean white background.
   - Observe homepage trust badges: `"Verified Partner"` and `"Administrative Governance"` without exaggerated claims.
2. Navigate to `http://localhost:5173/ngos`:
   - `Trust seva` renders with its official logo in `AvatarImage`.
3. Open `http://localhost:5173/ngo/dashboard`:
   - Displays Village / Sanstha portal workspace with no public marketing header or footer.

---

## 5. Security & Statutory Integrity Considerations

- **Private Documents Protected:** Document endpoints (`/api/v1/ngo/documents/`) continue enforcing strict ownership and admin authorization. Private statutory documents (PAN card, 12A/80G certificates, bank passbooks) remain restricted.
- **Tenant Isolation Preserved:** Cross-workspace layout boundaries remain intact; public navigation is excluded from authenticated workspaces.
- **Audit Immutability Preserved:** No database records were altered, deleted, or fabricated.
