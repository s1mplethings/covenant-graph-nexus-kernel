from __future__ import annotations

import pathlib
import pytest

from cgkn.application.promotion.contracts import Privacy
from cgkn.application.promotion.service import EvidenceProjector, PromotionStudio


@pytest.fixture
def public_pack():
    return EvidenceProjector.project(
        project_id="cgkn",
        source_commit="a08af029754aac4176c38f36e928295a90cf1c85",
        evidence_ids=("source:a08af02", "receipt:self-growth-v1"),
        facts=("Self-Growth V1 completed its bounded qualification suite.", "Production routing remains fixed."),
        metrics={"qualification_cases": 21, "false_passes": 0},
        changed_capabilities=("self_growth.classify", "self_growth.qualify"),
        before_after={"qualification": {"before": 0, "after": 21}},
        candidate_assets=(),
        privacy=Privacy.PUBLIC,
    )


@pytest.fixture
def studio(tmp_path: pathlib.Path):
    return PromotionStudio(tmp_path / "assets")
