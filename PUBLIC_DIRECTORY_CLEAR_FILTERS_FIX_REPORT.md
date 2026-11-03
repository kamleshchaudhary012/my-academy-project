# DaanGives — Public Directory Clear All Filters Fix Report

**Date:** October 13, 2026  
**Repositories:**
- Frontend: `/Users/chaudharykamlesh/Desktop/daangives-frontend`
- Backend: `/Users/chaudharykamlesh/Desktop/daangives-backend`

---

## Executive Summary

When users clicked **"Clear All Filters"** on either `/ngos` (NGO Directory) or `/campaigns` (Campaigns Directory), the pages erroneously showed empty-state messages (*"No Verified NGOs Found"* / *"No active campaigns found."*), even though eligible verified records existed prior to filter clearing.

Through rigorous tracing across React state lifecycles, abort controller signal propagation, API serialization, and backend DRF query parameter handling, we isolated and resolved **three independent root causes**:
1. **Frontend State Timing & Effect Cleanup Abort:** When `clearFilters()` was clicked, state updates were scheduled asynchronously while `fetch` was called immediately. Because the fetch execution modified component references, React re-rendered and ran the previous `useEffect` cleanup function (`abortControllerRef.current.abort()`), cancelling the newly initiated cleared request. Simultaneously, `queryKey === lastExecutedQueryKeyRef.current` prevented the subsequent effect from re-issuing the request, leaving the state in an unresolved empty state.
2. **Debounce Race Condition:** Clearing `searchTerm` to `''` did not immediately update `debouncedSearchTerm` (which remained populated for 350ms), causing subsequent effect runs to query with the stale search string.
3. **Backend Negative Boolean Filter Bug:** In `ngo/public_views.py`, passing `has_80g=false`, `has_fcra=false`, or `has_12a=false` (or empty strings) was evaluated as `val = False` and filtered `legal_info__has_80g=False`. This explicitly excluded all 80G tax-exempt NGOs upon clearing or unchecking filters.

All issues have been resolved, verified with comprehensive automated frontend and backend regression test suites, and validated with clean production builds.

---

## 1. Separate Root-Cause Findings

### Page 1: NGO Directory (`/ngos`)

1. **Abort Controller Cancellation on Effect Re-render:**
   - In `NgoDirectoryPage.jsx`, `useEffect` had `fetchNgos` in its dependency array with a cleanup function:
     ```javascript
     return () => { if (abortControllerRef.current) abortControllerRef.current.abort(); };
     ```
   - When `clearFilters()` dispatched `fetchNgos({...})`, it created a new `AbortController` and assigned it to `abortControllerRef.current`.
   - The state setters (`setSelectedCategory('All')`, `setHas80gFilter(false)`, etc.) scheduled a re-render.
   - During re-render, the previous effect cleanup executed and aborted `abortControllerRef.current`—cancelling the cleared request in-flight.
   - The new effect executed `fetchNgos()`, but because `lastExecutedQueryKeyRef.current` was already set, `fetchNgos()` exited early without issuing a replacement request.
2. **Debounce Lag on Search Clear:**
   - When a user cleared a search query, `searchTerm` changed to `''`, but `useDebounce(searchTerm, 350)` retained the previous search query for 350ms.
   - When category changes triggered `fetchNgos()`, `debouncedSearchTerm` still held the old query, sending requests with stale search criteria.
3. **Backend Negative 80G/FCRA Filtering Bug (`ngo/public_views.py` & `src/services/api.js`):**
   - In `api.js`, `if (params.has_80g !== undefined && params.has_80g !== null && params.has_80g !== '') queryParams.set('has_80g', params.has_80g)` appended `?has_80g=false` whenever the checkbox was unchecked.
   - In `ngo/public_views.py`, lines 84–93:
     ```python
     has_80g = request.query_params.get('has_80g')
     if has_80g is not None:
         val = has_80g.lower() in ('true', '1')
         qs = qs.filter(legal_info__has_80g=val)
     ```
   - When `has_80g='false'`, `val = False`, and Django filtered `legal_info__has_80g=False`. This excluded all NGOs that possessed 80G approval (including verified NGOs).
