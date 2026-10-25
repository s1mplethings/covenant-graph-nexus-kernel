from __future__ import annotations

import pytest

from cgkn.application.community.contracts import CommunityPolicy, CommunityPost, CommunityThread
from cgkn.application.promotion.contracts import PromotionClaim
from cgkn.application.promotion.service import PromotionClaimLedger


@pytest.fixture
def community_policy():
    return CommunityPolicy("source", "policy-v1", True, "ALLOWED_WITH_DISCLOSURE", "ALLOWED", "OFFICIAL_API_WITH_APPROVAL", "DISCLOSE", 3, 2, source_urls=("https://example.invalid/rules",))


@pytest.fixture
def claim_ledger():
    return PromotionClaimLedger((PromotionClaim("claim-1", "CGKN keeps one CapabilityTree and one ExecutionDAG authority.", ("source:goal",)),))


def make_thread(case_id: str, metadata: dict, *, platform: str = "github", content: str = "How should RAG agent repair preserve interfaces?") -> CommunityThread:
    thread_id = f"thread-{case_id}"
    post = CommunityPost(f"post-{case_id}", thread_id, None, "public-user", content, "2026-10-25T00:00:00Z", public_metadata=metadata, our_reply_target=True)
    return CommunityThread(thread_id, platform, f"https://example.invalid/{case_id}", "RAG agent repair", "public-user", post.created_at, post.created_at, "test", (), (post,), content, (post.post_id,), float(metadata.get("relevance", 0)))

