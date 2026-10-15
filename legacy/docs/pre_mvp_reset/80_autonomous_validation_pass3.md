# Autonomous Validation Pass 3

Pass 3 is a support-only research lane for testing whether a real language
model can design and revise project acceptance operations from public goals and
actual execution feedback. It reuses Pass 1/2 isolation, adapters, independent
oracles, evidence logs, and fresh-workspace reproduction. It does not alter the
CGKN generation mainline, formal evidence, packaging, or delivery.

## A/C/D design

- A uses one real-model call per project to propose an ordinary coding-agent
  test plan. It receives no execution feedback.
- C uses reviewed deterministic business boundaries and makes no model call.
- D uses three rounds per project. Each round proposes at most two operations,
  executes them against the same isolated project state, and passes bounded
  observations into the next round.

Every arm has the same six-operation maximum per project, public materials,
source version, adapter permissions, and deterministic oracles. Invalid model
operations are rejected rather than translated into arbitrary shell commands.
Only executed operations count. Model plans cannot read project tests, prior
validation reports, known-defect lists, or oracle definitions.

The reference study uses two different real projects:

- the CGKN-generated Local AI Knowledge Studio snapshot, with document import,
  search, task state, report generation, and a packaged final artifact;
- ORBIT-360, with a file-backed dependency graph, execution, resume, status,
  and repair workflow.

No defects are injected. The generated project is copied into separate arm
workspaces, while ORBIT-360 uses detached Git worktrees. Original project data
and running services are not modified.

## Model-neutral operation contract

`scripts/autonomous_validation_pass3.py` uses a small `ModelClient` boundary
over the repository's OpenAI-compatible transport. Model name, endpoint, token
prices, and timeout are arguments or configured environment values. The model
returns JSON hypotheses and operations; project-specific adapters execute only
allowlisted public CLI/API operations. This keeps the explorer compatible with
another hosted or local OpenAI-compatible model without making the model an
acceptance authority.

Run a bounded experiment:

```powershell
python scripts/autonomous_validation_pass3.py `
  --repo . `
  --out runs/autonomous-validation/pass3-real-projects `
  --model qwen3.5-flash `
  --input-price-per-million 0.029 `
  --output-price-per-million 0.287 `
  --pricing-source https://www.alibabacloud.com/help/en/model-studio/model-pricing
```

Token usage comes from Provider responses. Cost is an estimate from the
explicit rates and is never represented as an invoice. If rates are omitted,
the report records token counts and leaves cost unavailable.

## Independent acceptance and traces

The model never declares a counted defect. Adapters capture operation inputs,
results, process status, state before/after, and produced files. Independent
deterministic oracles create candidate findings. Every candidate is replayed
from the same source identity in a fresh workspace before it counts.

Outputs include:

- `scenario_plan.json`: public evidence hashes and experimental controls;
- `A|C|D/<project>/discovery/execution.json`: complete plan and execution
  trace;
- `D/<project>/discovery/round-N/trace.json`: feedback-loop evidence;
- per-finding `reproduction/.../execution.json`: independent replay;
- `validation_report.json` and `.md`: comparison, model receipts, costs,
  conclusions, and limits.

Subjective model concerns stay in the plan trace and are not counted as
defects. All Pass 3 reports remain `NOT_EVALUATED` with
`release_authority=false`.