4. **Empty State & Error Conflation:**
   - When `error` occurred, the error banner rendered, but because `ngos.length === 0`, the empty-state card (*"No Verified NGOs Found"*) was rendered simultaneously beneath the error banner.

---

### Page 2: Campaign Directory (`/campaigns`)

1. **Abort Controller Cancellation on Effect Re-render:**
   - Identical to `/ngos`: when `clearFilters()` called `fetchCampaigns({...})`, the state updates for `selectedCategory = 'All'` caused React to run the previous effect cleanup, aborting the in-flight cleared request. The subsequent effect run skipped dispatching because the query key matched `lastExecutedQueryKeyRef.current`.
2. **Debounce Desynchronization:**
   - Similar to `/ngos`, clearing `searchTerm` to `''` took 350ms to reflect in `debouncedSearchTerm`, causing intermediate effect runs to send stale queries.
3. **Backend Case Sensitivity & Empty String Category/Type Filter (`campaigns/public_views.py`):**
   - In `campaigns/public_views.py`:
     ```python
     category = self.request.query_params.get('category')
     if category and category.upper() != 'ALL':
         qs = qs.filter(category=category.upper())
     ```
   - Passing empty strings or whitespace queries without strip checking risked filter mismatches.
4. **Empty State & Error Conflation:**
   - When an API failure occurred, `campaigns.length === 0` caused *"No active campaigns found."* to render concurrently with the error banner.

---

## 2. Exact Files and APIs Inspected and Changed

### Frontend (`/Users/chaudharykamlesh/Desktop/daangives-frontend`)

| File Path | Description of Changes |
| :--- | :--- |
| `src/services/api.js` | Updated `getPublicNgos` and `getPublicCampaigns` query parameter serialization: `has_80g`, `has_fcra`, `has_12a`, and `is_featured` are only appended when strictly truthy (`=== true \|\| === 'true'`). Stale/empty/`'All'` values are omitted. |
| `src/pages/public/NgoDirectoryPage.jsx` | 1. `fetchNgos` accepts explicit `overrides = null` dictionary.<br>2. Immediate search reset: `(searchTerm \|\| '').trim() === '' ? '' : debouncedSearchTerm`.<br>3. `clearFilters()` explicitly passes clean default values.<br>4. Separated unmount cleanup from fetch effect so re-renders do not abort active cleared requests.<br>5. Distinct error banner with retry button; error state does not render empty state card. |
| `src/pages/public/CampaignDirectoryPage.jsx` | 1. `fetchCampaigns` accepts explicit `overrides = null` dictionary.<br>2. Immediate search reset on input clearing.<br>3. `clearFilters()` explicitly passes clean defaults.<br>4. Separated unmount cleanup from fetch effect.<br>5. Distinct error banner with retry button. |
| `src/test/pages/DirectoryClearFilters.test.jsx` | Created 10 comprehensive regression tests verifying before/after clear, pagination reset, error distinction, and repeated clear cycles. |

### Backend (`/Users/chaudharykamlesh/Desktop/daangives-backend`)

| File Path | Description of Changes |
| :--- | :--- |
| `ngo/public_views.py` | 1. Category filter handles case-insensitive `'ALL'`, `'all'`, `'All'`, and empty strings.<br>2. Location filters (`city`, `district`, `state`, `service_areas`) trimmed and ignore empty strings.<br>3. `has_80g`, `has_fcra`, and `has_12a` only filter `True` when explicitly `'true'`/`'1'`. Unchecked/cleared values (`'false'`, `'0'`, `''`) do NOT filter out eligible approved NGOs. |
| `campaigns/public_views.py` | 1. Category and campaign_type filter safely checks `category.strip().upper() not in ('', 'ALL')`.<br>2. `is_featured` checks `in ('true', '1')`. |
| `ngo/tests/test_public_apis.py` | Added tests 35–39 covering cleared categories, false/empty 80G/FCRA parameters, combined filter clearing, and unapproved NGO exclusion. |
| `campaigns/test_public_campaign_views.py` | Created 5 test cases testing public visibility rules, category/type filter clearing, multi-field search clearing, and combined cleared filters. |

