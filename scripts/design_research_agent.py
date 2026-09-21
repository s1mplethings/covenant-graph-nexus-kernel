#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import market_research_agent
except ModuleNotFoundError:  # package import in tests and tooling
    from scripts import market_research_agent


OPENVERSE_IMAGES_API = "https://api.openverse.org/v1/images/"
VISUAL_INTERACTION_MODES = {"web", "gui", "desktop"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _declared_interaction_modes(blueprint: dict[str, Any] | None) -> tuple[bool, set[str]]:
    """Return authoritative interaction modes when upstream planning declared them.

    Report formats such as HTML are outputs, not interactive surfaces. The
    requirement/discovery lane has better evidence than keyword matching, so a
    declared CLI-only contract suppresses visual-design expansion even when the
    goal mentions an HTML report.
    """
    plan = blueprint if isinstance(blueprint, dict) else {}
    direction = plan.get("selected_project_direction", {})
    complexity = plan.get("complexity_project_contract", {})
    candidates = [
        plan.get("interaction_modes"),
        complexity.get("required_interfaces") if isinstance(complexity, dict) else None,
        direction.get("required_interfaces") if isinstance(direction, dict) else None,
    ]
    if isinstance(direction, dict):
        goal_spec = direction.get("canonical_goal_spec", {})
        if isinstance(goal_spec, dict):
            candidates.append(goal_spec.get("interaction_modes"))
    for value in candidates:
        if isinstance(value, list):
            modes = {
                str(item).strip().lower()
                for item in value
                if str(item).strip().lower() in {"cli", *VISUAL_INTERACTION_MODES}
            }
            if modes:
                return True, modes
    return False, set()


def visual_surface_required(goal: str, blueprint: dict[str, Any] | None = None) -> bool:
    declared, interaction_modes = _declared_interaction_modes(blueprint)
    if declared:
        return bool(VISUAL_INTERACTION_MODES.intersection(interaction_modes))
    text = (str(goal or "") + " " + json.dumps(blueprint or {}, ensure_ascii=False)).lower()
    visual_terms = (
        "web", "website", "ui", "ux", "frontend", "dashboard", "界面",
        "网页", "网站", "看板", "工作台", "可视化", "visual", "图片", "视频",
        "timeline", "editor", "studio", "portal", "播放器", "报告页",
    )
    nonvisual_terms = (
        "cli only", "api only", "library only", "纯命令行", "仅命令行",
        "只要 api", "只要api", "无界面", "不要界面",
    )
    def has_term(term: str) -> bool:
        if re.fullmatch(r"[a-z0-9 -]+", term):
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))
        return term in text

    if any(has_term(term) for term in nonvisual_terms) and not any(
        has_term(term) for term in visual_terms
    ):
        return False
    return any(has_term(term) for term in visual_terms)


def infer_design_archetype(goal: str) -> str:
    lowered = str(goal or "").lower()
    if any(term in lowered for term in ("story", "novel", "creative", "art", "image", "video", "故事", "小说", "创作", "图片", "视频")):
        return "creative_studio"
    if any(term in lowered for term in ("analysis", "evidence", "security", "risk", "monitor", "分析", "证据", "风控", "监控", "检测")):
        return "evidence_workspace"
    if any(term in lowered for term in ("task", "kanban", "project", "workflow", "任务", "看板", "项目管理", "流程")):
        return "calm_productivity"
    if any(term in lowered for term in ("shop", "store", "brand", "commerce", "商店", "品牌", "电商")):
        return "brand_experience"
    return "editorial_product"


def _keywords(goal: str, limit: int = 5) -> str:
    lowered = str(goal or "").lower()
    tokens = re.findall(r"[a-z][a-z0-9+.-]{1,24}", lowered)
    stop = {
        "build", "create", "make", "project", "application", "interface",
        "with", "for", "from", "local", "design", "designed", "ui", "ux",
    }
    aliases: list[str] = []
    if any(term in lowered for term in ("cs2", "csgo", "counter-strike")):
        aliases.extend(["esports", "evidence"])
    elif any(term in lowered for term in ("视频", "video")):
        aliases.extend(["video", "creator"])
    elif any(term in lowered for term in ("任务", "看板", "task", "kanban")):
        aliases.extend(["task", "workspace"])
    elif any(term in lowered for term in ("故事", "小说", "story", "novel")):
        aliases.extend(["story", "editor"])
    for token in [*aliases, *tokens]:
        if token not in stop and token not in aliases:
            aliases.append(token)
        if len(aliases) >= limit:
            break
    return " ".join(aliases[:limit])


