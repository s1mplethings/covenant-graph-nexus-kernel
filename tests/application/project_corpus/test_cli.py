from __future__ import annotations

import json
import pathlib

from cgkn.application.project_corpus import ProjectCorpus
from cgkn.cli import main


def test_corpus_cli_init_stats_search_and_verify(tmp_path: pathlib.Path, capsys):
    root = tmp_path / "corpus"
    assert main(["corpus", "--root", str(root), "init"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    ProjectCorpus(root).capture_attempt(
        family_id="family-1",
        attempt_id="attempt-1",
        run_id="run-1",
        source_version="source-1",
        generator_version="generator-1",
        status="FAIL",
        provenance="generated_original",
        public_packet={"requirement": "CSV cleaner"},
        snapshots=[{"stage": "FAILED_TEST", "files": {"app.py": "raise RuntimeError\n"}}],
        failures=[{"failure_type": "TEST", "fingerprint": "failure-1"}],
    )
    assert main(["corpus", "--root", str(root), "search", "--status", "FAIL"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["family_id"] == "family-1"
    assert main(["corpus", "--root", str(root), "stats"]) == 0
    assert json.loads(capsys.readouterr().out)["attempts"] == 1
    assert main(["corpus", "--root", str(root), "verify"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
