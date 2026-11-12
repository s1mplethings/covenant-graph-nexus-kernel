"""CharacterCut P2 deterministic capabilities for the VeriArbor Host.

No provider calls. The clip policy consumes the historical CharacterCut export
and produces a new, source-traceable P2 deliverable. Technical acceptance reuses
the P1 media acceptance tool.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import time
from typing import Any, Mapping

from cgkn.execution import (BlockExecutionRequest, BlockExecutionResult, BlockStatus,
                            ExecutionError, ExecutionErrorCode)
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

TRIAL = pathlib.Path(r"C:\Users\sunom\VeriArbor-Experiments\real-product-growth-v1-20261108")
HISTORICAL_EXPORT = pathlib.Path(r"F:\CharacterCut\exports\twilight-full-reviewed\608f9d2d74f5456081e824a32424bf87")
CHARACTER_DB = pathlib.Path(r"F:\CharacterCut\projects\tamers4-twilight\character.sqlite")
SOURCE = pathlib.Path(r"Q:\tamers\4) Twilight Sparkle Shows Trixie The True Meaning Of Friendship Whether She Likes It Or Not.mp4")
ACCEPTANCE_TOOL = TRIAL / "tools" / "media_acceptance.py"
FFMPEG = r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
FFPROBE = r"C:\Program Files\ffmpeg\bin\ffprobe.exe"
MERGE_GAP_MS = 1000
MIN_DELIVERY_MS = 1000
POLICY_VERSION = "clip-policy-v1"


class _BoundedExecutor:
    def __init__(self, capability, function, *, executor_ref=None, timeout=900):
        self.capability = capability
        self.function = function
        ref = executor_ref or capability
        self.descriptor = ExecutorDescriptor(ref, "charactercut_p2", (capability,),
                                            ("filesystem.read", "filesystem.write", "process.execute"),
                                            default_timeout_seconds=timeout)

    def execute(self, request):
        return self.function(request)


def _sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _result(request, outputs, *, status=BlockStatus.SUCCEEDED, error=None, started="", clock=None):
    return BlockExecutionResult(
        project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id,
        node_id=request.node_id, executor_ref=request.executor_ref, status=status,
        outputs=dict(outputs), error=error, started_at=started or utc_now(), ended_at=utc_now(),
        duration_ms=max(0, int((time.perf_counter() - (clock or time.perf_counter())) * 1000)))


def _appearances() -> dict[str, dict]:
    import sqlite3
    con = sqlite3.connect("file:" + str(CHARACTER_DB).replace("\\", "/") + "?mode=ro", uri=True)
    rows = [json.loads(r[0]) for r in con.execute("select data from character_appearances")]
    con.close()
    return {str(r["id"]): r for r in rows}


def _concat(paths: list[pathlib.Path], output: pathlib.Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    listing = output.parent / (output.stem + ".concat.txt")
    listing.write_text("".join("file '" + str(p).replace("\\", "/") + "'\n" for p in paths), encoding="utf-8")
    proc = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0",
                           "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(output)],
                          capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg concat failed: " + proc.stderr[-1000:])


def _accept(path: pathlib.Path, out: pathlib.Path, min_seconds: float = 1.0) -> dict:
    proc = subprocess.run([sys.executable, str(ACCEPTANCE_TOOL), str(path),
                           "--min-seconds", str(min_seconds), "--require-audio", "--out", str(out)],
                          capture_output=True, text=True, timeout=600, check=False)
    receipt = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    receipt["tool_returncode"] = proc.returncode
    return receipt


def exec_clip_policy(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    out_root = pathlib.Path(cfg.get("output_root") or (TRIAL / "p2-charactercut" / "run-01" / "OUTPUT" / "clip-policy-attempt"))
    out_root.mkdir(parents=True, exist_ok=True)
    try:
        manifest = json.loads((HISTORICAL_EXPORT / "clip_manifest.json").read_text(encoding="utf-8"))
        appearances = _appearances()
        source_duration = 1604174
        clips = sorted(manifest["clips"], key=lambda c: (int(c["start_ms"]), int(c["end_ms"])))
        groups: list[dict] = []
        for clip in clips:
            start, end = int(clip["start_ms"]), int(clip["end_ms"])
            if groups and start - groups[-1]["end_ms"] <= MERGE_GAP_MS:
                groups[-1]["clips"].append(clip)
                groups[-1]["end_ms"] = max(groups[-1]["end_ms"], end)
            else:
                groups.append({"clips": [clip], "start_ms": start, "end_ms": end})
        delivered, evidence_only = [], []
        clip_dir = out_root / "clips"
        for index, group in enumerate(groups, 1):
            duration = sum(int(c["end_ms"]) - int(c["start_ms"]) for c in group["clips"])
            states = []
            refs = []
            for c in group["clips"]:
                refs.extend(c.get("appearance_refs", []))
                for ref in c.get("appearance_refs", []):
                    row = appearances.get(str(ref))
                    states.append(row.get("verification_status") if row else ("CONFIRMED" if str(ref).startswith("manual-") else "UNREVIEWED"))
            identity_state = "CONFIRMED" if any(s == "CONFIRMED" for s in states) else ("UNREVIEWED" if states else "UNKNOWN")
            output = clip_dir / f"group_{index:04d}_{group['start_ms']}-{group['end_ms']}.mp4"
            _concat([pathlib.Path(c["output"]) for c in group["clips"]], output)
            entry = {
                "clip_id": f"p2-group-{index:04d}",
                "source_intervals": [[int(c["start_ms"]), int(c["end_ms"])] for c in group["clips"]],
                "output": str(output),
                "output_duration_ms": duration,
                "identity_state": identity_state,
                "identity_evidence_refs": sorted(set(map(str, refs))),
                "confidence": None,
                "confidence_type": "UNCALIBRATED_HISTORICAL_EXPORT",
                "review_state": "HUMAN_CONFIRMED" if identity_state == "CONFIRMED" else "UNREVIEWED",
                "strategy_version": "historical-export-608f9d2d+clip-policy-v1",
                "deliverability": "DELIVER" if duration >= MIN_DELIVERY_MS else "EVIDENCE_ONLY",
                "policy_version": POLICY_VERSION,
            }
            (delivered if entry["deliverability"] == "DELIVER" else evidence_only).append(entry)
        collection = out_root / "collection.mp4"
        _concat([pathlib.Path(e["output"]) for e in delivered], collection)
        technical = _accept(collection, out_root / "evidence" / "collection_acceptance.json", 1.0)
        delivered_acceptance = []
        for entry in delivered:
            receipt = _accept(pathlib.Path(entry["output"]), out_root / "evidence" / (entry["clip_id"] + ".json"), 1.0)
            entry["technical_status"] = receipt.get("status")
            entry["sha256"] = _sha(pathlib.Path(entry["output"]))
            delivered_acceptance.append({"clip_id": entry["clip_id"], "status": receipt.get("status"),
                                         "sha256": entry["sha256"]})
        for entry in evidence_only:
            entry["technical_status"] = "NOT_APPLICABLE_EVIDENCE_ONLY"
        timeline = {
            "kind": "CharacterTimeline", "schema_version": "1.0",
            "source": {"path": str(SOURCE), "sha256": _sha(SOURCE), "duration_ms": source_duration},
            "character_id": manifest.get("character_id"),
            "strategy_version": "historical-export-608f9d2d+clip-policy-v1",
            "policy_version": POLICY_VERSION,
            "entries": delivered + evidence_only,
        }
        new_manifest = {
            "kind": "CharacterClipManifest", "schema_version": "1.0",
            "source": {"path": str(SOURCE), "sha256": _sha(SOURCE)},
            "character_id": manifest.get("character_id"),
            "policy_version": POLICY_VERSION,
            "historical_export": {"id": manifest.get("id"), "manifest_sha256": _sha(HISTORICAL_EXPORT / "clip_manifest.json")},
            "clips": delivered + evidence_only,
            "delivered_clip_ids": [e["clip_id"] for e in delivered],
            "evidence_only_clip_ids": [e["clip_id"] for e in evidence_only],
            "compilation": {"path": str(collection), "sha256": _sha(collection),
                            "duration_ms": technical.get("duration_seconds", 0) * 1000 if technical.get("duration_seconds") else None,
                            "technical_status": technical.get("status")},
        }
        policy = {
            "kind": "CharacterClipPolicyEvidence", "schema_version": "1.0",
            "policy_version": POLICY_VERSION,
            "source_manifest": str(HISTORICAL_EXPORT / "clip_manifest.json"),
            "source_manifest_sha256": _sha(HISTORICAL_EXPORT / "clip_manifest.json"),
            "rules": {"merge_gap_ms": MERGE_GAP_MS, "min_delivery_ms": MIN_DELIVERY_MS,
                      "short_isolated": "EVIDENCE_ONLY, retained in manifest/timeline, excluded from compilation",
                      "no_simple_duration_filter": True},
            "before": {"clips": len(clips), "under_1s": sum(1 for c in clips if int(c["end_ms"]) - int(c["start_ms"]) < 1000),
                       "under_100ms": sum(1 for c in clips if int(c["end_ms"]) - int(c["start_ms"]) < 100)},
            "after": {"delivered": len(delivered), "evidence_only": len(evidence_only),
                      "under_1s_delivered": sum(1 for e in delivered if e["output_duration_ms"] < 1000)},
            "technical": technical,
            "delivered_acceptance": delivered_acceptance,
        }
        _write(out_root / "character_timeline.json", timeline)
        _write(out_root / "clip_manifest.json", new_manifest)
        _write(out_root / "evidence" / "clip_policy.json", policy)
        passed = (technical.get("status") == "PASS" and
                  all(e["technical_status"] == "PASS" for e in delivered) and
                  all(e["output_duration_ms"] >= MIN_DELIVERY_MS for e in delivered))
        outputs = {"clip_policy": {"root": str(out_root), "timeline": str(out_root / "character_timeline.json"),
                                   "manifest": str(out_root / "clip_manifest.json"),
                                   "evidence": str(out_root / "evidence" / "clip_policy.json"),
                                   "delivered": len(delivered), "evidence_only": len(evidence_only),
                                   "under_1s_delivered": policy["after"]["under_1s_delivered"],
                                   "technical_status": technical.get("status")}}
        if not passed:
            return _result(request, outputs, status=BlockStatus.FAILED,
                           error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                                                "clip policy technical acceptance failed"),
                           started=started, clock=clock)
        return _result(request, outputs, started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


def _read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def check_clip_policy(root: pathlib.Path, contract: Mapping[str, Any]) -> dict:
    # The deliverable checker root is the CharacterCut output root; locate the latest policy output.
    base = pathlib.Path(r"C:\Users\sunom\VeriArbor-Experiments\real-product-growth-v1-20261108\p2-charactercut\run-01\OUTPUT")
    candidates = sorted([p for p in base.iterdir() if p.is_dir() and p.name.startswith("clip-policy-")] if base.is_dir() else [],
                        key=lambda p: p.stat().st_mtime)
    if not candidates:
        return {"passed": False, "observed": {"error": "no clip-policy output"}, "artifacts": []}
    out = candidates[-1]
    manifest = _read_json(out / "clip_manifest.json")
    timeline = _read_json(out / "character_timeline.json")
    policy = _read_json(out / "evidence" / "clip_policy.json")
    delivered = [e for e in manifest.get("clips", []) if e.get("deliverability") == "DELIVER"]
    evidence_only = [e for e in manifest.get("clips", []) if e.get("deliverability") == "EVIDENCE_ONLY"]
    checks = {
        "manifest_present": bool(manifest),
        "timeline_present": bool(timeline),
        "policy_present": bool(policy),
        "delivered_nonempty": bool(delivered),
        "no_short_delivery": all(int(e.get("output_duration_ms", 0)) >= MIN_DELIVERY_MS for e in delivered),
        "evidence_only_retained": len(evidence_only) == len(manifest.get("evidence_only_clip_ids", [])),
        "all_delivered_technical": all(e.get("technical_status") == "PASS" for e in delivered),
        "compilation_technical": manifest.get("compilation", {}).get("technical_status") == "PASS",
        "source_intervals_valid": all(0 <= a < b <= 1604174 for e in manifest.get("clips", []) for a, b in e.get("source_intervals", [])),
    }
    return {"passed": all(checks.values()), "observed": {"output": str(out), "checks": checks,
            "delivered": len(delivered), "evidence_only": len(evidence_only)},
            "artifacts": [str(out / "clip_manifest.json"), str(out / "character_timeline.json"),
                          str(out / "evidence" / "clip_policy.json")]}


def exec_identity_review(request: BlockExecutionRequest) -> BlockExecutionResult:
    started, clock = request.created_at, time.perf_counter()
    cfg = dict(request.task_context.node_config)
    out_root = pathlib.Path(cfg.get("output_root") or (TRIAL / "p2-charactercut" / "run-01" / "OUTPUT" / "identity-review"))
    out_root.mkdir(parents=True, exist_ok=True)
    try:
        review = json.loads((TRIAL / "p2-charactercut" / "run-01" / "REVIEW_SET" / "REVIEW_SET.json").read_text(encoding="utf-8"))
        latest = pathlib.Path(r"F:\CharacterCut\projects\tamers4-twilight\runs\d905580d6dca4888a98cc280d35e8f3d")
        identities = json.loads((latest / "identities.json").read_text(encoding="utf-8"))
        regions = json.loads(pathlib.Path(r"F:\CharacterCut\projects\tamers4-twilight\runs\444452eba63642dbab9e1f27655cd704\regions.json").read_text(encoding="utf-8"))
        region_by_id = {str(r["id"]): r for r in regions}
        # Nearest identity observation at or before the review timestamp (1 s sampling).
        by_time = []
        for identity in identities:
            region = region_by_id.get(str(identity.get("region_id")))
            if region:
                by_time.append((int(region["frame_timestamp_ms"]), identity))
        by_time.sort(key=lambda x: x[0])
        predictions = []
        for item in review["items"]:
            ts = int(item["timestamp_ms"])
            candidates = [x for x in by_time if abs(x[0] - ts) <= 1000]
            if not candidates:
                predictions.append({"id": item["id"], "timestamp_ms": ts, "prediction": "UNKNOWN",
                                    "confidence": None, "evidence_ref": None, "reason": "NO_OBSERVATION_WITHIN_1S"})
                continue
            _, identity = min(candidates, key=lambda x: abs(x[0] - ts))
            predictions.append({"id": item["id"], "timestamp_ms": ts,
                                "prediction": identity.get("character_id", "UNKNOWN"),
                                "confidence": identity.get("similarity"),
                                "evidence_ref": identity.get("region_id"),
                                "reason": "NEAREST_OBSERVATION_WITHIN_1S"})
        counts: dict[str, int] = {}
        for p in predictions:
            counts[p["prediction"]] = counts.get(p["prediction"], 0) + 1
        report = {
            "kind": "CharacterCutIdentityPredictions", "schema_version": "1.0",
            "review_set_sha256": _sha(TRIAL / "p2-charactercut" / "run-01" / "REVIEW_SET" / "REVIEW_SET.json"),
            "baseline_run": str(latest),
            "baseline_run_sha256": {"identities": _sha(latest / "identities.json"),
                                    "tracks": _sha(latest / "tracks.json")},
            "method": "nearest existing identity observation within 1 s; no new model call",
            "labels_status": "PENDING_INDEPENDENT_REVIEW",
            "independent_human_ground_truth": False,
            "counts": counts,
            "predictions": predictions,
            "limitations": ["No independent labels; precision/recall cannot be computed.",
                            "Predictions are a baseline replay, not a new model run.",
                            "Strata labels are pending; strata-specific accuracy unavailable."],
        }
        _write(out_root / "REVIEW_SET_PREDICTIONS.json", report)
        uncertainty = {
            "kind": "CharacterCutIdentityUncertainty", "schema_version": "1.0",
            "baseline_counts": {"identities": len(identities),
                                "character": sum(1 for i in identities if i.get("character_id") != "UNKNOWN"),
                                "unknown": sum(1 for i in identities if i.get("character_id") == "UNKNOWN")},
            "review_set_counts": counts,
            "unknown_rate_review_set": counts.get("UNKNOWN", 0) / max(1, len(predictions)),
            "known_failures": ["UNKNOWN coverage", "no independent GT", "side/back/far/occlusion unmeasured"],
            "status": "IDENTITY_REVIEW_PENDING",
        }
        _write(out_root / "IDENTITY_UNCERTAINTY_REPORT.json", uncertainty)
        return _result(request, {"identity_review": {"root": str(out_root),
                                                     "predictions": str(out_root / "REVIEW_SET_PREDICTIONS.json"),
                                                     "uncertainty": str(out_root / "IDENTITY_UNCERTAINTY_REPORT.json"),
                                                     "counts": counts}}, started=started, clock=clock)
    except Exception as exc:  # noqa: BLE001
        return _result(request, {}, status=BlockStatus.FAILED,
                       error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)),
                       started=started, clock=clock)


def check_identity_review(root: pathlib.Path, contract: Mapping[str, Any]) -> dict:
    base = pathlib.Path(r"C:\Users\sunom\VeriArbor-Experiments\real-product-growth-v1-20261108\p2-charactercut\run-01\OUTPUT\identity-review")
    pred = _read_json(base / "REVIEW_SET_PREDICTIONS.json")
    unc = _read_json(base / "IDENTITY_UNCERTAINTY_REPORT.json")
    checks = {"predictions_present": bool(pred), "uncertainty_present": bool(unc),
              "labels_not_claimed": pred.get("independent_human_ground_truth") is False,
              "status_review_pending": unc.get("status") == "IDENTITY_REVIEW_PENDING"}
    return {"passed": all(checks.values()), "observed": {"checks": checks,
            "counts": pred.get("counts")}, "artifacts": [str(base / "REVIEW_SET_PREDICTIONS.json"),
                                                         str(base / "IDENTITY_UNCERTAINTY_REPORT.json")]}


def build_catalog(output_root: pathlib.Path) -> dict:
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    clip = build_leaf_contract(
        goal="apply a deliverability policy to the historical character clips",
        kind="IMPLEMENTATION", scope=["clip-policy-attempt/character_timeline.json", "clip-policy-attempt/clip_manifest.json", "clip-policy-attempt/evidence/clip_policy.json"],
        acceptance=["character.clip_quality"], checker="character.check.clip_quality@1",
        output_identity="character.clip.policy", effect_domains=["filesystem"],
        executor="character.clip.policy@1", dependencies=[],
        expected_delta="no delivered 40 ms fragment; retained evidence-only items; traceable compilation")
    identity = build_leaf_contract(
        goal="measure the existing identity baseline on the frozen review set",
        kind="INSPECTION", scope=["identity-review/REVIEW_SET_PREDICTIONS.json", "identity-review/IDENTITY_UNCERTAINTY_REPORT.json"],
        acceptance=["character.identity_review"], checker="character.check.identity_review@1",
        output_identity="character.identity.review", effect_domains=["filesystem"],
        executor="character.identity.review@1", dependencies=[],
        subject="frozen review set", expected_observation="predictions + uncertainty report",
        pass_fail_rule="report present and honest about missing independent labels")
    return {
        "character.clip.policy@1": {"executor_ref": "character.clip.policy@1",
            "config": {"executor_ref": "character.clip.policy@1", "workdir": str(output_root),
                       "output_root": str(output_root / "clip-policy-attempt"), "leaf_contract": clip}},
        "character.identity.review@1": {"executor_ref": "character.identity.review@1",
            "config": {"executor_ref": "character.identity.review@1", "workdir": str(output_root),
                       "output_root": str(output_root / "identity-review"), "leaf_contract": identity}},
    }
