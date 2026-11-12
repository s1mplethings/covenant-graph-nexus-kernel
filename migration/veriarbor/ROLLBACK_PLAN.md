# Bounded rollback

Use AUTHORITY_SWITCH_RECEIPTS.jsonl in reverse order. For each row verify the
current file SHA-256 equals after_sha256, and the snapshot equals before_sha256.
Restore only that file's bytes. If a hash differs, stop and reconcile the newer
edit; never reset/clean this dirty worktree. Snapshots preserve pre-existing
uncommitted user work. Do not import rollback snapshots in production.

New adapters can remain unused after rollback. Removing them requires confirming
there are no live imports. The isolated editable package can remain installed;
no global Python changes are needed. No rollback modifies historical acceptance,
Provider responses, UNKNOWN records, accounting, Corpus or product candidates.

Switch receipts initially say PENDING_REGRESSION. REGRESSION.json and the final
migration receipt bind completed checks to the final source manifest. No pending
entry is itself a claim that its gate passed.