def design_search_queries(goal: str, archetype: str) -> list[str]:
    base = _keywords(goal, 2)
    labels = {
        "creative_studio": ["creative editor interface", "editorial creator workspace", "cinematic timeline UI"],
        "evidence_workspace": ["data visualization interface", "investigation case workspace", "interactive timeline visualization"],
        "calm_productivity": ["calm productivity interface", "editorial project workspace", "human centered task UI"],
        "brand_experience": ["expressive brand commerce", "editorial product showcase", "story driven storefront"],
        "editorial_product": ["editorial web application", "expressive product interface", "human centered digital tool"],
    }
    queries = list(labels[archetype])
    if base:
        queries[1] = f"{base} {queries[1]}"
    return queries


def search_openverse(query: str, limit: int = 4) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "page_size": str(limit), "mature": "false"})
    doc = market_research_agent.request_json(f"{OPENVERSE_IMAGES_API}?{params}")
    rows = doc.get("results", []) if isinstance(doc, dict) else []
    results: list[dict[str, Any]] = []
    for row in rows[:limit] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("foreign_landing_url") or row.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "source": "Openverse",
                "source_kind": "licensed_visual_reference",
                "name": str(row.get("title") or "Untitled visual reference")[:200],
                "url": url,
                "thumbnail": str(row.get("thumbnail") or ""),
                "creator": str(row.get("creator") or ""),
                "license": str(row.get("license") or "unknown"),
                "license_url": str(row.get("license_url") or ""),
                "use_boundary": "Analyze composition, rhythm, hierarchy, and tone only; do not copy the asset into the generated project.",
            }
        )
    return results


def search_github_design(query: str, limit: int = 4) -> list[dict[str, Any]]:
    rows = market_research_agent.github_repositories(query, limit=limit)
    return [
        {
            **row,
            "source_kind": "interface_implementation_reference",
            "use_boundary": "Study information architecture and interaction patterns; do not clone source or visual identity.",
        }
        for row in rows
    ]


def search_npm_design(query: str, limit: int = 3) -> list[dict[str, Any]]:
    rows = market_research_agent.npm_packages(query + " design system", limit=limit)
    return [
        {
            **row,
            "source_kind": "design_system_package_reference",
            "use_boundary": "Use only when its license and runtime fit are verified; extract principles rather than accepting default styling.",
        }
        for row in rows
    ]


def curated_design_sources(archetype: str) -> list[dict[str, Any]]:
    catalog = [
        {
            "source": "DesignSystemCatalog",
            "source_kind": "interaction_guidance",
            "name": "Apple Human Interface Guidelines",
            "url": "https://developer.apple.com/design/human-interface-guidelines/",
            "use_boundary": "Use accessibility and interaction principles; do not imitate Apple product identity.",
        },
        {
            "source": "DesignSystemCatalog",
            "source_kind": "visual_system_guidance",
            "name": "Adobe Spectrum",
            "url": "https://spectrum.adobe.com/",
            "use_boundary": "Use component-state and inclusive-design guidance; create a project-specific visual language.",
        },
        {
            "source": "DesignSystemCatalog",
            "source_kind": "visual_system_guidance",
            "name": "Material Design 3",
            "url": "https://m3.material.io/",
            "use_boundary": "Use layout, motion, and accessibility guidance selectively; do not ship an unmodified Material-looking dashboard.",
        },
        {
            "source": "DesignSystemCatalog",
            "source_kind": "data_interface_guidance",
            "name": "IBM Carbon Design System",
            "url": "https://carbondesignsystem.com/",
            "use_boundary": "Use data-density and accessibility guidance; avoid copying Carbon branding or default compositions.",
        },
    ]
    if archetype == "creative_studio":
        return [catalog[1], catalog[0], catalog[2]]
    if archetype == "evidence_workspace":
        return [catalog[3], catalog[0], catalog[1]]
    return [catalog[0], catalog[2], catalog[1]]


def _dedupe_references(rows: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.get("url", "")).strip()
        name = str(row.get("name", "")).strip()
        key = (url or name).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(dict(row))
    source_order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in deduped:
        source = str(item.get("source", "unknown"))
        if source not in buckets:
            source_order.append(source)
            buckets[source] = []
        buckets[source].append(item)
    output: list[dict[str, Any]] = []
    while len(output) < limit and any(buckets[source] for source in source_order):
        for source in source_order:
            if buckets[source] and len(output) < limit:
                item = buckets[source].pop(0)
                item["reference_id"] = f"REF-{len(output) + 1:02d}"
                output.append(item)
    return output


