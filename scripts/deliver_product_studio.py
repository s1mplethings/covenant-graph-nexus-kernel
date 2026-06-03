#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import pathlib
import shutil
import zipfile
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_run(run_file: pathlib.Path) -> dict[str, Any]:
    return json.loads(run_file.read_text(encoding="utf-8"))


def run_text(run: dict[str, Any]) -> str:
    intent = run.get("customer_intent", {})
    parts = [
        intent.get("goal", ""),
        " ".join(str(item) for item in intent.get("input_expectation", [])),
        " ".join(str(item) for item in intent.get("output_expectation", [])),
    ]
    return " ".join(parts)


def infer_project_type(run: dict[str, Any]) -> str:
    text = run_text(run).lower()
    image_keywords = ("图片", "image", "gui", "重命名", "rename", "prefix", "index")
    if any(keyword in text for keyword in image_keywords):
        return "image_batch_rename_gui"
    return "static_gui_demo"


def project_name(run: dict[str, Any]) -> str:
    story = run.get("product_story", {})
    intent = run.get("customer_intent", {})
    return str(story.get("product_name") or intent.get("goal") or "Product Studio Static GUI Demo")


def build_generated_project(run: dict[str, Any], out_dir: pathlib.Path) -> dict[str, Any]:
    project_dir = out_dir / "generated_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    name = project_name(run)
    goal = str(run.get("customer_intent", {}).get("goal", name))
    escaped_name = html.escape(name)
    escaped_goal = html.escape(goal)

    (project_dir / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_name}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="shell">
    <header class="page-header">
      <p class="eyebrow">Local static GUI demo</p>
      <h1>{escaped_name}</h1>
      <p class="goal">{escaped_goal}</p>
    </header>

    <section class="panel" aria-labelledby="input-title">
      <h2 id="input-title">Input area</h2>
      <p>Selecting real folders is deferred. This demo uses local simulated image records.</p>
      <label for="prefix">Rename prefix</label>
      <input id="prefix" type="text" value="demo" autocomplete="off">
      <label for="startIndex">Start index</label>
      <input id="startIndex" type="number" value="1" min="1">
      <div class="actions">
        <button id="applyRename" type="button">Run preview</button>
        <button id="exportReport" type="button">Export report</button>
      </div>
    </section>

    <section class="panel" aria-labelledby="preview-title">
      <h2 id="preview-title">Preview list</h2>
      <ul id="previewList" class="preview-list"></ul>
    </section>

    <section class="panel" aria-labelledby="status-title">
      <h2 id="status-title">Status</h2>
      <pre id="statusArea">Ready. No file-system access and no network access are used.</pre>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )

    (project_dir / "styles.css").write_text(
        """* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  background: #f4f7f9;
  color: #17212b;
}

.shell {
  width: min(960px, calc(100% - 32px));
  margin: 0 auto;
  padding: 32px 0;
}

.page-header {
  margin-bottom: 20px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #426173;
  font-size: 13px;
  text-transform: uppercase;
}

h1 {
  margin: 0 0 8px;
  font-size: 30px;
}

.goal {
  margin: 0;
  color: #475866;
}

.panel {
  margin: 16px 0;
  padding: 18px;
  background: #ffffff;
  border: 1px solid #d8e0e6;
  border-radius: 8px;
}

label {
  display: block;
  margin-top: 12px;
  font-weight: 700;
}

input {
  width: 100%;
  margin-top: 6px;
  padding: 10px 12px;
  border: 1px solid #bac7d0;
  border-radius: 6px;
  font: inherit;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

button {
  padding: 10px 14px;
  border: 0;
  border-radius: 6px;
  background: #176c7d;
  color: #ffffff;
  font-weight: 700;
  cursor: pointer;
}

button:hover {
  background: #0f5260;
}

.preview-list {
  padding: 0;
  list-style: none;
}

.preview-list li {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #e4eaee;
}

pre {
  min-height: 110px;
  padding: 12px;
  overflow: auto;
  background: #101820;
  color: #dff7ed;
  border-radius: 6px;
}
""",
        encoding="utf-8",
    )

    (project_dir / "app.js").write_text(
        """const sampleImages = [
  { original: "holiday_photo_a.svg", size: "128 KB" },
  { original: "holiday_photo_b.svg", size: "132 KB" },
  { original: "holiday_photo_c.svg", size: "119 KB" }
];

const prefixInput = document.getElementById("prefix");
const startIndexInput = document.getElementById("startIndex");
const previewList = document.getElementById("previewList");
const statusArea = document.getElementById("statusArea");

function buildRows() {
  const prefix = prefixInput.value.trim() || "demo";
  const startIndex = Number.parseInt(startIndexInput.value, 10) || 1;
  return sampleImages.map((image, offset) => {
    const nextIndex = String(startIndex + offset).padStart(3, "0");
    return {
      original: image.original,
      renamed: `${prefix}_${nextIndex}.svg`,
      size: image.size
    };
  });
}

function renderPreview() {
  const rows = buildRows();
  previewList.innerHTML = "";
  for (const row of rows) {
    const item = document.createElement("li");
    item.innerHTML = `<span>${row.original}</span><strong>${row.renamed}</strong>`;
    previewList.appendChild(item);
  }
  statusArea.textContent = `Preview refreshed for ${rows.length} simulated images.`;
}

function exportReport() {
  const rows = buildRows();
  const lines = [
    "Simulated image rename report",
    "No real files were changed.",
    "",
    ...rows.map((row) => `${row.original} -> ${row.renamed} (${row.size})`)
  ];
  statusArea.textContent = lines.join("\\n");
}

document.getElementById("applyRename").addEventListener("click", renderPreview);
document.getElementById("exportReport").addEventListener("click", exportReport);
renderPreview();
""",
        encoding="utf-8",
    )

    readme = project_dir / "README.md"
    readme.write_text(
        f"""# {name}

Open `index.html` in a local browser.

This is a local static GUI demo generated by the Product Studio delivery pipeline.

Implemented:
- Static HTML/CSS/JS image rename preview.
- Simulated image records.
- Prefix and index preview refresh.
- Simulated operation report text.

Not implemented:
- Real file-system image renaming.
- Real browser screenshot capture.
- Real runner orchestration.
- Provider-backed generation.

Next stage:
- Add a runner for local execution checks.
- Add browser screenshot capture.
- Add a file-system adapter for real image folders.
""",
        encoding="utf-8",
    )

    manifest = {
        "kind": "GeneratedProjectManifest",
        "project_type": infer_project_type(run),
        "files": ["README.md", "index.html", "styles.css", "app.js", "project_manifest.json"],
        "no_network": True,
        "provider_used": False,
    }
    write_json(project_dir / "project_manifest.json", manifest)
    return {
        "project_dir": str(project_dir),
        "manifest": str(project_dir / "project_manifest.json"),
        "files": manifest["files"],
        "project_type": manifest["project_type"],
    }


