# Codex Conversation / Dynamic Planning Contract

The Codex conversation is the only user-facing intake and result surface.
Dynamic planning is a support lane and cannot silently become the production
generator or delivery authority.

```text
Codex conversation -> whiteboard + agent_session -> reviewed Provider route
dynamic planning   -> bounded upstream planning evidence only
```

The conversation path must pass Provider validation, post-build finalization,
canonical evidence, required review, `local_packager`, and the public delivery
gate. It must not expose internal JSON, manifests, logs, or unapproved local
paths as a final result. Dynamic planning must not depend on a UI transport or
conversation credential.
