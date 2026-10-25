# Security policy

## Supported versions

Security fixes target the current review candidate and the latest tagged
Research Preview. Older experimental snapshots are not supported releases.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for
`s1mplethings/covenant-graph-nexus-kernel` when available. Do not open a public
issue containing credentials, exploit details, private paths, or private data.

## Security boundaries

- Provider credentials are process-local secrets and must never be accepted as
  CLI arguments, written to receipts, or included in model prompts.
- Public writes require an exact, current approval. A draft or an offline
  adapter qualification is not authorization to publish.
- Executors are bounded by declared effects and scope. Retrieved content and
  public benchmark inputs are untrusted data.
- Benchmark gold answers, hidden assertions, and fixing commits must not enter
  CGKN Knowledge, prompts, or persistent learning state.
- Postiz is a separately deployed AGPL-3.0 transport service. CGKN contains
  only its API boundary and does not vendor Postiz code.

Release publication additionally requires a secret scan, local-path/privacy
scan, repository-history review, provenance audit, clean-clone reproduction,
and zero P0 release blockers.