def create_sample_svg(path: pathlib.Path, title: str, fill: str) -> None:
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="360" height="220" viewBox="0 0 360 220">
  <rect width="360" height="220" rx="18" fill="{fill}"/>
  <circle cx="82" cy="86" r="38" fill="#ffffff" opacity="0.72"/>
  <rect x="130" y="66" width="190" height="26" rx="8" fill="#ffffff" opacity="0.82"/>
  <rect x="130" y="108" width="150" height="20" rx="7" fill="#ffffff" opacity="0.64"/>
  <text x="28" y="188" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="#ffffff">{html.escape(title)}</text>
</svg>
""",
        encoding="utf-8",
    )


def create_test_data(run: dict[str, Any], out_dir: pathlib.Path) -> dict[str, Any]:
    test_data_dir = out_dir / "test_data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    samples = [
        {"id": "sample_001", "file": "sample_001.svg", "original_name": "holiday_photo_a.svg"},
        {"id": "sample_002", "file": "sample_002.svg", "original_name": "holiday_photo_b.svg"},
        {"id": "sample_003", "file": "sample_003.svg", "original_name": "holiday_photo_c.svg"},
    ]
    create_sample_svg(test_data_dir / "sample_001.svg", "Sample 001", "#176c7d")
    create_sample_svg(test_data_dir / "sample_002.svg", "Sample 002", "#7a4f9a")
    create_sample_svg(test_data_dir / "sample_003.svg", "Sample 003", "#5f6b2d")
    manifest = {
        "kind": "SampleImagesManifest",
        "project_type": infer_project_type(run),
        "samples": samples,
        "no_external_image_library": True,
    }
    write_json(test_data_dir / "sample_images_manifest.json", manifest)
    return {
        "test_data_dir": str(test_data_dir),
        "manifest": str(test_data_dir / "sample_images_manifest.json"),
        "samples": samples,
    }


def run_static_runtime_check(project_dir: pathlib.Path) -> dict[str, Any]:
    checked_files = ["README.md", "index.html", "styles.css", "app.js"]
    missing_files = [name for name in checked_files if not (project_dir / name).exists()]
    result = {
        "kind": "ProductStudioRuntimeCheck",
        "status": "PASS" if not missing_files else "PARTIAL",
        "checked_files": checked_files,
        "missing_files": missing_files,
        "local_open_instruction": f"Open {project_dir / 'index.html'} in a local browser.",
        "no_network": True,
        "provider_used": False,
    }
    write_json(project_dir.parent / "runtime_check.json", result)
    return result


def create_test_report(
    run: dict[str, Any],
    runtime_check: dict[str, Any],
    test_data: dict[str, Any],
    out_dir: pathlib.Path,
) -> dict[str, Any]:
    known_limits = [
        "Static runtime file checks only.",
        "No real browser screenshot was captured.",
        "No real file-system image rename was executed.",
    ]
    report = {
        "kind": "ProductStudioTestReport",
        "status": "PARTIAL",
        "checked_items": [
            "generated_project files exist",
            "sample test data exists",
            "static runtime check completed",
            "visual evidence placeholders created",
        ],
        "test_data": test_data,
        "runtime_check": runtime_check,
        "known_limits": known_limits,
        "evidence_needed_next": [
            "real browser screenshot capture",
            "real file-system rename integration test",
        ],
        "no_network": True,
        "provider_used": False,
    }
    write_json(out_dir / "test_report.json", report)
    return report


def create_preview_svg(path: pathlib.Path, title: str, subtitle: str) -> None:
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <rect width="960" height="540" fill="#f4f7f9"/>
  <rect x="72" y="54" width="816" height="96" rx="12" fill="#ffffff" stroke="#d8e0e6"/>
  <text x="104" y="102" font-family="Arial, Helvetica, sans-serif" font-size="30" font-weight="700" fill="#17212b">{html.escape(title)}</text>
  <text x="104" y="132" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#475866">{html.escape(subtitle)}</text>
  <rect x="72" y="184" width="380" height="252" rx="12" fill="#ffffff" stroke="#d8e0e6"/>
  <text x="104" y="232" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" fill="#17212b">Input area</text>
  <rect x="104" y="264" width="284" height="38" rx="8" fill="#edf3f6" stroke="#bac7d0"/>
  <rect x="104" y="328" width="148" height="42" rx="8" fill="#176c7d"/>
  <text x="126" y="356" font-family="Arial, Helvetica, sans-serif" font-size="16" font-weight="700" fill="#ffffff">Run preview</text>
  <rect x="484" y="184" width="404" height="252" rx="12" fill="#ffffff" stroke="#d8e0e6"/>
  <text x="516" y="232" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" fill="#17212b">Preview list</text>
  <text x="516" y="276" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#17212b">holiday_photo_a.svg -> demo_001.svg</text>
  <text x="516" y="316" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#17212b">holiday_photo_b.svg -> demo_002.svg</text>
  <text x="516" y="356" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#17212b">holiday_photo_c.svg -> demo_003.svg</text>
</svg>
""",
        encoding="utf-8",
    )


