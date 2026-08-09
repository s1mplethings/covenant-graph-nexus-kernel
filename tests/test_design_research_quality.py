from __future__ import annotations

import pathlib

from scripts import design_research_agent
from scripts import run_local_pipeline_impl


GOAL = "构建一个有设计感的本地 CS2 证据分析工作台，包含关系图、时间线和人工复核报告界面"


def fake_searcher(source: str, index: int):
    def search(query: str):
        return [
            {
                "source": source,
                "source_kind": "test_reference",
                "name": f"Reference {index}",
                "url": f"https://example.com/design/{index}",
                "license": "reference-only",
                "use_boundary": "Analyze principles only; do not copy assets or exact layout.",
                "query": query,
            }
        ]

    return search


def researched_design(tmp_path: pathlib.Path) -> dict:
    return design_research_agent.run_design_research(
        GOAL,
        {},
        {"kind": "MarketResearchManifest"},
        tmp_path / "design",
        searchers=[
            ("SearchA", fake_searcher("SearchA", 1)),
            ("SearchB", fake_searcher("SearchB", 2)),
            ("SearchC", fake_searcher("SearchC", 3)),
        ],
    )


def valid_visual_files(design: dict) -> list[dict[str, str]]:
    contract = design_research_agent.bounded_design_context(design)["design_contract"]
    colors = contract["design_tokens"]["color"]
    selected = contract["selected_direction_name"]
    css = f"""
:root {{
  --canvas: {colors['canvas']}; --surface: {colors['surface']}; --ink: {colors['ink']};
  --muted: {colors['muted']}; --accent: {colors['accent']}; --accent-alt: {colors['accent_alt']};
  --signal: {colors['signal']}; --space-1: .5rem; --space-2: 1rem; --space-3: 2rem;
  --radius: .8rem; --motion: 220ms; --display: Georgia, serif; --body: system-ui, sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: var(--ink); background: var(--canvas); font-family: var(--body); min-height: 100vh; }}
.shell {{ display: grid; grid-template-areas: 'hero detail' 'timeline detail'; grid-template-columns: minmax(0, 1.6fr) minmax(18rem, .8fr); gap: var(--space-3); padding: var(--space-3); }}
.hero {{ grid-area: hero; max-inline-size: 70rem; min-height: 15rem; background: var(--surface); border-radius: var(--radius); padding: var(--space-3); }}
.hero h1 {{ font: 700 clamp(2.4rem, 7vw, 5.8rem)/.92 var(--display); margin: 0; color: var(--ink); }}
.detail {{ grid-area: detail; position: sticky; top: var(--space-2); align-self: start; background: var(--surface); padding: var(--space-2); border: 1px solid var(--muted); }}
.timeline {{ grid-area: timeline; display: grid; gap: var(--space-1); color: var(--muted); }}
button {{ min-width: 44px; min-height: 44px; border: 0; border-radius: var(--radius); background: var(--accent); color: var(--surface); padding: var(--space-1) var(--space-2); transition: transform var(--motion), background var(--motion); }}
button:hover {{ transform: translateY(-2px); background: var(--accent-alt); }}
button:active {{ transform: translateY(0); }}
button:focus-visible {{ outline: 3px solid var(--signal); outline-offset: 3px; }}
.status {{ color: var(--accent-alt); padding: var(--space-1); }}
@media (max-width: 760px) {{ .shell {{ grid-template-areas: 'hero' 'timeline' 'detail'; grid-template-columns: 1fr; padding: var(--space-2); }} .detail {{ position: static; }} }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation-duration: .01ms !important; transition-duration: .01ms !important; }} }}
"""
    research_doc = "\n".join(
        [
            "# Design Research",
            selected,
            "We use the references for principles only; do not copy assets, brands, or exact layout.",
            "https://example.com/design/1",
            "https://example.com/design/2",
            "https://example.com/design/3",
        ]
    )
    system_doc = f"# Design System\n\n{selected}\n\nColor, typography, spacing, radius, motion, focus, responsive layout, and interaction states.\n"
    return [
        {"path": "index.html", "content": "<!doctype html><html><body><main class='shell'><section class='hero'><h1>Case review</h1><button>Review</button></section><aside class='detail'>Evidence</aside><section class='timeline'>Timeline</section></main></body></html>"},
        {"path": "src/styles.css", "content": css},
        {"path": "docs/design_research.md", "content": research_doc},
        {"path": "docs/design_system.md", "content": system_doc},
    ]


