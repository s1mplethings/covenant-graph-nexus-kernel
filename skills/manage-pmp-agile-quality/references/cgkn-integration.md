# CGKN Integration

## Self-hosting

Use `project_management/current/` as the current management snapshot. Keep
`PROJECT_MANAGEMENT.md`, `backlog.json`, `risks.json`, and
`active_iteration.json` synchronized. Completed release-level history belongs
under `project_management/summaries/`, not an unbounded tracked iteration archive.

Use `project_management/current/enterprise_experience.json` as the structured
organizational experience store. Retrieve bounded relevant items before
planning. Record a usage receipt before changing confidence or declaring a
practice effective.

## Generated projects

Feed the tailored project goal, selected backlog item, acceptance criteria,
quality metrics, direct interface expectations, and selected enterprise
experience into the existing provider component/leaf context. Use the current
generation-context librarian; do not copy the whole management pack into every
prompt.

## Authority boundaries

This skill may propose and validate planning artifacts. It must not:

- become a second Codex conversation generation mainline;
- reconnect a legacy local generator;
- authorize formal PASS;
- replace canonical test/runtime/visual evidence;
- package or publicly deliver outside `local_packager`;
- silently weaken fixed kernel or public-delivery constraints.
