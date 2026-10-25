# CGKN Community Operator

Community Operator answers a narrow question: where can the CGKN project team
contribute useful technical context without becoming a promotion bot?

## Authority and flow

The application reuses the existing `CapabilityRegistry`, `ComponentSpec`,
runtime, Project Knowledge, Promotion claim ledger, approval patterns, and
transport abstractions. It creates no second planner, DAG, scheduler, Knowledge
store, or capability authority.

```text
bounded public scan
  -> normalized untrusted thread
  -> ability-to-help and policy-first ranking
  -> engage decision
  -> independent project-mention/link decision
  -> bounded context and approved claims
  -> reply draft
  -> value, claim, disclosure, policy, and spam validation
  -> exact APPROVED_TO_REPLY binding
  -> qualified official reply adapter
  -> receipt, follow-up, moderation, and experience state
```

Discovery, ranking, drafting, and tracking may be automated. External reply,
edit, or deletion is a separate `EXTERNAL_WRITE` action. It requires a human
approval bound to the exact platform, thread, target post, reply hash, mention
flag, links, persona, and revision. Any change invalidates approval.

## Fail-closed behavior

- Unknown community rules become `HUMAN_REVIEW`.
- Insufficient project knowledge becomes `IGNORE` or `DRAFT_ONLY`.
- Engaging does not imply mentioning CGKN; mentioning does not imply linking.
- A reply with no value after removing project promotion is rejected.
- Project facts require an approved Promotion claim; general technical
  reasoning remains separately labeled.
- High spam risk, hidden affiliation, private data, secrets, unsupported
  claims, and promotional calls to action block publication.
- A moderator warning activates community suppression until human review.
- Restarting with the same thread, target, revision, and reply hash returns
  `ALREADY_REPLIED` rather than creating another comment.

The first release does not automate private messages, votes, likes, account
creation, browser-cookie posting, or replies to unknown public targets.

## Evaluation

```powershell
python scripts/run_community_operator.py --profile evaluate --json
python scripts/run_community_operator.py --profile real-read --json
```

The offline profile runs 60 opportunity cases, 30 reply cases, 20 policy cases,
10 follow-up cases, a 12-case fake adapter matrix, and four injected official
HTTP adapter contracts. The real-read profile additionally scans 10–30 public
GitHub issues through the official API, records Top20 opportunities and Top10
drafts, and performs zero external writes.

