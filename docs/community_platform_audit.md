# Community platform audit

Captured: 2026-10-25. This is a conservative capability audit, not legal advice
and not permission to post. Community-specific rules still govern every target.

The implementation uses only documented APIs for production adapters. It does
not use browser cookies, anti-bot bypasses, private messages, votes, likes, or
undisclosed identities. Unknown rules always require human review; unsupported
write paths are `DRAFT_ONLY` or `MANUAL_ONLY`.

## Qualified architecture targets

- GitHub exposes official issue-comment REST endpoints and Discussion GraphQL
  mutations. Reads can use official search and thread APIs; writes require the
  appropriate repository permission and exact human approval.
- Mastodon exposes search, status context, and reply creation using
  `in_reply_to_id`. Search coverage varies by instance and authenticated scope;
  instance rules remain authoritative.
- Bluesky exposes public AppView search/thread reads and authenticated AT
  Protocol record creation with explicit root/parent reply references.
- Discourse documents search, topic/post reads, and post creation. Site and
  category rules remain authoritative.

## Read/draft-only defaults

- Reddit has official comment APIs, but developer access, Reddit terms, and
  subreddit rules all apply. No CGNK account or approval is qualified, so v1 is
  `DRAFT_ONLY`.
- Hacker News has an official Firebase read API but no official write API;
  therefore replies remain manual.
- V2EX API 2.0 Beta documents topic and reply reads but no qualified reply-write
  route for this project.
- Zhihu's data platform offers metered products including search and own-content
  comment data, but no general community reply contract was verified.
- Lobsters, Juejin, and general Bilibili comments have no documented official
  write path qualified for this use. They remain manual or unimplemented.

The machine-readable details and evidence URLs are in
`benchmarks/community_v1/fixtures/community_connectivity_matrix.json`.

