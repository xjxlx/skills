#!/usr/bin/env python3
"""从蓝湖已加载 CSS 中识别尺寸近似的重复卡片候选。"""

from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_TOLERANCE = 2.0
DIMENSION_PATTERN = re.compile(r"^(-?(?:\d+(?:\.\d+)?|\.\d+))(px|vw|vh|rem|em|%)$")
RULE_PATTERN = re.compile(r"([^{}]+)\{([^{}]*)\}", flags=re.DOTALL)
DECLARATION_PATTERN = re.compile(r"([A-Za-z-]+)\s*:\s*([^;{}]+)(?:;|$)")
URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", flags=re.IGNORECASE | re.DOTALL)
CLASS_PATTERN = re.compile(r"\.([A-Za-z][A-Za-z0-9_-]*)")
LAYOUT_UTILITY_CLASSES = frozenset({"flex-row", "flex-col"})
METRIC_NAMES = ("width", "height", "backgroundWidth", "backgroundHeight")
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})


class DomParentIndex(HTMLParser):
    """只记录 class 与直接父节点，避免用视觉相似度跨区域拼列表。"""

    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[dict] = []
        self.stack: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = next((value for name, value in attrs if name.lower() == "class"), "") or ""
        self.nodes.append({"tag": tag.lower(), "classes": classes.split(), "parent": self.stack[-1] if self.stack else None})
        if tag.lower() not in VOID_TAGS:
            self.stack.append(len(self.nodes) - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[index]]["tag"] == tag:
                del self.stack[index:]
                return


def parse_dimension(value: str) -> tuple[float, str] | None:
    match = DIMENSION_PATTERN.fullmatch(value.strip().removesuffix("!important").strip())
    return (float(match.group(1)), match.group(2)) if match else None


def parse_background_size(value: str) -> tuple[tuple[float, str], tuple[float, str]] | None:
    parts = value.strip().removesuffix("!important").strip().split()
    if len(parts) != 2:
        return None
    width, height = (parse_dimension(part) for part in parts)
    return (width, height) if width and height else None


def declarations(body: str) -> dict[str, str]:
    return {name.lower(): value.strip() for name, value in DECLARATION_PATTERN.findall(body)}


def target_selector(selector: str) -> str | None:
    class_names = [name for name in CLASS_PATTERN.findall(selector) if name not in LAYOUT_UTILITY_CLASSES]
    return class_names[-1] if class_names else None


def block_from_rule(selector: str, body: str, source_css: str) -> dict | None:
    node_name = target_selector(selector)
    values = declarations(body)
    background_match = URL_PATTERN.search(values.get("background", ""))
    width = parse_dimension(values.get("width", ""))
    height = parse_dimension(values.get("height", ""))
    background_size = parse_background_size(values.get("background-size", ""))
    if not node_name or not background_match or not width or not height or not background_size:
        return None
    return {
        "selector": selector.strip(),
        "nodeName": node_name,
        "sourceCss": source_css,
        "backgroundImage": background_match.group(2).strip(),
        "metrics": {
            "width": {"value": width[0], "unit": width[1]},
            "height": {"value": height[0], "unit": height[1]},
            "backgroundWidth": {"value": background_size[0][0], "unit": background_size[0][1]},
            "backgroundHeight": {"value": background_size[1][0], "unit": background_size[1][1]},
        },
    }


def css_blocks(css_text: str, source_css: str) -> list[dict]:
    blocks = []
    for selector, body in RULE_PATTERN.findall(re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)):
        if selector.strip().startswith("@"):
            continue
        for item in selector.split(","):
            block = block_from_rule(item, body, source_css)
            if block:
                blocks.append(block)
    return blocks


def can_join(group: list[dict], block: dict, tolerance: float) -> bool:
    for metric in METRIC_NAMES:
        existing = [item["metrics"][metric] for item in group]
        candidate = block["metrics"][metric]
        if any(item["unit"] != candidate["unit"] for item in existing):
            return False
        values = [item["value"] for item in existing] + [candidate["value"]]
        if max(values) - min(values) > tolerance:
            return False
    return True


def group_blocks(blocks: list[dict], tolerance: float) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for block in sorted(blocks, key=lambda item: (item["sourceCss"], item["selector"])):
        for group in groups:
            if can_join(group, block, tolerance):
                group.append(block)
                break
        else:
            groups.append([block])
    return [group for group in groups if len(group) >= 2]


def metric_ranges(group: list[dict]) -> dict[str, dict]:
    result = {}
    for metric in METRIC_NAMES:
        values = [item["metrics"][metric]["value"] for item in group]
        unit = group[0]["metrics"][metric]["unit"]
        result[metric] = {"min": min(values), "max": max(values), "unit": unit}
    return result


def shared_parent(html_text: str, node_names: list[str]) -> dict | None:
    parser = DomParentIndex()
    parser.feed(html_text)
    parent_sets = []
    for name in node_names:
        parents = {node["parent"] for node in parser.nodes if name in node["classes"] and node["parent"] is not None}
        if not parents:
            return None
        parent_sets.append(parents)
    common = set.intersection(*parent_sets)
    if not common:
        return None
    parent = parser.nodes[min(common)]
    return {
        "tag": parent["tag"],
        "classTokens": [token for token in parent["classes"] if token not in LAYOUT_UTILITY_CLASSES],
    }


def detect_repeated_blocks(
    archive: Path,
    css_paths: list[str],
    html_path: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict:
    if tolerance < 0:
        raise ValueError("tolerance 不能小于 0")
    with zipfile.ZipFile(archive) as zipped:
        html_text = zipped.read(html_path).decode("utf-8", errors="replace")
        blocks = []
        for css_path in css_paths:
            css_text = zipped.read(css_path).decode("utf-8", errors="replace")
            blocks.extend(css_blocks(css_text, css_path))
    groups = group_blocks(blocks, tolerance)
    candidates = []
    for group in groups:
        parent = shared_parent(html_text, [item["nodeName"] for item in group])
        if parent is None:
            continue
        candidates.append(
            {
            "selectors": [item["selector"] for item in group],
            "nodeNames": [item["nodeName"] for item in group],
            "sourceCss": sorted({item["sourceCss"] for item in group}),
            "backgroundImages": [item["backgroundImage"] for item in group],
            "metricRanges": metric_ranges(group),
            "sharedParent": parent,
            "sharedParentConfirmed": True,
            "listAxis": "requires-computed-layout",
        }
        )
    return {
        "version": 1,
        "tolerance": tolerance,
        "cssPaths": css_paths,
        "candidateCount": len(candidates),
        "candidates": candidates,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="识别蓝湖 CSS 中尺寸近似的重复卡片候选")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--html", required=True)
    parser.add_argument("--css", required=True, action="append", dest="css_paths")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args()
    write_json(args.out, detect_repeated_blocks(args.zip, args.css_paths, args.html, args.tolerance))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
