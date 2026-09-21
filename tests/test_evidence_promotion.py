from __future__ import annotations

import importlib.util
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "promote_evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("promote_evidence_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promotion_keeps_summary_and_excludes_raw_run_payload(tmp_path: pathlib.Path) -> None:
    module = load_module()
    run = tmp_path / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "run_summary.json").write_text(
        json.dumps(
            {
                "metrics": {"passed": 3},
                "cache": {"huge": True},
                "raw_provider_response": "must not be promoted",
                "checkpoints": [1, 2, 3],
            }
        ),
        encoding="utf-8",
    )
    (run / "provider_output.json").write_text('{"raw": true}', encoding="utf-8")
    output = tmp_path / "evidence" / "test" / "v1"

    bundle = module.promote(run, output, "bounded claim", "NOT_EVALUATED", "python reproduce.py")

    rendered = json.dumps(bundle)
    assert "must not be promoted" not in rendered
    assert "checkpoints" not in bundle["metrics"]["run_summary"]
    assert bundle["sourceHashes"][0]["source"] == "run_summary.json"
    assert bundle["evidenceStatus"] == "NOT_EVALUATED"
    assert (output / "verification_summary.json").is_file()
