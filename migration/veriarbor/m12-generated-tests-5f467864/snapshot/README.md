# Promotion Studio

Promotion Studio is a local-first application for managing marketing projects, campaigns, content creation, approval workflows, publishing, scheduling, and analytics. It provides a browser-based GUI backend that dispatches requests to various milestone modules (M1-M11).

## Local Server Startup

To start the local server, use the `main.py` script with the following command:

```bash
python main.py --serve --port <PORT> --data <DATA_DIR>
```

- `--serve`: Starts the HTTP server.
- `--port <PORT>`: Specifies the port number on which the server will listen (default is 8080 if not provided in some contexts, but explicit is better).
- `--data <DATA_DIR>`: Specifies the directory where all persistent data (projects, campaigns, content, receipts, etc.) will be stored. This directory will be created if it does not exist.

Example:
```bash
python main.py --serve --port 8080 --data ./my_promotion_data
```

Once started, you can access the GUI by navigating to `http://localhost:<PORT>/` in your web browser.

## Data Directory Configuration

The `--data` argument defines the root directory for all persistent storage. The application uses JSON files within this directory to store state:
- `projects.json`: Stores project metadata.
- `campaigns.json`: Stores campaign details linked to projects.
- `content.json`: Stores content drafts, revisions, and status.
- `evidence.json`: Stores imported evidence files and their hashes.
- `claims.json`: Stores claims linked to evidence.
- `receipts.json`: Stores publication receipts from M7.
- `schedules.json`: Stores scheduled publications from M8.
- `media_storage/`: A subdirectory containing uploaded media files organized by project ID.

Ensure this directory is writable by the Python process running the server.

## Local Test Platform Usage

The system includes a built-in local test platform (`promotion_publish.py`) that simulates external publishing endpoints. When you publish content via the GUI or API, the request is sent to this local platform, which generates receipts and metrics. This allows for end-to-end testing of the workflow without requiring external services.

The platform handles:
- `/publish`: Accepts POST requests to simulate publishing.
- `/publications`: GET endpoint to retrieve publication status by idempotency key.
- `/metrics`: GET endpoint to retrieve analytics data for a published item.

## Complete User Workflows

### 1. Project Creation
- Navigate to the **Projects** tab.
- Enter a **Project name**.
- Click **Create project**.
- The new project will appear in the selection dropdown. Select it to set the current context.

### 2. Campaign Creation
- Navigate to the **Campaigns** tab.
- Ensure a project is selected.
- Enter **Campaign name**, **Audience**, and **Channels** (comma-separated).
- Click **Create campaign**.
- The campaign will appear in the selection dropdown. Select it to configure content channels.

### 3. Evidence & Claims (Optional but Recommended)
- While not directly exposed as a primary tab in the simplified GUI view, the backend supports importing evidence and creating claims.
- Content creation links to claims which are validated against evidence.

### 4. Content Creation
- Navigate to the **Content** tab.
- Ensure a project and campaign are selected.
- Enter **Content text**.
- Select a **Channel** from the dropdown (populated from campaign channels).
- Optionally select **Claims** and **Media** if available.
- Click **Save content**.
- The content appears in the list with status `DRAFT`.

### 5. Review and Approval
- Navigate to the **Review** tab.
- Select the content you wish to review.
- Click **Review** to move status to `REVIEW`.
- Click **Approve** to move status to `APPROVED`. 
- *Note*: Approval validates that linked claims are supported by evidence and media is valid.

### 6. Publishing
- Navigate to the **Publish** tab.
- Ensure content is `APPROVED`.
- Enter a **Platform URL** (this should point to the local test platform, e.g., `http://localhost:8080` if serving both, or a separate instance).
- Click **Publish**.
- A receipt is generated with status `PUBLISHED` and a `remote_id`.

### 7. Scheduling
- The backend supports scheduling approved content for future publication using ISO8601 timestamps.
- Operations include `schedule.create`, `schedule.list`, `schedule.cancel`, and `schedule.run_due`.

### 8. Receipts and Analytics
- Navigate to the **Receipts/Analytics** tab.
- Click **Refresh receipts** to see publication history.
- Click **Refresh analytics** to see aggregated metrics (views, impressions, etc.) fetched from the platform's `/metrics` endpoint.

## Known Limitations

- **Local Only**: All data is stored locally. There is no cloud synchronization or multi-user collaboration features.
- **Single Threaded Assumption**: While the server uses threading for HTTP requests, complex concurrent writes to the same data directory might require careful handling. Atomic file operations are used to mitigate corruption.
- **No External Integrations**: The "platform" is a simulated local service. Real-world integrations would require replacing the `promotion_publish.py` logic with actual API calls.
- **GUI Simplicity**: The interface is functional but minimal. Advanced filtering, search, and bulk actions are not implemented.