---

## 3. Before/After Request and Response Behavior

### NGO Directory (`/ngos`)

#### Before Fix:
- **User Action:** User selected category "Disaster Relief" (0 results), then clicked "Clear All Filters".
- **API Request:** Immediately dispatched with stale closure category `?category=DISASTER_RELIEF` and `?has_80g=false`.
- **Backend Query:** Filtered for `category='DISASTER_RELIEF'` AND `legal_info__has_80g=False`.
- **Response:** `{"count": 0, "results": []}`.
- **Frontend Display:** *"No Verified NGOs Found"* (records disappeared).

#### After Fix:
- **User Action:** User clicks "Clear All Filters".
- **API Request:** Dispatched with clean query: `GET /api/v1/public/ngos/?ordering=display_name&page=1` (all stale filter params removed).
- **Backend Query:** `NGOProfile.objects.filter(status='APPROVED', is_active=True).order_by('display_name')`.
- **Response:** `{"count": 1, "results": [{"display_name": "Trust seva", "category": "EDUCATION", ...}]}`.
- **Frontend Display:** Full directory of verified NGOs is immediately rendered; empty state dismissed.

---

### Campaign Directory (`/campaigns`)

#### Before Fix:
- **User Action:** User filtered by category or search (0 results), then clicked "Clear All Filters".
- **API Request:** Dispatched with stale closure parameters; in-flight request was aborted by component effect re-render cleanup; subsequent request skipped by query-key deduplication.
- **Response:** Request aborted / state unresolved with 0 results.
- **Frontend Display:** *"No active campaigns found."*

#### After Fix:
- **User Action:** User clicks "Clear All Filters".
- **API Request:** Dispatched with clean query: `GET /api/v1/public/campaigns/?ordering=-created_at&page=1`.
- **Backend Query:** `Campaign.objects.filter(status='ACTIVE', is_active=True, ngo__status='APPROVED', ngo__is_active=True).order_by('-created_at')`.
- **Response:** Returns all active campaigns under approved NGOs.
- **Frontend Display:** Search input cleared, category chips reset to "All Categories", active campaigns grid restored.

---

## 4. Tests and Actual Results

### Frontend Test Suite (Vitest)

#### 1. Clear All Filters Regression Tests:
Command:
```bash
npx vitest run src/test/pages/DirectoryClearFilters.test.jsx
```
Output:
```
✓ src/test/pages/DirectoryClearFilters.test.jsx (10 tests) 1257ms
  ✓ Directory Clear All Filters Regression Tests (10)
    ✓ NGO Directory: shows results before filtering, empty state when filtered, and recovers records after Clear All Filters (120ms)
    ✓ NGO Directory: clearing multiple active filters together resets inputs, checkboxes, ordering and query params (430ms)
    ✓ NGO Directory: resets pagination when filters are cleared (53ms)
    ✓ NGO Directory: API errors remain distinct from empty results and display a retry button (15ms)
    ✓ NGO Directory: repeated filter changes and clear operations remain fully functional (59ms)
    ✓ Campaign Directory: shows results before filtering, empty state when filtered, and recovers records after Clear All Filters (43ms)
    ✓ Campaign Directory: clearing multiple active filters together resets search, category, ordering, and pagination (407ms)
    ✓ Campaign Directory: resets pagination when filters are cleared (53ms)
    ✓ Campaign Directory: API errors remain distinct from empty results and display retry button (14ms)
    ✓ Campaign Directory: repeated filter changes and clear operations remain fully functional (60ms)

Test Files  1 passed (1)
     Tests  10 passed (10)
  Duration  1.67s
```

