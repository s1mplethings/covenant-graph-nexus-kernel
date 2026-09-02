# ITER-035 runtime evidence

Status: completed.

## Root cause

The plugin generation preflight inspected inherited process variables directly, while the kernel contract and Provider runtime resolve the canonical Windows User-level `CGKN_OPENAI_API_KEY`. That contract drift caused a false missing-key report even though the configured API credential was usable.

## Implemented increment

- Added typed `cgkn_probe_provider` with explicit `RUN_PROVIDER_PROBE` confirmation.
- The probe uses the canonical credential resolver, issues only a minimal live request, returns bounded public diagnostic categories, and writes no candidate or delivery artifact.
- Updated `cgkn_generate` to use the same canonical resolver before delegating to the unchanged reviewed Provider mainline.
- Applied PB-025 and `EXP-CGKN-BOOTSTRAP-001`: the capability remains inside the existing MCP plugin and does not create a second generation or delivery route.

## Verification

- Targeted plugin, skill, credential, transport, and kernel contract suite: `62 passed`.
- Plugin skill validation: passed.
- Plugin manifest validation: passed.
- Live Provider probe: `connected`; source scope `canonical_user`; base URL `https://api.gptsapi.net/v1`; endpoint mode `chat`; model `gpt-4.1-mini`; TLS verification enabled; one attempt.
- Plugin cachebuster: `0.1.0+codex.20260824155310`.
- Automatic `codex plugin add cgkn@personal` could not start because the packaged desktop CLI executable returned Windows access denied. The source and local MCP verification are complete; plugin pickup requires the same command from a normal user terminal followed by a fresh Codex task.

Formal evidence status remains `NOT_EVALUATED`. The probe is operational support evidence only and cannot authorize Provider generation, packaging, or delivery.
