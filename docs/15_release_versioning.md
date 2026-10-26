# CGNK release versioning

CGNK uses semantic versions for repository releases:

- `MAJOR` changes an externally relied-on kernel, contract, or integration boundary.
- `MINOR` adds compatible formal capabilities or materially expands the reviewed mainline.
- `PATCH` contains compatible fixes without a new formal capability.
- `-rc.N` marks a review candidate that is uploadable for evaluation but is not a stable release.

The repository version is recorded in `VERSION`. Git release tags use the same value with a
leading `v`, but a tag is created only after the applicable quality gates pass. Uploading a review
branch does not imply formal acceptance or public release.

Companion packages follow their ecosystem's equivalent notation:

- Codex plugin: repository SemVer plus one `+codex.<cachebuster>` suffix for local pickup.
- Python Agent Kit: PEP 440 (`0.2.0rc5` for repository version `0.2.0-rc.5`).
- MCP server protocol identity: repository SemVer without the Codex cachebuster.

## Current review candidate

`0.2.0-rc.5` is a Research Preview data-foundation release. It adds a local,
content-addressed Project Corpus for project-attempt evidence and replay without
changing Knowledge, planning, execution, or project-state authority. It does
not publish a dataset, adopt a Router or Multi-Agent runtime, or claim that
corpus capture itself improves generation quality.

Runtime workspaces, generated project memory, media, transient evidence, and local `.cgkn` state are
not release source and must not be committed to the review branch.

Repository review-branch publication uses `python scripts/canonical_repo_publish.py`. Its prepare step writes ignored local support receipts, while publish accepts only a conventional commit message, an identity-bound passing test receipt, the exact deterministic commit set, a passing canonical version gate, clean post-commit verification, an unchanged remote baseline, and fetched remote SHA equality after a normal push. Generated projects may adopt the same lightweight sequence with project-sized test commands; this does not connect repository publication to CGNK's product delivery route.

## Supersession and retirement

The active tree exposes current truth only. Structural upgrades declare `supersedes`, migrate formal consumers, verify the replacement, retire old producers and entrypoints, and freeze the result with `python scripts/canonical_version_gate.py`. Compatibility is limited to reading, decoding, projecting, or migrating an older format and must name a future `remove_in`; it cannot become a new canonical producer. Detailed implementation history remains in Git. `project_management/current/` contains only the current management snapshot, while bounded release summaries live under `project_management/summaries/`.