def create_visual_evidence(run: dict[str, Any], project_dir: pathlib.Path, out_dir: pathlib.Path) -> dict[str, Any]:
    evidence_dir = out_dir / "visual_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    create_preview_svg(evidence_dir / "app_home_preview.svg", project_name(run), "Static visual preview, not a browser screenshot.")
    create_preview_svg(evidence_dir / "result_preview.svg", "Rename Result Preview", "Static SVG rendering of the expected preview state.")
    evidence = {
        "kind": "ProductStudioVisualEvidence",
        "evidence_type": "static_svg_preview",
        "status": "PARTIAL",
        "reason": "no browser screenshot runner in this phase",
        "files": [
            "visual_evidence/app_home_preview.svg",
            "visual_evidence/result_preview.svg",
        ],
        "project_dir": str(project_dir),
        "next_required_step": "real browser screenshot capture",
    }
    write_json(evidence_dir / "visual_evidence.json", evidence)
    return evidence


def create_user_summary(run: dict[str, Any], delivery_dir: pathlib.Path, status: str) -> pathlib.Path:
    path = delivery_dir / "user_summary.md"
    path.write_text(
        f"""# Product Studio Delivery Summary

Status: {status}

Goal: {run.get("customer_intent", {}).get("goal", "Unknown goal")}

Generated:
- Static GUI demo under `generated_project/`
- Sample test data under `test_data/`
- Static runtime check
- Test report
- Static SVG visual previews
- Delivery bundle JSON and zip package

This package is ready for local inspection. It is not a final PASS delivery because real browser screenshots and real file-system image renaming are deferred.
""",
        encoding="utf-8",
    )
    return path


