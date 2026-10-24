# Promotion platform and Postiz reference audit

Captured 2026-10-25. The machine-readable matrix is in
`benchmarks/promotion_v1/fixtures/platform_connectivity_matrix.json`.

CGKN implements native protocol adapters for Bluesky, Mastodon, and YouTube,
with real publication disabled unless an exact approval and local opaque
credential reference are present. Offline contract qualification uses injected
HTTP transports and never contacts a public account.

Postiz is an optional process boundary. Its public API/provider pattern,
official OAuth approach, media-before-post flow, idempotent scheduling concepts,
analytics surface, and self-hosted deployment informed the bridge contract.
These are `BORROWED_CONCEPT` items. CGKN's evidence/claim authority, approval
hash binding, local PublicationPlan authority, and receipts are
`REIMPLEMENTED_DIFFERENTLY`. Postiz's database, AI drafting, Temporal scheduler,
and campaign authority are `NOT_NEEDED`.

No Postiz source was copied. Postiz is AGPL-3.0 and may only run as a separately
self-hosted service reached through its documented API/CLI/MCP boundary.
