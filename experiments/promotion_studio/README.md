# Promotion Studio v1 experiment

This is a local-first, source-bound evaluation harness for Promotion Studio. It
uses deterministic signal, copy, validation, image, and video routes. Native
publisher qualification injects a recording transport and does not contact
public accounts. The sole fake publication is exact-hash approved and writes a
restart-safe local receipt.

Formal evaluation must run from a clean, frozen source commit. A real public
post is optional and remains blocked unless local test-account credentials and
explicit publish approval are both present.
