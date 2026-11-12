# Promotion Studio Test Plan

This document outlines the reproducible test procedures for Promotion Studio milestones M1-M12. It covers API-level tests, GUI integration tests (upload, edit, state), and independent measurement steps.

## Prerequisites

1.  **Environment**: Python 3.8+ installed.
2.  **Dependencies**: All milestone modules (`milestones/milestone_*/api.py`) and `promotion_publish.py` must be present in the working directory structure.
3.  **Data Directory**: A clean temporary directory (e.g., `./test_data`) to ensure isolation between test runs.
4.  **Server Startup**:
    *   Start the local platform server: `python promotion_publish.py --serve --port 9090 --data ./test_data_platform`
    *   Start the main application server: `python early_main.py --serve --port 8080 --data ./test_data_app`

## Milestone Coverage Overview

| Milestone | Component | Key Operations Tested |
| :--- | :--- | :--- |
| M1 | Project Workspace | Create, List, Get projects |
| M2 | Evidence & Signals | Import evidence, Refresh, Create/Reject signals |
| M3 | Claim Ledger | Create claims, Validate status against evidence |
| M4 | Campaign CRUD | Create, Update, Archive campaigns |
| M5 | Content Studio | Create, Edit, Compare revisions |
| M6 | Approval | Review, Approve content (validates claims/media) |
| M7 | Local Publish | Send, Reconcile, Retry publications |
| M8 | Scheduler | Schedule, Run due tasks |
| M9 | Receipt Queries | List, Get, Export receipts |
| M10 | Analytics | Fetch metrics, History, Recommend |
| M11 | Media | Import, Validate signatures, Integrity checks |
| M12 | Final GUI/API | End-to-end workflow via browser and API dispatch |

---

## Detailed Test Procedures

### M1: Project Management

**API Test:**
1.  POST `/api/action` with `{"milestone": "M1", "op": "project.create", "name": "TestProject"}`.
    *   **Expected**: HTTP 200, JSON response containing `id` and `name`.
2.  POST `/api/action` with `{"milestone": "M1", "op": "project.list"}`.
    *   **Expected**: HTTP 200, JSON response containing `items` array with the created project.

**GUI Test:**
1.  Navigate to `http://localhost:8080`.
2.  In the **Projects** view, enter "TestProject" in the input labeled **Project name**.
3.  Click button **Create project**.
4.  **Expected**: Status message shows "Created project: TestProject". The project appears in the **Select project** dropdown.

### M2: Evidence & Signals

**API Test:**
1.  Prepare a local directory `./fixtures/evidence` with text files.
2.  POST `/api/action` with `{"milestone": "M2", "op": "evidence.import", "project_id": <ID>, "path": "./fixtures/evidence"}`.
    *   **Expected**: HTTP 200, JSON response with `id`, `status`: "CURRENT", and `files` list.
3.  POST `/api/action` with `{"milestone": "M2", "op": "signal.create", "project_id": <ID>, "evidence_id": <EVIDENCE_ID>, "text": "New Signal"}`.
    *   **Expected**: HTTP 200, JSON response with signal `id` and `status`: "OPEN".

### M3: Claim Ledger

**API Test:**
1.  POST `/api/action` with `{"milestone": "M3", "op": "claim.create", "project_id": <ID>, "text": "Exact substring from evidence", "evidence_ids": [<EVIDENCE_ID>]}`.
    *   **Expected**: HTTP 200, JSON response with `status`: "SUPPORTED".
2.  POST `/api/action` with `{"milestone": "M3", "op": "claim.create", "project_id": <ID>, "text": "Invalid claim", "evidence_ids": []}`.
    *   **Expected**: HTTP 200, JSON response with `status`: "UNSUPPORTED".

### M4: Campaigns

**API Test:**
1.  POST `/api/action` with `{"milestone": "M4", "op": "campaign.create", "project_id": <ID>, "name": "SummerSale", "audience": "General", "channels": ["web", "email"]}`.
    *   **Expected**: HTTP 200, JSON response with campaign `id` and `status`: "ACTIVE".

**GUI Test:**
1.  Select the project created in M1.
2.  Navigate to **Campaigns** view.
3.  Enter "SummerSale" in **Campaign name**, "General" in **Audience**, and "web,email" in **Channels**.
4.  Click **Create campaign**.
5.  **Expected**: Status shows creation success. Campaign appears in dropdown.

### M5: Content Studio

**API Test:**
1.  POST `/api/action` with `{"milestone": "M5", "op": "content.create", "project_id": <ID>, "campaign_id": <CAMPAIGN_ID>, "channel": "web", "text": "Hello World", "claim_ids": [<CLAIM_ID>], "media_ids": []}`.
    *   **Expected**: HTTP 200, JSON response with content `id`, `revision`: 1, `status`: "DRAFT".
2.  POST `/api/action` with `{"milestone": "M5", "op": "content.edit", ... , "text": "Hello Updated"}`.
    *   **Expected**: HTTP 200, JSON response with `revision`: 2.

**GUI Test:**
1.  Select Project and Campaign.
2.  Navigate to **Content** view.
3.  Enter text in **Content text** textarea.
4.  Select Channel from dropdown.
5.  Click **Save content**.
6.  **Expected**: Status shows saved ID. Content appears in list.