def create_known_limits(delivery_dir: pathlib.Path, limits: list[str]) -> pathlib.Path:
    path = delivery_dir / "known_limits.md"
    content = ["# Known Limits", ""]
    content.extend(f"- {item}" for item in limits)
    content.append("")
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def create_revision_entry(delivery_dir: pathlib.Path) -> dict[str, Any]:
    entry = {
        "kind": "ProductStudioRevisionEntry",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "allowed_revision_types": [
            "ui_change",
            "feature_addition",
            "output_format_change",
            "runtime_bug",
            "test_update",
            "evidence_update",
            "delivery_repackage",
        ],
        "how_to_request_revision": "Describe the requested change and reference the generated delivery bundle.",
        "next_recommended_stage": "runner / browser screenshot / filesystem adapter integration",
    }
    write_json(delivery_dir / "revision_entry.json", entry)
    return entry


def create_delivery_bundle(
    run: dict[str, Any],
    delivery_dir: pathlib.Path,
    generated: dict[str, Any],
    test_report: dict[str, Any],
    visual_evidence: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    bundle = {
        "kind": "ProductStudioDeliveryBundle",
        "status": status,
        "run_file": str(delivery_dir / "product_studio_run.json"),
        "generated_project_dir": generated["project_dir"],
        "project_package": str(delivery_dir / "delivery_bundle.zip"),
        "readme": str(delivery_dir / "generated_project" / "README.md"),
        "user_summary": str(delivery_dir / "user_summary.md"),
        "test_data": str(delivery_dir / "test_data"),
        "test_report": str(delivery_dir / "test_report.json"),
        "visual_evidence": str(delivery_dir / "visual_evidence" / "visual_evidence.json"),
        "known_limits": str(delivery_dir / "known_limits.md"),
        "revision_entry": str(delivery_dir / "revision_entry.json"),
        "included_evidence": [
            "runtime_check.json",
            "test_report.json",
            "visual_evidence/visual_evidence.json",
            "visual_evidence/app_home_preview.svg",
            "visual_evidence/result_preview.svg",
        ],
        "test_report_status": test_report["status"],
        "visual_evidence_status": visual_evidence["status"],
        "boundary_guard_used": False,
        "no_network": True,
        "provider_used": False,
    }
    write_json(delivery_dir / "delivery_bundle.json", bundle)
    return bundle


def zip_delivery_bundle(delivery_dir: pathlib.Path, bundle: dict[str, Any]) -> pathlib.Path:
    zip_path = delivery_dir / "delivery_bundle.zip"
    include_roots = [
        delivery_dir / "generated_project",
        delivery_dir / "test_data",
        delivery_dir / "runtime_check.json",
        delivery_dir / "test_report.json",
        delivery_dir / "visual_evidence",
        delivery_dir / "delivery_bundle.json",
        delivery_dir / "user_summary.md",
        delivery_dir / "known_limits.md",
        delivery_dir / "revision_entry.json",
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in include_roots:
            if item.is_dir():
                for path in sorted(item.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(delivery_dir).as_posix())
            elif item.exists():
                archive.write(item, item.relative_to(delivery_dir).as_posix())
    bundle["project_package"] = str(zip_path)
    write_json(delivery_dir / "delivery_bundle.json", bundle)
    return zip_path


def boundary_guard_decision(run: dict[str, Any], out_dir: pathlib.Path) -> dict[str, Any]:
    import scripts.cgnk_boundary_guard as boundary_guard

    intent = {
        "kind": "AgentActionIntent",
        "agent_id": "agent.product_studio_builder",
        "role": "build_agent",
        "stage": "build",
        "lane": "build",
        "action_type": "write_artifact",
        "reads": ["artifact.build_plan@1"],
        "writes": ["artifact.generated_project@1"],
        "paths_read": [],
        "paths_write": ["generated/project_manifest.json"],
        "tools": ["local_file_write"],
        "provider_request": False,
        "reason": "Generate local static project files for Product Studio delivery.",
    }
    return boundary_guard.BoundaryGuard().decide(intent, run_state={"artifacts": ["artifact.build_plan@1"]})


def deliver(run_file: pathlib.Path, out_dir: pathlib.Path, use_boundary_guard: bool = False) -> dict[str, Any]:
    run = load_run(run_file)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_run = out_dir / "product_studio_run.json"
    if run_file.resolve() != target_run.resolve():
        shutil.copyfile(run_file, target_run)

    guard_result: dict[str, Any] | None = None
    if use_boundary_guard:
        guard_result = boundary_guard_decision(run, out_dir)
        if guard_result["status"] in {"block", "escalate"}:
            blocked = {
                "kind": "ProductStudioDeliveryResult",
                "status": "BLOCKED",
                "boundary_guard_used": True,
                "boundary_guard_decision": guard_result,
                "no_network": True,
                "provider_used": False,
            }
            write_json(out_dir / "delivery_result.json", blocked)
            return blocked

    generated = build_generated_project(run, out_dir)
    test_data = create_test_data(run, out_dir)
    runtime_check = run_static_runtime_check(pathlib.Path(generated["project_dir"]))
    test_report = create_test_report(run, runtime_check, test_data, out_dir)
    visual_evidence = create_visual_evidence(run, pathlib.Path(generated["project_dir"]), out_dir)

    status = "PARTIAL"
    limits = [
        "当前是本地静态交付闭环。",
        "尚未接真实 provider。",
        "尚未接真实 Telegram 文件发送。",
        "尚未做真实浏览器截图。",
        "尚未做真实文件系统图片重命名。",
        "下一步可以接 runner / browser screenshot / filesystem adapter。",
    ]
    create_user_summary(run, out_dir, status)
    create_known_limits(out_dir, limits)
    create_revision_entry(out_dir)
    bundle = create_delivery_bundle(run, out_dir, generated, test_report, visual_evidence, status)
    bundle["boundary_guard_used"] = bool(use_boundary_guard)
    if guard_result is not None:
        bundle["boundary_guard_decision"] = guard_result
    write_json(out_dir / "delivery_bundle.json", bundle)
    zip_path = zip_delivery_bundle(out_dir, bundle)

    result = {
        "kind": "ProductStudioDeliveryResult",
        "status": status,
        "delivery_dir": str(out_dir),
        "delivery_bundle": str(out_dir / "delivery_bundle.json"),
        "delivery_bundle_zip": str(zip_path),
        "boundary_guard_used": bool(use_boundary_guard),
        "no_network": True,
        "provider_used": False,
    }
    write_json(out_dir / "delivery_result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a minimal local Product Studio delivery bundle.")
    parser.add_argument("--run-file", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--use-boundary-guard", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = deliver(args.run_file, args.out, use_boundary_guard=args.use_boundary_guard)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Product Studio delivery: {result['status']}")
        print(f"Delivery dir: {result.get('delivery_dir', args.out)}")
        if "delivery_bundle_zip" in result:
            print(f"Delivery zip: {result['delivery_bundle_zip']}")
    return 0 if result["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
