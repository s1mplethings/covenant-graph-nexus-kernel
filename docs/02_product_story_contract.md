# Product Story Contract

## 0. Purpose

The product story layer turns a raw user request into a product that can be designed, built, tested, and delivered.

The story is not marketing copy. It is a required source artifact for scope, UX, tests, and delivery evidence.

## 1. Required position

`product_story` MUST be created after `virtual_team_roster` and before `technical_plan` and `build_plan`.

Implementation MUST NOT begin before `product_story` and `mvp_scope` exist.

## 2. Required fields

A valid `product_story` MUST include:

```text
product_name
one_sentence_pitch
target_user
main_problem
current_pain
desired_outcome
first_run_experience
core_user_journey
mvp_boundary
non_goals
default_assumptions
acceptance_implications
```

## 3. Story-to-acceptance rule

Every important story claim MUST map to an acceptance implication.

Example:

```text
Story claim:
User can import a folder of images and preview renamed results before exporting.

Acceptance implication:
The generated project MUST include folder input, preview list, rename action, export result, test images, and screenshot evidence of the preview screen.
```

A story that does not influence scope, UX, tests, or delivery SHOULD be removed.

## 4. MVP boundary rule

`mvp_boundary` MUST define the first usable version.

It MUST include:

```text
must_have
should_have
could_have
non_goals
blocked_or_deferred
```

The first version SHOULD be small enough to run locally and produce visible evidence.

If the user asks for "anything" or a broad project category, CGNK MUST choose a bounded MVP and write the decision into `default_assumptions`.

## 5. GUI and visual behavior

If the requested project includes GUI, visual output, media output, or user-facing screens, the product story MUST define:

```text
first screen
main action
result screen
empty state
error state
visual evidence requirement
```

A GUI project MUST NOT pass without visual evidence unless the run is explicitly marked PARTIAL or BLOCKED.

## 6. Input-output priority

The product story MUST preserve the user's input and output requirement.

If the user defines only input and output, CGNK MUST infer a reasonable product path and record assumptions.

If the inferred path conflicts with the output contract, the output contract wins.

## 7. Forbidden behavior

The following are FORBIDDEN for a PASS run:

```text
implementing code before product_story exists
using product_story as decorative prose only
omitting target_user
omitting first_run_experience for GUI projects
omitting mvp_boundary
omitting non_goals
omitting acceptance_implications
marking a project complete when the delivered UI contradicts the story
```

## 8. Pass gate

`product_story` passes only when:

```text
it names the target user
it states the main problem
it states the desired outcome
it defines the first-run experience
it defines the core journey
it defines MVP scope and non-goals
it maps story claims to acceptance implications
it is consistent with output_contract
```

## 9. Revision rule

When the user requests a change, CGNK SHOULD update the product story or mark the change as a direct implementation revision.

If the user's feedback changes the product purpose, user journey, or output contract, the story MUST be updated before rebuilding.
