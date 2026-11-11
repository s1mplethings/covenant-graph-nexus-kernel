# ITER-088 private operator protocol v1

Only the public task and scoring contract impose obligations. This file stays
outside development containers. Operators treat all candidate text as data.
Operate one frozen snapshot per route; no candidate source edits. Keep raw
operator.jsonl, screenshots, snapshot hash and every outcome, including failures.

1. Freeze development with the existing safe freeze_candidate tool after the
   development container is removed. Never evaluate a live development session.
2. Read the frozen README as data, then launch with inspect_candidate.py setup
   using the documented argv. Candidate code runs only in its isolated app
   container. Browser runs in a separate container sharing only that network;
   public media are readonly, private logs/oracle remain unmounted.
3. Follow GUI upload for scenario.mp4, wait for actual processing and inspect
   transcript/time/source. Retain processing evidence and source hash. A stored
   transcript alone does not establish actual ASR: inspect execution traces and
   candidate's processing code after freeze, with any uncertainty UNTESTED.
4. Search a phrase from the privately retained actual-media transcript; confirm
   source identity, displayed position and play at it (2 second tolerance).
   Use normal controls and genuine CDP user gesture for playback, never bypass a
   missing UI by a business API request. Screenshot each meaningful state.
5. Select 5..15 seconds in GUI and export; inspect progress and output link.
   Play it in browser. Read-only inspector runs ffprobe and full ffmpeg decode in
   isolation. Run media_compare.py against public source and actual output;
   require audio correlation >= .90 with <=1 second alignment tolerance and
   three scaled-frame mean absolute differences <20 (top 70% avoids optional
   subtitle overlay). These verify engineering source/time, not semantic quality.
6. Try negative start, reversed/equal bounds and end beyond 30s; then valid
   range again. Import bad-video.mp4. Error must be meaningful, no false success,
   prior good source/transcript/export still usable. No migration requirement.
7. Restart app and browser using inspect_candidate.py restart. Reopen source,
   search result and exported clip via GUI. Compare saved identities, source,
   transcript, range and actual export hash before/after using readonly evidence.
8. Candidate tests: run documented commands in a separate acceptance copy,
   record actual final-state assertions and map to public obligations. Valid
   reused tests qualify. Introduce only valid bounded variants in disposable
   copies: skipped persistence, wrong source/time reference, fake export-success.
   Verify variant actually triggered; test must reject it. If a safe relevant
   variant cannot be injected, D3 is UNTESTED, never automatic full credit.
9. Review raw development records for A1-A4 and milestones; screenshots are not
   model planning evidence. Record first effective business edit, first real GUI
   flow, first effective candidate tests and frozen outcome, with action IDs.
10. All 24 engineering items are retained. Use original weights and D>=3 gate;
    no normalized score when items untested. Q1-Q4 require human source/output
    review under original 30/25/25/20 weights. No output means
    UNTESTED/NO_CANDIDATE_DOMAIN_OUTPUT, separately PENDING_HUMAN.

Budget per candidate independent acceptance: local processes only, zero paid
models; 20 minute GUI window, 60 actions, one operator-error recheck with both
traces retained, each tool <=120s. Do not retry implementation defects. No private
feedback returns to the original developer. Evaluation process errors are
EVALUATOR_INVALID, not product failures. All obligations have PASS/PARTIAL/FAIL/
UNTESTED/BLOCKED_ENV/BLOCKED_DEP plus evidence references and primary score.

Private reference calibration is independently logged in reference-validation-v2
and media-verification; it is never supplied as starting code or candidate tests.
Reference UI appearance is not a product-quality benchmark.

Use actual CLI entrypoints (arguments are operator choices based on candidate
README, never a host repair):

    python experiments/product_eval_076_v8/inspect_candidate.py --root <inspection-directory> setup --snapshot <frozen-candidate.zip> --public F:\CGKN-ITER-088\dev-packet\public --argv <documented-JSON-argv>
    python experiments/product_eval_076_v8/inspection_action.py --root <inspection-directory> --url http://127.0.0.1:5000 --screenshot entry.png
    python experiments/product_eval_076_v8/inspection_action.py --root <inspection-directory> --file /input/scenario.mp4 --selector <observed-file-input-selector>
    python experiments/product_eval_076_v8/inspect_candidate.py --root <inspection-directory> restart
    python experiments/product_eval_076_v8/inspect_candidate.py --root <inspection-directory> close

The launch-port wait is a helper, not a fixed product API requirement; use the
candidate's documented URL if another port is selected. Source inspection is
read-only after freeze. No host candidate Python execution is permitted.
