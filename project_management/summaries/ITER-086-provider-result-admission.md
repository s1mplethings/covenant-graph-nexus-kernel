# ITER-086 Provider result admission

ITER-086 separated Provider transport success from formal requirements-planning
admission. Inspection of production run
`production-8ffc7f0800e34269a94c3c2589f654d4` showed the actual attempt order was two
timeouts, one HTTP 200, a schema-repair timeout, and two further outer retries.
The HTTP 200 was recorded at the transport boundary but did not produce a
validated planning artifact; its body was not durably retained, so semantic
validity could not be reconstructed from the persisted hash.

The repair routes planning text through the existing single-object JSON
extractor before applying the unchanged strict planning proposal validator.
Fenced or commentary-wrapped single objects can therefore be admitted without
a second live envelope-repair request, while invalid JSON or schema remains
fail-closed. Safe validation-failure and response-to-artifact admission events
make the handoff explicit without treating HTTP status as formal authority.

The canonical scoped receipt covered 222 zero-API admission, requirements,
surrogate, provenance, formal-chain, kernel, publish, management, and resume
tests. Repair commit `4832a0f1f2b52e9118732c43ca6fa359f2ade6f9` was normally pushed and remote
verified.

Live revalidation created
`production-7ba6c807edeb49689520b8ba771db94f`, bound to the repair commit and the
original sealed brief. Canonical metrics recorded two primary generation calls:
the first completed as a 60-second transport timeout and the second began, but
the MCP command's 120-second process boundary terminated the run before the
second response or the canonical retry policy completed. No successful Provider
result, planning artifact, candidate, provenance, formal evidence, or safe
resume state was produced. This is retained as a Provider/command-lifetime
blocker rather than another admission defect; no further Provider call was made.