def test_design_research_searches_sources_and_selects_distinct_direction(tmp_path: pathlib.Path) -> None:
    result = researched_design(tmp_path)

    assert result["workflow_state"] == "completed"
    assert result["visual_surface_required"] is True
    assert len(result["search_attempts"]) == 3
    assert all(item["workflow_state"] == "completed" for item in result["search_attempts"])
    assert len(result["references"]) >= 3
    assert len(result["directions"]) == 3
    assert len({item["name"] for item in result["directions"]}) == 3
    assert (tmp_path / "design" / "design_research.json").exists()
    assert (tmp_path / "design" / "DESIGN_RESEARCH.md").exists()


def test_nonvisual_api_does_not_receive_aesthetic_frontend_gate(tmp_path: pathlib.Path) -> None:
    result = design_research_agent.run_design_research(
        "Build a JSON API only with no interface",
        {},
        {},
        tmp_path / "api-design",
        searchers=[("unused", lambda query: (_ for _ in ()).throw(AssertionError(query)))],
    )

    assert result["visual_surface_required"] is False
    assert result["search_attempts"] == []
    context = design_research_agent.bounded_design_context(result)
    receipt = run_local_pipeline_impl.validate_generated_design_quality(
        component_id="assembled_project",
        files=[{"path": "main.py", "content": "print('ok')\n"}],
        design_context=context,
        assembled=True,
    )
    assert receipt["status"] == "pass"
    assert receipt["applicability"] == "not_required"


def test_design_context_enters_only_relevant_librarian_queries(tmp_path: pathlib.Path) -> None:
    design = researched_design(tmp_path)
    pipeline = run_local_pipeline_impl.apply_design_context_to_component_pipeline(
        {
            "components": [
                {"id": "foundation", "required_paths": [], "acceptance": []},
                {"id": "frontend", "required_paths": ["index.html", "src/styles.css"], "acceptance": []},
                {"id": "docs", "required_paths": ["README.md"], "acceptance": []},
            ]
        },
        design,
    )
    docs = next(item for item in pipeline["components"] if item["id"] == "docs")
    assert "docs/design_research.md" in docs["required_paths"]
    assert "docs/design_system.md" in docs["required_paths"]

    frontend = next(item for item in pipeline["components"] if item["id"] == "frontend")
    index = run_local_pipeline_impl.build_generation_context_librarian_index(
        goal=GOAL,
        component=frontend,
        component_pipeline=pipeline,
        manifest=[{"path": "src/styles.css", "purpose": "styles", "dependencies": []}],
        completed_files=[],
        prior_files=[],
        integration_feedforward={},
    )
    context = run_local_pipeline_impl.query_generation_context_librarian(
        index,
        leaf={"path": "src/styles.css", "depends_on": []},
    )
    assert any(item["item_id"] == "contract:design_context" for item in context["selected_items"])


def test_design_quality_rejects_generic_industrial_shell(tmp_path: pathlib.Path) -> None:
    design = researched_design(tmp_path)
    context = design_research_agent.bounded_design_context(design)
    result = run_local_pipeline_impl.validate_generated_design_quality(
        component_id="assembled_project",
        files=[
            {"path": "index.html", "content": "<html><body><main><div class='card'>Dashboard</div></main></body></html>"},
            {"path": "src/styles.css", "content": ".card { color: blue; padding: 8px; }"},
        ],
        design_context=context,
        assembled=True,
    )

    assert result["status"] == "fail"
    assert any("design tokens" in item for item in result["blockers"])
    assert any("responsive" in item for item in result["blockers"])
    assert any("design documentation" in item for item in result["blockers"])
    assert "src/styles.css" in result["affected_files"]


def test_design_document_traceability_failure_targets_required_doc_leaves(
    tmp_path: pathlib.Path,
) -> None:
    design = researched_design(tmp_path)
    context = design_research_agent.bounded_design_context(design)
    result = run_local_pipeline_impl.validate_generated_design_quality(
        component_id="docs",
        files=[
            {"path": "docs/design_research.md", "content": "# Research\nGeneric notes.\n"},
            {"path": "docs/design_system.md", "content": "# System\nTokens and layout.\n"},
        ],
        design_context=context,
    )

    assert result["status"] == "fail"
    assert "design documentation cites fewer than three source URLs" in result["blockers"]
    assert "design documentation does not name the selected visual direction" in result["blockers"]
    assert "design documentation omits the anti-copying boundary" in result["blockers"]
    assert result["affected_files"] == [
        "docs/design_research.md",
        "docs/design_system.md",
    ]


def test_design_quality_accepts_traceable_visual_system(tmp_path: pathlib.Path) -> None:
    design = researched_design(tmp_path)
    context = design_research_agent.bounded_design_context(design)
    result = run_local_pipeline_impl.validate_generated_design_quality(
        component_id="assembled_project",
        files=valid_visual_files(design),
        design_context=context,
        assembled=True,
    )

    assert result["status"] == "pass", result["blockers"]
    assert result["metrics"]["custom_property_count"] >= 8
    assert result["metrics"]["design_reference_url_count"] >= 3
