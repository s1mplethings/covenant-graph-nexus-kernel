# ITER-058 — CGNK Necessity Boundary

Status: **PASS_WITH_LIMITS**.

The frozen formal holdout used Source Closure
`a2c7720fb176ba8aa913016dd166e98221282afd`, API Lab
`7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`, one DeepSeek cheap route, and 18
five-episode chains per baseline. Results were B0 Direct Cheap 18/18, B1 Direct
with Flat State 17/18, and B2 CGNK 18/18. B0 versus B2 had no discordant chain;
full CGNK architecture benefit is therefore not proven. B2 reduced measured
rework by 18.5%, concentrated in supersession and mixed long-horizon work, but
used 7.2% more context and 0.9% more estimated Provider cost than B0.

The Knowledge store/persistence/internalization cyclic SCC was reduced from one
to zero by extracting a pure projection boundary. Public symbols, schemas,
ProjectKnowledgePack authority, segmented-v2 persistence, v1 migration,
checkpoint/replay/fallback, and Conversation behavior remain compatible.

All eight Kernel profiles passed; active repository finished with 3,022 passed,
363 skipped, zero failed, and zero errors. Router was not reopened. Multi-Agent
Runtime remains not recommended. See
`research/release-058/technical_report.md` for the complete 54-section report.
