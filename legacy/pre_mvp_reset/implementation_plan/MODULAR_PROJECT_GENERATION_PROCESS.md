# Modular Project Generation Process

This process defines a CGNK-native project-generation module graph. The goal is module placement and contract separation; execution orchestration can be added later.

## Module Lines

1. `module.customer.service@1` normalizes the user goal into `artifact.customer_request@1`.
2. `module.local.librarian@1` indexes local libraries and CGNK module contracts into `artifact.local_library_index@1`.
3. `module.online.library_sources@1` finds online library sources into `artifact.online_library_sources@1`.
4. `module.feature.library_search@1` ranks local and online capability options into `artifact.feature_library_candidates@1`.
5. `module.local_agent.plan@1` prepares a local agent plan as `artifact.local_agent_plan@1`.
6. `module.adversarial_generation@1` reviews the request, candidates, and plan as `artifact.adversarial_review@1`.
7. `module.project.generator@1` emits `artifact.project_blueprint@1` and `artifact.generation_trace@1`.
8. `module.test_graph.emit@1` emits `artifact.test_graph@1`.
9. `module.effect_report.emit@1` emits `artifact.effect_report@1`.
10. `module.unified_control@1` is the only convergence point for final routing.

## Contract Rule

Every line exchanges typed artifacts through `flow.modular_project_generation@1`. No module directly owns another module's internal state, and no module line is merged into another line.

## Validation

Run:

```bash
python scripts/validate_bundle.py --flow flow.modular_project_generation@1 --schema
```

Expected result:

```text
REFS: OK errors=0
flow.modular_project_generation@1: OK errors=0
```
