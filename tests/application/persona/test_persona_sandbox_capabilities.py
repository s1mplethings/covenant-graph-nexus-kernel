from __future__ import annotations

import pytest

from cgkn.application.persona.capabilities import build_persona_registry
from cgkn.application.persona.service import SocialSandbox


def test_persona_capabilities_share_registry_boundary_and_have_no_external_write():
    registry = build_persona_registry(); rows = registry.query()
    assert len(rows) == 7
    assert all(row.lifecycle_status.value == "ADMITTED" for row in rows)
    assert registry.query(effect="external.write") == ()


def test_social_sandbox_is_advisory_and_detects_risk():
    result = SocialSandbox.rehearse(public_thread="How should repair preserve interfaces?", draft="Check out CGKN, the best tool. We tested it 100%.",
                                    community_policy={"maintainer_only": True}, disclosure="", approved_claims=())
    assert result["aggregate"] == "SOCIAL_REHEARSAL_HIGH_RISK"
    assert result["authority"] == "ADVISORY_ONLY"
    assert not result["writes_relationship_state"] and not result["approval_bypass"]


def test_social_sandbox_accepts_specific_low_risk_draft():
    result = SocialSandbox.rehearse(public_thread="How should repair preserve interfaces?",
                                    draft="Preserve the current interface manifest, invalidate only affected nodes, and rerun downstream checks.",
                                    community_policy={}, disclosure="", approved_claims=(), roles=("MAINTAINER", "SKEPTICAL_EXPERT", "NEWCOMER"))
    assert result["aggregate"] == "SOCIAL_REHEARSAL_PASS"


@pytest.mark.parametrize("roles", (("MAINTAINER",), ("UNKNOWN", "NEWCOMER", "PROJECT_USER"), SocialSandbox.ROLES))
def test_social_sandbox_role_bounds(roles):
    with pytest.raises(ValueError, match="3-6"):
        SocialSandbox.rehearse(public_thread="x", draft="x", community_policy={}, disclosure="", approved_claims=(), roles=roles)
