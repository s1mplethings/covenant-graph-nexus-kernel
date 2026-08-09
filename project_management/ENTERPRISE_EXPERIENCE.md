# Enterprise Experience

Organization: CGKN

## EXP-CGKN-BOOTSTRAP-001: Self-host the management method before provider integration

- State: `approved`
- Situation: CGKN is adding a new project-management capability that must govern both its own work and generated projects.
- Action: First stabilize schemas, deterministic validation, repository instructions, a project-local skill, and a real CGKN iteration; integrate provider planning context in a later bounded increment.
- Outcome: The bootstrap and provider-integration increments passed schema, semantic, CLI lifecycle, skill, knowledge, kernel, provider, and execution-route checks without creating another generation or delivery route.
- Tags: cgkn, continuous-improvement, hybrid, self-hosting
- Evidence: project_management/cgkn/iterations/ITER-001.json, project_management/cgkn/iterations/ITER-002.json, tests/test_adaptive_project_management_context.py, tests/test_pmp_agile_quality_manager.py, tests/test_pmp_agile_quality_schemas.py

## EXP-CGKN-LIBRARIAN-001: Use bounded librarian projections for large component and leaf generation

- State: `approved`
- Situation: A generated project has enough files, interfaces, or upstream evidence that copying the entire context into every provider request would be noisy or oversized.
- Action: Keep the complete feedforward snapshot and source catalog local, then retrieve only the current contract, direct dependency interfaces, and a bounded set of relevant source excerpts.
- Outcome: Provider leaves receive traceable relevant context while prompt size remains bounded and unrelated passed checkpoints remain reusable.
- Tags: cgkn, context, large-project, librarian, project-generation
- Evidence: docs/00_kernel_contract.md, tests/test_complexity_formal_mainline_contract.py, tests/test_generation_scale_ladder.py

## EXP-CGKN-QUALITY-001: Separate planning, implementation, and delivery truth

- State: `approved`
- Situation: Planning artifacts or generated files exist, but runtime, visual, test, review, or package evidence may still be incomplete.
- Action: Evaluate each evidence layer independently and allow only canonical producers and inspectors to authorize formal gates.
- Outcome: Planning progress and partial implementation remain visible without being promoted into a false public delivery PASS.
- Tags: cgkn, delivery, evidence, governance, quality
- Evidence: docs/01_contract_registry.md, tests/test_kernel_contract.py
