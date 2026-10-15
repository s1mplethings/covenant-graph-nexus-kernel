# Virtual Team Contract

## 0. Purpose

CGNK MUST create a project-specific virtual team before implementation begins.

The virtual team is a production mechanism, not a narrative decoration. Each role MUST own artifacts, decisions, risks, and pass gates.

## 1. Team formation rule

A Product Studio run MUST create `virtual_team_roster` after `output_contract` and before `product_story`.

The roster MUST explain:

```text
why each role exists
which artifacts the role owns
which decisions the role can make
which pass gates the role must satisfy
```

## 2. Default roles

CGNK SHOULD start with these default roles:

| Role | Required ownership |
| --- | --- |
| Product Lead | `product_story`, `mvp_scope`, user value, non-goals, default assumptions. |
| Solution Architect | `technical_plan`, architecture boundaries, runtime target, dependency plan. |
| UX Designer | `page_flow`, `interaction_model`, first-run experience, GUI evidence expectations. |
| Implementation Engineer | `build_plan`, generated files, runtime fixes, implementation trace. |
| QA Engineer | `test_plan`, `test_data`, `test_report`, regression checks. |
| Delivery Manager | `delivery_bundle`, README, visual evidence, user summary, revision entry. |

## 3. Dynamic roles

CGNK MAY add roles based on the project type.

Examples:

| Trigger | Additional role |
| --- | --- |
| Data import/export, CSV, Excel, reports | Data Engineer |
| AI model, embeddings, LLM, image generation | AI Engineer |
| Image/video/audio processing | Media Pipeline Engineer |
| Game tools, creative tools | Game Tools Designer |
| Security, local secrets, permissions | Security Reviewer |
| Complex docs or tutorials | Documentation Lead |

A dynamic role MUST have concrete artifact ownership. A role without artifact ownership MUST NOT be added.

## 4. Role output contract

Each role output MUST be machine-checkable or traceable to a required artifact.

Example mapping:

```text
Product Lead -> product_story.json, mvp_scope.json
Solution Architect -> technical_plan.json
UX Designer -> page_flow.json, interaction_model.json
Implementation Engineer -> build_plan.json, generated_project manifest
QA Engineer -> test_plan.json, test_data, test_report.json
Delivery Manager -> delivery_bundle.json, user_summary.md
```

## 5. Team discussion rule

The virtual team SHOULD resolve design and implementation choices before code generation.

For each major decision, CGNK SHOULD record:

```text
decision
owner role
reason
accepted alternative
rejected alternatives
risk
acceptance implication
```

## 6. Forbidden behavior

The following are FORBIDDEN for a PASS run:

```text
creating a role that owns no artifact
implementing before virtual_team_roster exists
claiming virtual team review without role outputs
using generic role names without responsibilities
letting Implementation Engineer override output_contract without Product Lead and Delivery Manager review
letting Delivery Manager mark PASS without QA evidence
```

## 7. Pass gate

`virtual_team_roster` passes only when:

```text
at least Product Lead, Solution Architect, Implementation Engineer, QA Engineer, and Delivery Manager exist
all roles have artifact ownership
all required downstream artifacts have at least one owner
role responsibilities match the project type
```

GUI projects SHOULD include UX Designer.

A project that requires visual output SHOULD include either UX Designer, Media Pipeline Engineer, or Delivery Manager evidence ownership.
