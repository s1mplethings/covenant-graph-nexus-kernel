# ITER-018 Self-Grown Real Capabilities

## 1. Git Identity

- Branch: `codex/self-grown-real-capabilities-20261018`
- Base: `cd4e088b216d4f43ac3e6dc88e93781ebce91be3`
- Source closure: `168f308f0e80aca9283af29cd6c7c0cfdc834ffe`
- Source tree: `b0b86f25f35c314e1ad630ff496cdeb05df287cf`
- Evidence closure: pending canonical evidence commit

## 2. Protected Baseline

Parent remains `BASELINE-SELF-GROWTH-SINGLE-PROVIDER-001`. MVP, Repository Codegen, Capability Builder, Self-Growth V1, fallback-deny, frozen routing, zero manual candidate edits, and zero unsafe admissions remain protected. No replacement baseline was created because the ideal three-leaf success condition was not met.

## 3. Test Policy

Only MICRO and SMALL_REGRESSION were run. Full Kernel and active-repository regressions were `NOT_RUN_BY_POLICY`; the accepted Kernel receipt was not re-signed because no L0–L5 source changed.

The application-wide receipt is stale by boundary hash after these scoped application changes. It was intentionally not re-signed because doing so would require claiming or running the forbidden full application validation; the 36-test scoped receipt is reported separately and is not presented as full closure.

## 4. Existing Growth Health

The accepted `text.slugify@1` and `markdown.links.extract@1` store was reused directly. Both returned PASS with zero Provider, Growth, Builder, and Admission calls.

## 5. Public Network Boundary

The new application-layer authority permits credential-free HTTPS GET/HEAD only. It validates every resolved address, revalidates every redirect, rejects localhost/private/link-local/multicast/metadata destinations, rejects custom or credential headers and non-443 endpoints, limits redirects to three, timeout to ten seconds, and response bodies to 1 MiB. Generated code cannot import direct network, filesystem, process, or shell APIs.

## 6. web.fetch.public

Grok generated the executor in one call. Candidate tests, runtime-source checks, sandbox, admission, and Registry storage passed with zero manual edits. Real execution did not pass because this host resolved `example.com` to reserved address `198.18.1.22`; the SSRF boundary correctly blocked before transport. A repeated call reused the Registry with zero Growth/Builder calls and remained environment-blocked.

## 7. github.repo.inspect.public

The required dependency was `web.fetch.public@1`. Because that dependency could not complete its real smoke, this branch stopped before Provider invocation. No GitHub token was read, no candidate was created, and Provider calls were zero.

## 8. release.notes.from_diff

Grok generated the PURE local executor. A framework JSON materialization defect was found and repaired without editing either generated candidate. The final candidate passed four deterministic cases (added, modified, deleted, empty), runtime oracle, admission, first execution, Registry storage, and second-run zero-growth reuse.

## 9. Capability Composition

Composition was `BLOCKED_DEPENDENCY`. It was not valid to claim a composed Research/Release DAG while the GitHub leaf was absent. Growth and Builder calls for composition were zero.

## 10. Security

Targeted coverage passed for loopback, RFC1918, link-local metadata, IPv6 local ranges, `.local`, public-to-private redirect, Authorization/Cookie/API-key headers, POST, custom headers, response bounds, filesystem/process imports, and undeclared dependency access. Unsafe admissions: zero.

## 11. Provider

- Grok: READY; used in `SINGLE_PROVIDER_MODE`
- Qwen: BLOCKED_ENVIRONMENT
- DeepSeek: BLOCKED_CREDENTIAL
- Adaptive Provider Selection: BLOCKED_ENVIRONMENT

## 12. Testing

- MICRO: 35 passed
- SMALL_REGRESSION: 36 passed, including the Grok Responses structured-output path
- Real Provider calls: 3 of 8 maximum
- Actual tokens: 6,087 input and 13,766 output
- Estimated cost: USD 0.09477 under the ledger's recorded rates
- Full: `NOT_RUN_BY_POLICY`

## 13. Baseline

Overall result is `PARTIAL` / `PASS_WITH_LIMITS`. `BASELINE-SELF-GROWN-LEAVES-001` was not created. The parent baseline remains current and no guarantees were removed.

## 14. Readiness

- mvp_readiness: READY
- repository_codegen: COMPLETE
- capability_builder: COMPLETE
- self_growth_v1: COMPLETE
- research_foundation: NOT_AVAILABLE
- release_foundation: AVAILABLE
- provider_selection: BLOCKED_ENVIRONMENT

## 15. Remaining Next Steps

Run the existing admitted web leaf in an environment whose public DNS resolves to globally routable addresses, then build the dependent GitHub inspector and execute the small composition smoke. Later work may add Research composition, external acquisition, approval-bound write capabilities, and the project coordinator; none were started in this iteration.