def _palette(archetype: str) -> dict[str, str]:
    palettes = {
        "creative_studio": {
            "canvas": "#F4EFE8", "surface": "#FFF9F2", "ink": "#211A24",
            "muted": "#756A76", "accent": "#B94167", "accent_alt": "#5E4B8B", "signal": "#E48B57",
        },
        "evidence_workspace": {
            "canvas": "#111817", "surface": "#182321", "ink": "#E8F0EA",
            "muted": "#99AAA4", "accent": "#42D3B0", "accent_alt": "#8CA6FF", "signal": "#F3B562",
        },
        "calm_productivity": {
            "canvas": "#F3F0E8", "surface": "#FFFCF5", "ink": "#25302E",
            "muted": "#6E7872", "accent": "#4A65D6", "accent_alt": "#2C8C7D", "signal": "#D97757",
        },
        "brand_experience": {
            "canvas": "#F8F0E3", "surface": "#FFFDF8", "ink": "#251D18",
            "muted": "#786B60", "accent": "#D6472F", "accent_alt": "#2D6B59", "signal": "#E8A840",
        },
        "editorial_product": {
            "canvas": "#F1EFE9", "surface": "#FBFAF6", "ink": "#202521",
            "muted": "#6D746F", "accent": "#3657C8", "accent_alt": "#B54A38", "signal": "#D99B32",
        },
    }
    return palettes[archetype]


