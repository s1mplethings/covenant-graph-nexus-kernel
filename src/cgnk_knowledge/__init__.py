"""Deterministic conversation knowledge system for CGNK."""

from .context_pack import build_agent_context_pack
from .dialogue_integration import update_knowledge_from_dialogue_turn
from .event_log import append_event, events_from_jsonl, events_to_jsonl, list_events
from .keypoint_extract import extract_keypoints_from_turn
from .internalization import (
    KnowledgeMaintenancePolicy,
    KnowledgeRelation,
    internalize_evidence,
    make_derived_abstraction,
    raw_content_hash,
    refresh_stale_abstractions,
)
from .normalize import normalize_keypoints_to_knowledge_items
from .persistence import (
    DEFAULT_POLICY,
    FORMAT_VERSION as PERSISTENCE_FORMAT_VERSION,
    KnowledgePersistenceError,
    KnowledgePersistenceBackend,
    PersistencePolicy,
    SegmentedKnowledgeStore,
    authoritative_projection,
    build_pack_mutation,
    detect_persistence_format,
    migrate_legacy_pack,
    project_knowledge_semantic_hash,
    rollback_legacy_migration,
)
from .retrieve import retrieve_relevant_knowledge
from .store import (
    archive_knowledge_item,
    build_knowledge_index,
    rebuild_pack_indexes,
    discard_knowledge_item,
    load_legacy_project_knowledge,
    load_project_knowledge,
    new_project_knowledge_pack,
    save_project_knowledge,
    save_legacy_project_knowledge,
    upsert_knowledge_items,
)

__all__ = [
    "append_event",
    "archive_knowledge_item",
    "build_knowledge_index",
    "build_agent_context_pack",
    "discard_knowledge_item",
    "detect_persistence_format",
    "events_from_jsonl",
    "events_to_jsonl",
    "extract_keypoints_from_turn",
    "internalize_evidence",
    "list_events",
    "load_project_knowledge",
    "load_legacy_project_knowledge",
    "new_project_knowledge_pack",
    "KnowledgeMaintenancePolicy",
    "KnowledgeRelation",
    "KnowledgePersistenceError",
    "KnowledgePersistenceBackend",
    "PersistencePolicy",
    "PERSISTENCE_FORMAT_VERSION",
    "DEFAULT_POLICY",
    "normalize_keypoints_to_knowledge_items",
    "retrieve_relevant_knowledge",
    "raw_content_hash",
    "rebuild_pack_indexes",
    "refresh_stale_abstractions",
    "save_project_knowledge",
    "save_legacy_project_knowledge",
    "SegmentedKnowledgeStore",
    "authoritative_projection",
    "build_pack_mutation",
    "migrate_legacy_pack",
    "project_knowledge_semantic_hash",
    "rollback_legacy_migration",
    "update_knowledge_from_dialogue_turn",
    "upsert_knowledge_items",
    "make_derived_abstraction",
]
