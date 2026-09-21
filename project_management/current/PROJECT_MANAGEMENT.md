# CGKN current project management

CGKN uses a lightweight hybrid delivery model: stable kernel, Provider,
evidence, packaging, and delivery contracts remain fixed while repository and
product increments are implemented on bounded branches.

The current machine-readable surfaces are:

- `backlog.json` — ordered active and near-term work only.
- `risks.json` — current material risks and responses.
- `active_iteration.json` — the single current or most recently closed increment.
- `enterprise_experience.json` — a small set of approved reusable lessons.

Completed history is summarized by release under `../summaries/`. Detailed old
iteration and runtime records remain available in Git history, not in current
HEAD. These management records are support artifacts and cannot authorize
formal evidence, packaging, or delivery.