def design_directions(archetype: str, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = {
        "creative_studio": [
            ("Narrative Atelier", "tactile, cinematic, authored", "Layered editorial canvas with a strong scene focal point and restrained studio controls."),
            ("Editorial Canvas", "quiet, literary, spacious", "Typography-led composition with marginal notes and generous negative space."),
            ("Cinematic Index", "dramatic, temporal, precise", "Dark screening-room surfaces organized by a luminous narrative timeline."),
        ],
        "evidence_workspace": [
            ("Forensic Editorial", "credible, calm, investigative", "Evidence is read as a case narrative, not a wall of identical cards."),
            ("Signal Observatory", "focused, technical, atmospheric", "A dark field foregrounds signals, relationships, and uncertainty without game-like decoration."),
            ("Field Notes", "human, annotated, reviewable", "Report-like sheets combine metrics with handwritten-style annotations and provenance."),
        ],
        "calm_productivity": [
            ("Calm Workshop", "tactile, focused, humane", "A warm workbench composition gives active work spatial priority over status chrome."),
            ("Editorial Ledger", "ordered, typographic, trustworthy", "Strong typographic rhythm and ruled groupings replace repetitive dashboard cards."),
            ("Spatial Desk", "direct, modular, personal", "Work objects occupy a responsive desk with clear drag, focus, and completion feedback."),
        ],
        "brand_experience": [
            ("Story Commerce", "expressive, crafted, warm", "Products unfold through narrative chapters and materially rich surfaces."),
            ("Gallery Counter", "curated, airy, tactile", "A gallery rhythm gives each product a distinct visual moment and clear action."),
            ("Bold Catalogue", "graphic, energetic, memorable", "Oversized typography and asymmetric grids create brand character without sacrificing scanning."),
        ],
        "editorial_product": [
            ("Editorial Instrument", "distinctive, calm, useful", "The interface behaves like a purpose-built instrument with a strong typographic voice."),
            ("Humanist Workspace", "approachable, layered, clear", "Warm surfaces and progressive disclosure keep complexity understandable."),
            ("Graphic Utility", "bold, direct, rhythmic", "A controlled asymmetric grid and expressive type avoid generic SaaS composition."),
        ],
    }
    reference_ids = [str(item.get("reference_id", "")) for item in references[:6] if item.get("reference_id")]
    output: list[dict[str, Any]] = []
    for index, (name, tone, concept) in enumerate(names[archetype]):
        output.append(
            {
                "direction_id": f"DIR-{index + 1}",
                "name": name,
                "tone": tone,
                "concept": concept,
                "reference_ids": reference_ids[index::3] or reference_ids[:2],
                "layout_signature": [
                    "one dominant focal region instead of a uniform card grid",
                    "asymmetric but aligned composition with deliberate negative space",
                    "detail density revealed progressively around the primary task",
                ],
                "avoid": [
                    "generic admin-dashboard card wall",
                    "default framework colors and typography",
                    "decorative gradients without information purpose",
                    "copying a reference's assets, brand, or exact layout",
                ],
            }
        )
    return output


def build_design_contract(archetype: str, selected: dict[str, Any]) -> dict[str, Any]:
    palette = _palette(archetype)
    return {
        "selected_direction_id": selected.get("direction_id", "DIR-1"),
        "selected_direction_name": selected.get("name", "Editorial Instrument"),
        "selection_reason": "Best balance of product character, task clarity, implementation feasibility, and accessible interaction states.",
        "design_tokens": {
            "color": palette,
            "typography": {
                "display_stack": "Georgia, 'Times New Roman', serif",
                "body_stack": "Inter, ui-sans-serif, system-ui, sans-serif",
                "mono_stack": "'SFMono-Regular', Consolas, monospace",
                "scale": ["0.78rem", "0.9rem", "1rem", "1.25rem", "1.75rem", "clamp(2.4rem, 7vw, 5.8rem)"],
            },
            "space": ["0.25rem", "0.5rem", "0.75rem", "1rem", "1.5rem", "2.5rem", "4rem"],
            "radius": ["0.35rem", "0.8rem", "1.4rem"],
            "motion": {"fast": "120ms", "base": "220ms", "slow": "420ms", "curve": "cubic-bezier(.2,.8,.2,1)"},
        },
        "interaction_principles": [
            "Make one primary action visually dominant and keep secondary controls quiet.",
            "Show hover, pressed, keyboard-focus, disabled, empty, loading, success, and error feedback when applicable.",
            "Use progressive disclosure instead of displaying every control and metric at once.",
            "Respect prefers-reduced-motion and preserve meaning without animation.",
            "Keep touch targets at least 44 by 44 CSS pixels and maintain readable contrast.",
        ],
        "required_project_docs": ["docs/design_research.md", "docs/design_system.md"],
        "implementation_requirements": {
            "minimum_css_custom_properties": 8,
            "minimum_css_declarations": 24,
            "responsive_layout_required": True,
            "keyboard_focus_required": True,
            "interaction_feedback_required": True,
            "reduced_motion_required": True,
            "source_traceability_required": True,
        },
    }


def design_research_semantic_sha256(manifest: dict[str, Any]) -> str:
    """Hash design decisions and sources without artifact-time metadata."""
    source = manifest if isinstance(manifest, dict) else {}
    semantic = {
        "goal": str(source.get("goal", "")),
        "visual_surface_required": bool(source.get("visual_surface_required")),
        "archetype": str(source.get("archetype", "")),
        "references": source.get("references", []),
        "directions": source.get("directions", []),
        "design_contract": source.get("design_contract", {}),
        "market_research_ref": str(source.get("market_research_ref", "")),
    }
    canonical = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bounded_design_context(manifest: dict[str, Any], *, max_references: int = 6) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    references = []
    for item in manifest.get("references", [])[:max_references]:
        if not isinstance(item, dict):
            continue
        references.append(
            {
                "reference_id": str(item.get("reference_id", "")),
                "name": str(item.get("name", ""))[:180],
                "url": str(item.get("url", ""))[:500],
                "source": str(item.get("source", "")),
                "source_kind": str(item.get("source_kind", "")),
                "license": str(item.get("license", "")),
                "use_boundary": str(item.get("use_boundary", ""))[:400],
            }
        )
    selected_id = str(manifest.get("design_contract", {}).get("selected_direction_id", ""))
    selected = next(
        (
            item for item in manifest.get("directions", [])
            if isinstance(item, dict) and str(item.get("direction_id", "")) == selected_id
        ),
        {},
    )
    context = {
        "kind": "CGKNBoundedDesignContext",
        "schema_version": 1,
        "visual_surface_required": bool(manifest.get("visual_surface_required")),
        "archetype": str(manifest.get("archetype", "")),
        "selected_direction": selected,
        "design_contract": manifest.get("design_contract", {}),
        "references": references,
        "research_manifest_sha256": str(manifest.get("manifest_sha256", "")),
        "research_semantic_sha256": str(
            manifest.get("semantic_sha256", "")
            or design_research_semantic_sha256(manifest)
        ),
        "authority": "Design context constrains visual implementation but cannot authorize canonical visual evidence or delivery.",
    }
    identity_context = {
        key: value
        for key, value in context.items()
        if key != "research_manifest_sha256"
    }
    canonical = json.dumps(
        identity_context,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context["context_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return context


def design_research_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Design Research",
        "",
        f"Archetype: `{manifest.get('archetype', '')}`",
        f"Visual surface required: `{str(bool(manifest.get('visual_surface_required'))).lower()}`",
        "",
        "## Search",
        "",
    ]
    for attempt in manifest.get("search_attempts", []):
        lines.append(
            f"- {attempt.get('source', '')}: {attempt.get('workflow_state', '')}; "
            f"query `{attempt.get('query', '')}`; {attempt.get('result_count', 0)} results"
        )
    lines.extend(["", "## References", ""])
    for item in manifest.get("references", []):
        lines.append(
            f"- [{item.get('reference_id', '')}] {item.get('name', '')} — {item.get('url', '')} "
            f"({item.get('use_boundary', '')})"
        )
    lines.extend(["", "## Directions", ""])
    selected_id = manifest.get("design_contract", {}).get("selected_direction_id", "")
    for direction in manifest.get("directions", []):
        selected = " **selected**" if direction.get("direction_id") == selected_id else ""
        lines.append(f"- {direction.get('direction_id')}: {direction.get('name')} — {direction.get('concept')}{selected}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "References are used to analyze principles, hierarchy, rhythm, states, and tone. Generated projects must not copy source assets, branding, or exact layouts.",
            "",
        ]
    )
    return "\n".join(lines)


def run_design_research(
    goal: str,
    blueprint: dict[str, Any],
    market_research: dict[str, Any],
    out_dir: pathlib.Path,
    *,
    searchers: list[tuple[str, Callable[[str], list[dict[str, Any]]]]] | None = None,
) -> dict[str, Any]:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    required = visual_surface_required(goal, blueprint)
    archetype = infer_design_archetype(goal)
    queries = design_search_queries(goal, archetype)
    configured_searchers = searchers or [
        ("Openverse", search_openverse),
        ("GitHub", search_github_design),
        ("npm", search_npm_design),
    ]
    found: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    if required:
        for index, (source, searcher) in enumerate(configured_searchers):
            query = queries[index % len(queries)]
            try:
                rows = searcher(query)
                found.extend(rows)
                attempts.append({"source": source, "query": query, "workflow_state": "completed", "result_count": len(rows)})
            except Exception as exc:
                attempts.append({"source": source, "query": query, "workflow_state": "failed", "result_count": 0, "error": str(exc)[:300]})
    curated = curated_design_sources(archetype) if required else []
    references = _dedupe_references([*found, *curated])
    directions = design_directions(archetype, references)
    design_contract = build_design_contract(archetype, directions[0])
    manifest: dict[str, Any] = {
        "kind": "CGKNDesignResearchManifest",
        "schema_version": 1,
        "created_at": now(),
        "goal": goal,
        "visual_surface_required": required,
        "workflow_state": "completed",
        "archetype": archetype,
        "strategy": "search multiple reference classes, derive competing directions, select one project-specific system, and preserve anti-copying boundaries",
        "search_queries": queries if required else [],
        "search_attempts": attempts,
        "references": references,
        "directions": directions,
        "design_contract": design_contract,
        "market_research_ref": hashlib.sha256(
            json.dumps(market_research or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "limitations": [
            "Search results are design inputs, not implementation truth.",
            "Source licenses and project asset licenses must be checked independently before reuse.",
            "Canonical browser visual evidence and user review remain required when the delivery contract requires them.",
        ],
    }
    manifest["semantic_sha256"] = design_research_semantic_sha256(manifest)
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    (out_dir / "design_research.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "DESIGN_RESEARCH.md").write_text(
        design_research_markdown(manifest),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--blueprint", default="")
    parser.add_argument("--market-research", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    blueprint = json.loads(pathlib.Path(args.blueprint).read_text(encoding="utf-8")) if args.blueprint else {}
    market_research = json.loads(pathlib.Path(args.market_research).read_text(encoding="utf-8")) if args.market_research else {}
    result = run_design_research(args.goal, blueprint, market_research, pathlib.Path(args.out_dir))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"DESIGN_RESEARCH: references={len(result['references'])} directions={len(result['directions'])}")
        print(pathlib.Path(args.out_dir).resolve() / "design_research.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
