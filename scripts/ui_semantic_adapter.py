#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any


POLICY_VERSION = "interface_ownership_only_v2"


def _capability_stages(contract: dict[str, Any] | None) -> str:
    value = contract if isinstance(contract, dict) else {}
    groups = value.get("capability_groups", [])
    return " ".join(
        str(group.get("stage", ""))
        for group in groups
        if isinstance(group, dict)
    ).lower()


def _convert_button_inline_action(match: re.Match[str]) -> str:
    opening = match.group(0)
    handler_match = re.search(
        r"\son(?:click|change|input|submit)\s*=\s*(['\"])(.*?)\1",
        opening,
        flags=re.I | re.S,
    )
    if not handler_match:
        return opening
    call_match = re.fullmatch(
        r"\s*([A-Za-z_$][\w$]*)\s*\(\s*\)\s*;?\s*",
        handler_match.group(2),
    )
    if not call_match:
        return opening
    converted = opening[: handler_match.start()] + opening[handler_match.end() :]
    if not re.search(r"\bdata-action\s*=", converted, flags=re.I):
        converted = converted[:-1].rstrip() + f' data-action="{call_match.group(1)}">'
    return converted


def adapt_complex_workspace_html(
    content: str,
    contract: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """Apply bounded interface adapters to Provider-authored complex workspace HTML."""
    stages = _capability_stages(contract)
    if not stages:
        return content, []
    actions: list[str] = []
    adapted, converted_count = re.subn(
        r"<button\b[^>]*\son(?:click|change|input|submit)\s*=\s*(['\"]).*?\1[^>]*>",
        _convert_button_inline_action,
        content,
        flags=re.I | re.S,
    )
    if converted_count:
        actions.append("converted_inline_button_actions_to_data_action")

    if (
        len(re.findall(r"<main\b", adapted, flags=re.I)) == 1
        and not re.search(r"</main\s*>", adapted, flags=re.I)
    ):
        adapted, close_count = re.subn(
            r"(?=<script\b[^>]*src\s*=\s*['\"][^'\"]*src/app\.js)",
            "</main>\n",
            adapted,
            count=1,
            flags=re.I,
        )
        if not close_count:
            adapted, close_count = re.subn(
                r"</body>", "</main>\n</body>", adapted, count=1, flags=re.I
            )
        if not close_count:
            adapted = adapted.rstrip() + "\n</main>"
            close_count = 1
        if close_count:
            actions.append("closed_unterminated_main_owner")

    adapted, stale_css_count = re.subn(
        r"\s*<link\b(?=[^>]*\bhref\s*=\s*['\"](?:\./)?styles\.css['\"])[^>]*>",
        "",
        adapted,
        flags=re.I,
    )
    if stale_css_count:
        actions.append("removed_stale_root_css_owner")
    adapted, stale_js_count = re.subn(
        r"\s*<script\b(?=[^>]*\bsrc\s*=\s*['\"](?:\./)?app\.js['\"])[^>]*>\s*</script>",
        "",
        adapted,
        flags=re.I | re.S,
    )
    if stale_js_count:
        actions.append("removed_stale_root_javascript_owner")

    has_modular_app_owner = bool(
        re.search(
            r"<script\b[^>]*src\s*=\s*['\"](?:\./)?src/app\.js['\"]",
            adapted,
            flags=re.I,
        )
    )
    if has_modular_app_owner and re.search(r"<main\b", adapted, flags=re.I):
        adapted, competing_owner_count = re.subn(
            r"\s*<script\b(?=[^>]*\bsrc\s*=\s*['\"](?:\./)?src/main\.js['\"])[^>]*>\s*</script>",
            "",
            adapted,
            flags=re.I | re.S,
        )
        if competing_owner_count:
            actions.append("removed_competing_frontend_owner")
        adapted, empty_root_count = re.subn(
            r"\s*<div\b(?=[^>]*\bid\s*=\s*['\"]root['\"])[^>]*>\s*</div>",
            "",
            adapted,
            flags=re.I | re.S,
        )
        if empty_root_count:
            actions.append("removed_orphaned_empty_root")

    status_opening = re.search(
        r"<[A-Za-z][\w:-]*\b(?=[^>]*(?:role\s*=\s*['\"]status['\"]|aria-live\s*=))[^>]*>",
        adapted,
        flags=re.I | re.S,
    )
    if status_opening and not re.search(
        r"\bid\s*=\s*['\"][^'\"]+['\"]", status_opening.group(0), flags=re.I
    ):
        existing_ids = set(
            re.findall(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", adapted, flags=re.I)
        )
        status_id = "workspace-status"
        suffix = 2
        while status_id in existing_ids:
            status_id = f"workspace-status-{suffix}"
            suffix += 1
        replacement = status_opening.group(0)[:-1].rstrip() + f' id="{status_id}">'
        adapted = (
            adapted[: status_opening.start()]
            + replacement
            + adapted[status_opening.end() :]
        )
        actions.append("added_stable_workspace_status_id")

    if not re.search(r"<link\b[^>]*href\s*=\s*['\"][^'\"]*src/styles\.css", adapted, flags=re.I):
        adapted, owner_count = re.subn(
            r"</head>",
            '<link rel="stylesheet" href="src/styles.css">\n</head>',
            adapted,
            count=1,
            flags=re.I,
        )
        if owner_count:
            actions.append("restored_external_css_owner")
    if not re.search(r"<script\b[^>]*src\s*=\s*['\"][^'\"]*src/app\.js", adapted, flags=re.I):
        adapted, owner_count = re.subn(
            r"</body>",
            '<script src="src/app.js"></script>\n</body>',
            adapted,
            count=1,
            flags=re.I,
        )
        if owner_count:
            actions.append("restored_external_javascript_owner")
    return adapted, actions


def adapt_complex_workspace_javascript(
    content: str,
    accepted_html: str,
) -> tuple[str, list[str]]:
    """Retarget Provider-authored result writes to accepted HTML output interfaces."""
    id_tags = {
        identifier: tag.lower()
        for tag, identifier in re.findall(
            r"<([A-Za-z][\w:-]*)\b[^>]*\bid\s*=\s*['\"]([A-Za-z][\w:.-]*)['\"]",
            accepted_html,
            flags=re.I,
        )
    }
    status_match = re.search(
        r"<[A-Za-z][\w:-]*\b(?=[^>]*(?:role\s*=\s*['\"]status['\"]|aria-live\s*=))[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"]",
        accepted_html,
        flags=re.I | re.S,
    )
    status_id = status_match.group(1) if status_match else ""
    if not status_id:
        return content, []

    region_output_ids: dict[str, str] = {}
    canvas_output_ids: dict[str, str] = {}
    for _tag, attrs, body in re.findall(
        r"<(section|article|aside)\b([^>]*)>(.*?)</(?:section|article|aside)>",
        accepted_html,
        flags=re.I | re.S,
    ):
        region_match = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, flags=re.I)
        output_match = re.search(
            r"<output\b[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"]",
            body,
            flags=re.I,
        )
        if region_match and output_match:
            region_output_ids[region_match.group(1)] = output_match.group(1)
            for canvas_id in re.findall(
                r"<canvas\b[^>]*\bid\s*=\s*['\"]([^'\"]+)['\"]",
                body,
                flags=re.I,
            ):
                canvas_output_ids[canvas_id] = output_match.group(1)

    adapted = content
    actions: list[str] = []
    for region_id, tag in id_tags.items():
        if tag not in {"section", "article", "aside", "main"}:
            continue
        destination_id = region_output_ids.get(region_id, status_id)
        pattern = (
            rf"getElementById\s*\(\s*(['\"]){re.escape(region_id)}\1\s*\)"
            rf"(?=\.(?:textContent|innerHTML)\s*(?:\+?=))"
        )
        adapted, count = re.subn(
            pattern,
            f"getElementById('{destination_id}')",
            adapted,
            flags=re.I,
        )
        if count:
            actions.append("retargeted_region_result_write_to_output_interface")
    for canvas_id, destination_id in canvas_output_ids.items():
        pattern = (
            rf"getElementById\s*\(\s*(['\"]){re.escape(canvas_id)}\1\s*\)"
            rf"(?=\.(?:textContent|innerHTML)\s*(?:\+?=))"
        )
        adapted, count = re.subn(
            pattern,
            f"getElementById('{destination_id}')",
            adapted,
            flags=re.I,
        )
        if count:
            actions.append("retargeted_invalid_canvas_html_write_to_output_interface")
    return adapted, list(dict.fromkeys(actions))


def adapt_complex_workspace_css(
    content: str, accepted_html: str = ""
) -> tuple[str, list[str]]:
    """Repair only selector ownership; never invent visible design declarations."""
    adapted = content
    actions: list[str] = []
    region_tags = [
        tag.lower()
        for tag in re.findall(
            r"<(section|article|aside)\b[^>]*>", accepted_html, flags=re.I
        )
    ]
    if len(region_tags) >= 3 and len(set(region_tags)) == 1:
        region_tag = region_tags[0]
        owned_classes = {
            token.lower()
            for class_value in re.findall(
                r"\bclass\s*=\s*['\"]([^'\"]+)['\"]",
                accepted_html,
                flags=re.I,
            )
            for token in class_value.split()
        }
        if region_tag not in owned_classes and re.search(
            rf"(?<![\w-])\.{re.escape(region_tag)}(?![\w-])",
            adapted,
            flags=re.I,
        ):
            adapted = re.sub(
                rf"(?<![\w-])\.{re.escape(region_tag)}(?![\w-])",
                region_tag,
                adapted,
                flags=re.I,
            )
            actions.append("retargeted_unowned_semantic_class_to_region_tag")
    return adapted, actions