### M6: Approval Workflow

**API Test:**
1.  POST `/api/action` with `{"milestone": "M6", "op": "approval.review", "project_id": <ID>, "content_id": <CONTENT_ID>}`.
    *   **Expected**: HTTP 200, JSON response with `status`: "REVIEW".
2.  POST `/api/action` with `{"milestone": "M6", "op": "approval.approve", "project_id": <ID>, "content_id": <CONTENT_ID>}`.
    *   **Expected**: HTTP 200, JSON response with `status`: "APPROVED". (Requires valid claims/media).

**GUI Test:**
1.  Select the draft content.
2.  Navigate to **Review** view.
3.  Click **Review**. Button should become disabled or change state.
4.  Click **Approve**.
5.  **Expected**: Status shows "Content approved". Publish button becomes enabled.

### M7: Publication

**API Test:**
1.  Ensure Platform Server is running on port 9090.
2.  POST `/api/action` with `{"milestone": "M7", "op": "publish.send", "project_id": <ID>, "content_id": <CONTENT_ID>, "platform_url": "http://localhost:9090", "idempotency_key": "key-1"}`.
    *   **Expected**: HTTP 200, JSON receipt with `status`: "PUBLISHED", `remote_id` set.
3.  Repeat step 2 with same `idempotency_key`.
    *   **Expected**: HTTP 200, same receipt returned (no new publication).

**GUI Test:**
1.  Navigate to **Publish** view.
2.  Enter `http://localhost:9090` in **Platform URL**.
3.  Click **Publish**.
4.  **Expected**: Status shows published remote ID. Receipt appears in **Receipts/Analytics** view.

### M8: Scheduling

**API Test:**
1.  POST `/api/action` with `{"milestone": "M8", "op": "schedule.create", "project_id": <ID>, "content_id": <CONTENT_ID>, "platform_url": "...", "idempotency_key": "sched-1", "when": "2024-12-31T23:59:59Z"}`.
    *   **Expected**: HTTP 200, JSON schedule with `status`: "PENDING".
2.  POST `/api/action` with `{"milestone": "M8", "op": "schedule.run_due", "project_id": <ID>, "now": "2025-01-01T00:00:00Z"}`.
    *   **Expected**: HTTP 200, JSON items showing processed schedules.

### M9: Receipts

**API Test:**
1.  POST `/api/action` with `{"milestone": "M9", "op": "receipt.list", "project_id": <ID>}`.
    *   **Expected**: HTTP 200, JSON items containing previous publication receipts.

### M10: Analytics

**API Test:**
1.  POST `/api/action` with `{"milestone": "M10", "op": "analytics.fetch", "project_id": <ID>, "receipt_id": <RECEIPT_ID>, "platform_url": "http://localhost:9090"}`.
    *   **Expected**: HTTP 200, JSON sample with `metrics` (views, impressions, etc.).

### M11: Media Handling

**API Test:**
1.  Prepare a valid PNG file at `./fixtures/image.png`.
2.  POST `/api/action` with `{"milestone": "M11", "op": "media.import", "project_id": <ID>, "kind": "image", "filename": "image.png", "data": "<BASE64_DATA>"}`.
    *   **Expected**: HTTP 200, JSON media record with `status`: "VALID".
3.  GET `/api/media?project_id=<ID>&media_id=<MEDIA_ID>`.
    *   **Expected**: HTTP 200, Content-Type `image/png`, binary data matches source.

**GUI Test:**
1.  Navigate to **Media** view (if exposed in final GUI) or use Content view media selector.
2.  Upload image file.
3.  **Expected**: Preview renders correctly. Broken images show error message.

### M12: End-to-End Integration

**Scenario**: Full workflow from Project Creation to Published Receipt with Analytics.

1.  **Start Servers**: Launch both `early_main.py` and `promotion_publish.py` servers.
2.  **Browser Interaction**:
    *   Create Project "E2E_Test".
    *   Create Campaign "Launch" with channel "web".
    *   Import Evidence (via API or fixture setup if GUI lacks direct import UI, otherwise verify claim support).
    *   Create Claim "Valid Claim" linked to evidence.
    *   Create Content "Hello E2E" linked to Claim.
    *   Review and Approve Content.
    *   Publish Content to local platform.
    *   Verify Receipt appears in **Receipts/Analytics** tab with Remote ID.
    *   Fetch Analytics for the receipt.
3.  **State Persistence Check**:
    *   Reload the browser page.
    *   **Expected**: Selected Project/Campaign/Content persist via localStorage or server state retrieval. Receipts remain visible.
4.  **Error Handling**:
    *   Attempt to publish unapproved content.
    *   **Expected**: Alert message indicating failure.
    *   Attempt to approve content with broken media.
    *   **Expected**: Alert message indicating media validation failure.

## Independent Measurement Steps

1.  **Latency**: Measure time taken for `publish.send` round-trip including network call to local platform.
2.  **Throughput**: Concurrently send 10 unique publication requests; verify all receipts are persisted without race conditions (check `receipts.json` integrity).
3.  **Integrity**: Corrupt a stored media file manually; verify `media.get` returns `status`: "BROKEN" and blocks approval/publication.
