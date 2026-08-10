#!/usr/bin/env python3
"""仅根据已存储的 DOM IR 和浏览器计算结果生成 Compose 源码。"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


class GenerationError(ValueError):
    """生成所需的确定性输入缺失或不一致。"""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GenerationError(f"无法读取生成输入：{path}") from error
    if not isinstance(value, dict):
        raise GenerationError(f"生成输入必须是 JSON 对象：{path}")
    return value


def _kotlin_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _safe_identifier(value: str, fallback: str = "Page") -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not value or value[0].isdigit():
        value = f"_{value}"
    return value or fallback


def _layout_by_id(design: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    source = design.get("nodes", design.get("节点", []))
    for item in source:
        if isinstance(item, dict) and isinstance(item.get("nodeId"), str):
            result[item["nodeId"]] = item
    return result


def _style(layout: dict[str, Any]) -> dict[str, Any]:
    value = layout.get("style", {})
    return value if isinstance(value, dict) else {}


def _container_name(layout: dict[str, Any], child_count: int) -> str:
    style = _style(layout)
    if style.get("display") == "flex":
        return "Row" if style.get("flexDirection") == "row" else "Column"
    if child_count > 1:
        return "Column"
    return "Box"


def _image_records(dom: dict[str, Any], images_path: Path | None) -> dict[str, dict[str, Any]]:
    if images_path is None:
        return {}
    manifest = _load_json(images_path)
    by_source = {
        item.get("sourcePath"): item
        for item in manifest.get("images", [])
        if isinstance(item, dict) and isinstance(item.get("sourcePath"), str)
    }
    result = {}
    for resource in dom.get("resources", []):
        if resource.get("kind") != "image":
            continue
        record = by_source.get(resource.get("resolvedPath"))
        if record is None or not record.get("outputName"):
            raise GenerationError(f"图片资源没有确定的 images.json 映射：{resource.get('resolvedPath')}")
        result[resource["nodeId"]] = record
    return result


def _text_nodes(
    node: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    layouts: dict[str, dict[str, Any]],
    depth: int,
    image_records: dict[str, dict[str, Any]],
) -> list[str]:
    tag = node.get("tag", "")
    node_id = node["nodeId"]
    layout = layouts.get(node_id, {})
    if layout.get("visible") is False:
        return []
    if tag in {"document", "html", "head", "body", "#comment", "#doctype", "script", "style", "link", "meta"}:
        pieces: list[str] = []
        for child_id in node.get("childrenIds", []):
            child = by_id.get(child_id)
            if child:
                pieces.extend(_text_nodes(child, by_id, layouts, depth, image_records))
        return pieces
    indent = "    " * depth
    direct_text = " ".join(str(node.get("directText", "")).split())
    children: list[str] = []
    if direct_text:
        children.append(f'{indent}    Text(text = {_kotlin_string(direct_text)})')
    for child_id in node.get("childrenIds", []):
        child = by_id.get(child_id)
        if child:
            children.extend(_text_nodes(child, by_id, layouts, depth + 1, image_records))
    if tag in {"img", "picture", "svg"}:
        record = image_records.get(node_id)
        if record is None:
            return [f'{indent}    Text(text = {_kotlin_string("[image:" + node_id + "]")})']
        output_name = _safe_identifier(str(record["outputName"]), "asset")
        output_path = str(record.get("outputPath", ""))
        namespace = "mipmap" if "/mipmap" in output_path else "drawable"
        description = node.get("attributes", {}).get("alt") or "null"
        return [
            f"{indent}    Image(",
            f"{indent}        painter = painterResource(id = R.{namespace}.{output_name}),",
            f"{indent}        contentDescription = {_kotlin_string(description) if description != 'null' else 'null'},",
            f"{indent}        modifier = Modifier,",
            f"{indent}        contentScale = ContentScale.FillBounds,",
            f"{indent}    )",
        ]
    if not children:
        return []
    container = _container_name(layout, len(children))
    lines = [f"{indent}    {container}(modifier = Modifier)", f"{indent}    {{"]
    lines.extend(children)
    lines.append(f"{indent}    }}")
    return lines


def _find_generation_root(nodes: list[dict[str, Any]], layouts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_id = {node.get("nodeId"): node for node in nodes if isinstance(node, dict)}
    explicit = next((node for node in nodes if node.get("nodeId") == "design-root"), None)
    if explicit:
        return explicit
    candidates = [
        node for node in nodes
        if node.get("tag") not in {"document", "html", "head", "body", "#comment", "#doctype"}
        and node.get("nodeId") in layouts
        and layouts[node["nodeId"]].get("visible", True) is not False
    ]
    if not candidates:
        raise GenerationError("设计解析中没有可见 DOM 根节点")
    candidate_ids = {node["nodeId"] for node in candidates}
    return next((node for node in candidates if node.get("parentId") not in candidate_ids), candidates[0])


def generate_compose(
    dom_path: Path,
    design_path: Path,
    output_path: Path,
    package_name: str,
    images_path: Path | None = None,
    resource_package: str | None = None,
) -> dict[str, Any]:
    dom = _load_json(dom_path)
    design = _load_json(design_path)
    nodes = dom.get("nodes")
    if dom.get("version") != 1 or not isinstance(nodes, list) or not nodes:
        raise GenerationError(f"DOM IR 无效或为空：{dom_path}")
    layouts = _layout_by_id(design)
    root = _find_generation_root(nodes, layouts)
    by_id = {node.get("nodeId"): node for node in nodes if isinstance(node, dict)}
    page_name = _safe_identifier(output_path.stem)
    image_records = _image_records(dom, images_path)
    root_body = _text_nodes(root, by_id, layouts, 0, image_records)
    if not root_body:
        raise GenerationError(f"DOM 根节点没有可生成的可见内容：{root.get('nodeId')}")
    imports = [
        "import androidx.compose.foundation.layout.Box",
        "import androidx.compose.foundation.layout.Column",
        "import androidx.compose.foundation.layout.Row",
        "import androidx.compose.material3.Text",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.ui.Modifier",
    ]
    if any("Image(" in line for line in root_body):
        imports.extend([
            "import androidx.compose.foundation.Image",
            "import androidx.compose.ui.layout.ContentScale",
            "import androidx.compose.ui.res.painterResource",
            f"import {(resource_package or package_name)}.R",
        ])
    body = [f"package {package_name}", "", *imports, "", f"/** 由 DOM IR 自动生成；输入：{dom_path.name}。 */", "@Composable", f"fun {page_name}() {{", "    Box(modifier = Modifier)", "    {"]
    body.extend(root_body)
    body.extend(["    }", "}", ""])
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text("\n".join(body), encoding="utf-8")
    os.replace(temporary, output_path)
    return {"outputPath": str(output_path), "nodeCount": len(nodes), "rootNodeId": root["nodeId"], "sourceDom": str(dom_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="从已存储 DOM IR 生成 Compose 源码")
    parser.add_argument("--dom", required=True, type=Path)
    parser.add_argument("--design", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--images", type=Path)
    parser.add_argument("--resource-package")
    args = parser.parse_args()
    print(json.dumps(generate_compose(args.dom, args.design, args.output, args.package, args.images, args.resource_package), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