#### 2. Search Optimization Tests:
Command:
```bash
npx vitest run src/test/searchRequestOptimization.test.jsx
```
Output:
```
✓ src/test/searchRequestOptimization.test.jsx (4 tests) 1764ms
  ✓ PROJECT-WIDE SEARCH REQUEST OPTIMIZATION VERIFICATION (4)
    ✓ demonstrates AFTER optimization: rapid typing "kamlesh" issues exactly 1 search request instead of 7 (424ms)
    ✓ prevents duplicate requests for queries that normalize to the same string (847ms)
    ✓ does NOT debounce non-search controls (sorting changes execute immediately) (45ms)
    ✓ protects against stale responses when an earlier slow request returns after a newer one (446ms)

Test Files  1 passed (1)
     Tests  4 passed (4)
  Duration  2.18s
```

#### 3. Full Frontend Suite:
Command:
```bash
npm test -- --run
```
Output:
```
Test Files  42 passed (42)
     Tests  168 passed (168)
  Duration  5.27s
```

---

### Backend Test Suite (Django)

#### 1. Public NGO API Tests:
Command:
```bash
./env_daan/bin/python manage.py test ngo.tests.test_public_apis
```
Output:
```
Ran 39 tests in 6.273s
OK
```

#### 2. Public Campaign API Tests:
Command:
```bash
./env_daan/bin/python manage.py test campaigns.test_public_campaign_views
```
Output:
```
Ran 5 tests in 1.920s
OK
```

#### 3. Full App Backend Regression Test Suite:
Command:
```bash
./env_daan/bin/python manage.py test ngo.tests campaigns.test_public_campaign_views
```
Output:
```
Ran 375 tests in 135.228s
OK
```

---

## 5. Production Build Status

Command:
```bash
npm run build
```
Output:
```
> daangives-frontend@0.0.0 build
> vite build

vite v8.2.2 building client environment for production...
transforming (706) src/index.css✓ 706 modules transformed.
rendering chunks (52)...computing gzip size...
dist/index.html                                         0.46 kB │ gzip:   0.29 kB
dist/assets/index-BeNZrtvE.css                        121.77 kB │ gzip:  18.12 kB
dist/assets/index-DbDPglc0.js                         502.96 kB │ gzip: 122.78 kB
✓ built in 227ms
```
Status: **PASSED (0 Errors)**

---

## 6. Browser Verification Steps and Limitations

1. **Browser Subagent Execution:**
   - Attempted automated browser execution via `browser_subagent`.
   - **Observed Limitation:** Playwright failed to start due to network sandbox blocking external binary downloads (`could not install driver: 404 from https://playwright.azureedge.net/builds/driver/playwright-1.57.0-mac-arm64.zip`).
   - Consequently, in accordance with the prompt guidelines, no false claims of Playwright browser execution are made.
2. **Local Live Server Verification:**
   - Frontend dev server running on `http://localhost:5173` (HTTP 200).
   - Backend API running on `http://localhost:8000` (HTTP 200).
3. **Manual Verification Procedure (Steps for Human Tester in Browser):**
   - **NGO Directory (`http://localhost:5173/ngos`):**
     1. Open `http://localhost:5173/ngos`. Confirm approved NGO card (e.g. `Trust seva`) is visible.
     2. Click "Disaster Relief" category chip or search for `nonexistent`.
     3. Confirm empty-state card appears: *"No Verified NGOs Found"* with a "Clear All Filters" button.
     4. Click **"Clear All Filters"**. Confirm the search input clears, category chip returns to "All Categories", and the `Trust seva` card immediately reappears.
     5. Check "80G Approved Only" checkbox, verify list, and click "Clear All Filters" again. Confirm repeated clearing functions seamlessly.
   - **Campaign Directory (`http://localhost:5173/campaigns`):**
     1. Open `http://localhost:5173/campaigns`.
     2. Type `nomatch` into search input and press Enter.
     3. Confirm empty-state card appears: *"No active campaigns found."* with "Clear All Filters" button.
     4. Click **"Clear All Filters"**. Confirm search input clears, category resets to "All Categories", and directory recovers.

---

## 7. Data and Authorization Integrity Confirmation

- No database records were altered, fabricated, or deleted.
- No unapproved or pending NGOs or campaigns were automatically approved.
- Public visibility rules (`status == APPROVED`, `is_active == True` for NGOs; `status == ACTIVE`, `is_active == True`, and `ngo__status == APPROVED` for campaigns) remain strictly enforced.
