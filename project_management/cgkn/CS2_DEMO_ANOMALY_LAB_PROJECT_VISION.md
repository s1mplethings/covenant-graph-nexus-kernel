# CS2 Demo Anomaly Lab — Project Vision

## Vision

Build a defensive, explainable CS2 Demo analysis tool that helps a qualified
human reviewer find unusual aiming and information-timing windows in authorized
match recordings. The product turns a verifiably acquired Demo into traceable
telemetry, signal coverage, player-level evidence windows, and a local report.
It must make uncertainty visible and must never turn an unlabeled match into an
automatic cheating verdict.

## Intended users and outcome

- Reviewers investigating matches they are authorized to process.
- Researchers evaluating transparent behavioral signals and data coverage.
- Operators who need reproducible source, parser, and report evidence.

The useful outcome is a small set of inspectable time windows with provenance,
signal values, coverage, limitations, and human-review guidance—not a ban list.

## Required product capabilities

1. Discover candidates only from a bounded reviewed public catalog or accept an
   explicitly authorized local `.dem` file.
2. Bind online inputs to immutable repository and object identity, license
   metadata, byte count, and SHA-256 before use.
3. Enforce HTTPS host, request-count, elapsed-time, compressed-size,
   expanded-size, archive-member, traversal, drive-path, redirect, and symlink
   safety limits.
4. Parse genuine CS2 Demo telemetry with `demoparser2` and prove non-zero ticks,
   players, positions, and view angles before calling the input real.
5. Join weapon-fire, death, and round events only where attribution is supported;
   anonymous events remain unassigned.
6. Analyze recorded yaw/pitch deltas as a `view_angle_proxy`, spatial angular
   error, target alignment, snap-before-shot, tracking, switching, reaction, and
   information-timing only when the required source telemetry exists.
7. Preserve missing visibility, hearing, occlusion, teammate-information, and
   target-relation telemetry as `unknown`; do not infer hidden-information use.
8. Produce JSON and local HTML reports with source provenance, parser proof,
   coverage, evidence windows, confidence, limitations, and reviewer guidance.
9. Support bounded candidate failover without weakening security or silently
   falling back to synthetic evidence in the genuine-real-Demo acceptance run.

## Non-goals and safety boundaries

- Do not create, improve, conceal, or operate game cheats.
- Do not read raw mouse counts unless a future authorized source explicitly
  provides them; view-angle deltas are not raw device input.
- Do not bypass authentication, anti-cheat systems, platform controls, or site
  access restrictions.
- Do not claim cheating, accuracy, precision, recall, or false-positive rate
  from an unlabeled public regression corpus.
- Do not authorize automatic bans. Every material conclusion requires qualified
  human review and supporting evidence.
- Do not package or deliver outside CGKN's `local_packager` and public delivery
  gate.

## Frozen acceptance criteria

1. The reviewed Provider route generates a fresh project from this vision; old
   generated source is not reused.
2. Dependency, unit, security, parser, analysis, reporting, and CLI tests pass
   in an isolated declared environment.
3. A genuine authorized CS2 Demo completes parse-to-report with synthetic
   fallback disabled and produces non-zero tick/player rows, unique ticks,
   players, positions, yaw/pitch, and event coverage where present.
4. Independent assertions bind source hash, Demo hash, generated source hash,
   parser counts, report counts, and runtime command.
5. Missing information telemetry stays unknown; unsupported wall-information or
   prefire-before-information conclusions are absent.
6. Every player result exposes evidence coverage and cannot become a definitive
   cheating verdict from the unlabeled acceptance sample.
7. `accuracy_claim` remains `NOT_EVALUATED`, `automatic_ban_allowed` is false,
   and `human_review_required` is true unless a future separately governed,
   labeled evaluation changes those facts.
8. Only after generated tests and the real runtime acceptance pass may
   post-build finalization proceed to `local_packager` and the public delivery
   gate. Missing evidence remains explicit non-PASS.

## Quality measures

- Input truth: immutable provenance, verified size/hash, safe extraction.
- Parser truth: non-zero real ticks and players plus required spatial/view fields.
- Analysis truth: each signal declares required inputs and evaluated coverage.
- Conclusion truth: uncertainty and unsupported signals cannot increase risk.
- Reproducibility: source, input, environment, command, and output hashes bind.
- Delivery truth: generated-project fitness and formal delivery authorization
  are evaluated separately.

## Preserved evidence used to define the vision

- Retired working-project README SHA-256:
  `f1fb8869df31aafbdf20c38e8396f61d0559221d11d8638d73fb32194eb60a67`.
- Retired working-project test report SHA-256:
  `8c9f4a0f3e8058d16a53e32f8e592e81af2fa430e358450dd24bfc61ed552805`.
- ITER-019 runtime evidence SHA-256:
  `6c0589254a4d69100332a231fe95bb59eea2164d18cd31d941873adde8165c8a`.
- Preserved real report SHA-256:
  `dca6e5cd01c9cd418ff40fe31de0a72d85de477133c8de1f9a1166ebe31ded96`.

The old working source is intentionally disposable. The vision, safety
boundaries, and independently retained evidence are the durable product memory.
