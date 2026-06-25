# Startup And Visual Evidence Contract

## A. Startup Entry Priority

General startup evaluation order:

1. `package.json` `scripts.preview`
2. `package.json` `scripts.start`
3. `package.json` `scripts.dev`
4. static `index.html` via local HTTP server
5. static `dist/index.html` via local HTTP server
6. `app.py` / `main.py`

Visual evidence capture may prefer the pipeline-owned static HTTP server first when `index.html` or `dist/index.html` exists. This keeps screenshot capture independent from fragile generated start scripts unless those scripts are necessary.

## B. Startup Diagnostic Fields

`startup_failed` must record:

```json
{
  "startup_command": "",
  "startup_cwd": "",
  "startup_returncode": null,
  "startup_stdout_tail": "",
  "startup_stderr_tail": "",
  "port": null,
  "server_ready": false,
  "opened_url": "",
  "failure_reason": "startup_failed",
  "next_repair_hint": ""
}
```

## C. Screenshot Diagnostic Fields

`screenshot_blocked.json` must record:

```json
{
  "failure_reason": "",
  "opened_url": "",
  "browser_used": "",
  "page_title": "",
  "body_text_length": 0,
  "body_text_sample": "",
  "console_errors": [],
  "network_errors": [],
  "blank_score": 0.0,
  "is_blank_or_invalid": true
}
```

## D. When To Trigger Code Repair

Post-build repair may modify candidate project files for:

- `startup_failed`
- `entrypoint_missing`
- `page_blank`
- `module_system_failure`
- `missing_start_script`
- `missing_static_entry`

Provider code repair must not be triggered for:

- `browser_unavailable`
- `ffmpeg_unavailable`
- `environment_failure`

Environment failures should produce blocked diagnostics and candidate review notes, not candidate code changes.

## E. UI Smoke Minimum

Formal projects must satisfy minimum UI smoke before screenshot evidence is accepted:

- `body_text_length > 50`
- page title exists
- no console errors
- no fatal network errors
- domain keywords found

For a task and bug workbench, expected keywords include:

- `Task`
- `Bug`
- `Todo`
- `Doing`
- `Done`
- `Open`
- `Fixed`
- `Add`
- `Dashboard`
