#!/usr/bin/env python3
"""根据已存储的 DOM IR 和浏览器最终事实生成高保真 Compose 视觉基线。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


class GenerationError(ValueError):
    """生成所需的确定性输入缺失、不一致或无法安全表达。"""


_URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d+)?|\.\d+)")
_RGB_PATTERN = re.compile(r"rgba?\(([^)]+)\)", re.IGNORECASE)
_HEX_PATTERN = re.compile(r"^#([0-9a-f]{3,8})$", re.IGNORECASE)
_KOTLIN_KEYWORDS = frozenset(
    {
        "as", "break", "class", "continue", "do", "else", "false", "for", "fun", "if", "in",
        "interface", "is", "null", "object", "package", "return", "super", "this", "throw", "true",
        "try", "typealias", "typeof", "val", "var", "when", "while",
    }
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GenerationError(f"无法读取生成输入：{path}") from error
    if not isinstance(value, dict):
        raise GenerationError(f"生成输入必须是 JSON 对象：{path}")
    return value


def _kotlin_string(value: str) -> str:
    """使用与 Kotlin 兼容的 JSON 转义，并阻止 `$` 被解释为字符串模板。"""
    return json.dumps(value, ensure_ascii=False).replace("$", r"\$")


def _safe_identifier(value: str, fallback: str = "Page") -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not any(character.isalnum() for character in value):
        return fallback
    if not value or value[0].isdigit():
        value = f"_{value}"
    if value in _KOTLIN_KEYWORDS:
        value = f"{fallback}_{value}"
    return value


def _kotlin_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) or not any(character.isalnum() for character in value):
        raise GenerationError(f"不是合法 Kotlin 标识符：{value}")
    return f"`{value}`" if value in _KOTLIN_KEYWORDS else value


def _kotlin_qualified_name(value: str) -> str:
    parts = value.split(".")
    if not parts or any(not part for part in parts):
        raise GenerationError(f"不是合法 Kotlin 限定名：{value}")
    return ".".join(_kotlin_identifier(part) for part in parts)


def _android_resource_name(record: dict[str, Any]) -> str:
    raw = str(record.get("outputName") or Path(str(record.get("outputPath", ""))).name)
    stem = Path(raw).stem
    value = re.sub(r"[^a-z0-9_]", "_", stem.lower()).strip("_")
    if not value:
        raise GenerationError(f"图片资源缺少合法 Android 名称：{record}")
    if value[0].isdigit():
        value = f"asset_{value}"
    return _kotlin_identifier(value)


def _resource_namespace(record: dict[str, Any]) -> str:
    output_path = str(record.get("outputPath", "")).replace("\\", "/")
    return "mipmap" if "/mipmap" in output_path else "drawable"


def _design_nodes(design: dict[str, Any]) -> list[dict[str, Any]]:
    source = design.get("nodes", design.get("节点", []))
    return [item for item in source if isinstance(item, dict)] if isinstance(source, list) else []


def _layout_by_id(design: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["nodeId"]: item
        for item in _design_nodes(design)
        if isinstance(item.get("nodeId"), str) and item["nodeId"]
    }


def _style(layout: dict[str, Any]) -> dict[str, Any]:
    value = layout.get("style", {})
    return value if isinstance(value, dict) else {}


def _container_name(layout: dict[str, Any], child_count: int) -> str:
    style = _style(layout)
    if style.get("display") == "flex":
        return "Row" if style.get("flexDirection") in {"row", "row-reverse"} else "Column"
    return "Column" if child_count > 1 else "Box"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER_PATTERN.match(value.strip())
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _format_float(value: float) -> str:
    rounded = round(value, 3)
    if rounded == 0:
        rounded = 0.0
    if rounded.is_integer():
        return f"{int(rounded)}f"
    return f"{rounded:g}f"


def _bounds(layout: dict[str, Any]) -> dict[str, float] | None:
    raw = layout.get("bounds", layout.get("边界"))
    if not isinstance(raw, dict):
        return None
    values = {name: _number(raw.get(name)) for name in ("x", "y", "width", "height")}
    if any(value is None for value in values.values()):
        return None
    return {name: float(value) for name, value in values.items() if value is not None}


def _design_root_id(design: dict[str, Any]) -> str | None:
    root = design.get("设计根节点", design.get("designRoot"))
    if isinstance(root, dict) and isinstance(root.get("nodeId"), str):
        return root["nodeId"]
    return None


def _find_generation_root(
    nodes: list[dict[str, Any]],
    layouts: dict[str, dict[str, Any]],
    design: dict[str, Any],
) -> dict[str, Any]:
    by_id = {node.get("nodeId"): node for node in nodes if isinstance(node, dict)}
    explicit_id = _design_root_id(design)
    if explicit_id in by_id:
        return by_id[explicit_id]
    candidates = [
        node
        for node in nodes
        if node.get("tag") not in {"document", "html", "head", "#comment", "#doctype"}
        and node.get("nodeId") in layouts
        and layouts[node["nodeId"]].get("visible", True) is not False
    ]
    if not candidates:
        raise GenerationError("设计解析中没有可见 DOM 根节点")
    candidate_ids = {node["nodeId"] for node in candidates}
    return next((node for node in candidates if node.get("parentId") not in candidate_ids), candidates[0])


def _root_bounds(design: dict[str, Any], root_layout: dict[str, Any]) -> dict[str, float]:
    result = _bounds(root_layout)
    if result is not None:
        return result
    root = design.get("设计根节点", design.get("designRoot"))
    if isinstance(root, dict):
        result = _bounds(root)
        if result is not None:
            return result
    canvas = design.get("设计画布", {})
    width = _number(canvas.get("宽度像素")) if isinstance(canvas, dict) else None
    height = _number(canvas.get("高度像素")) if isinstance(canvas, dict) else None
    return {"x": 0.0, "y": 0.0, "width": width or 1.0, "height": height or 1.0}


def _canvas_size(design: dict[str, Any], root_bounds: dict[str, float]) -> tuple[float, float]:
    canvas = design.get("设计画布", {})
    width = _number(canvas.get("宽度像素")) if isinstance(canvas, dict) else None
    height = _number(canvas.get("高度像素")) if isinstance(canvas, dict) else None
    width = width or _number(design.get("canvasWidthPx")) or root_bounds["width"]
    height = height or _number(design.get("canvasHeightPx")) or root_bounds["height"]
    if width <= 0 or height <= 0:
        raise GenerationError(f"设计画布尺寸无效：{width}×{height}")
    return width, height


def _normalise_source_path(value: str) -> str:
    value = unquote(value).replace("\\", "/").split("?", 1)[0].split("#", 1)[0]
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value
    parts = [part for part in PurePosixPath(path.lstrip("/")).parts if part not in {"", "."}]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _manifest_records(images_path: Path | None) -> list[dict[str, Any]]:
    if images_path is None:
        return []
    manifest = _load_json(images_path)
    values = manifest.get("images", [])
    if not isinstance(values, list):
        raise GenerationError(f"images.json 的 images 必须是数组：{images_path}")
    return [item for item in values if isinstance(item, dict) and isinstance(item.get("sourcePath"), str)]


def _record_for_source(source: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate = _normalise_source_path(source)
    if not candidate:
        return None
    exact = [record for record in records if _normalise_source_path(str(record["sourcePath"])) == candidate]
    if len(exact) == 1:
        return exact[0]
    suffix = [
        record
        for record in records
        if candidate.endswith("/" + _normalise_source_path(str(record["sourcePath"])))
        or _normalise_source_path(str(record["sourcePath"])).endswith("/" + candidate)
    ]
    unique = {str(record.get("sourcePath")): record for record in suffix}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(exact) > 1 or len(unique) > 1:
        raise GenerationError(f"图片 URL 无法唯一对应 images.json：{source}")
    return None


def _final_image_sources(design: dict[str, Any]) -> dict[str, str]:
    source = design.get("images", design.get("图片资源", []))
    result: dict[str, str] = {}
    if not isinstance(source, list):
        return result
    for item in source:
        if not isinstance(item, dict) or not isinstance(item.get("nodeId"), str):
            continue
        value = item.get("source") or item.get("currentSrc") or item.get("src")
        if isinstance(value, str) and value:
            result[item["nodeId"]] = value
    return result


def _image_records(
    dom: dict[str, Any],
    design: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node_id, source in _final_image_sources(design).items():
        record = _record_for_source(source, records)
        if record is not None:
            result[node_id] = record
    for resource in dom.get("resources", []):
        if not isinstance(resource, dict) or resource.get("kind") != "image":
            continue
        node_id = resource.get("nodeId")
        if not isinstance(node_id, str) or node_id in result:
            continue
        resolved = resource.get("resolvedPath")
        if isinstance(resolved, str):
            record = _record_for_source(resolved, records)
            if record is not None:
                result[node_id] = record
    return result


def _background_record(style: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    value = style.get("backgroundImage")
    if not isinstance(value, str) or value in {"", "none"}:
        return None
    repeat = str(style.get("backgroundRepeat", "")).strip().lower()
    if repeat and repeat != "no-repeat":
        raise GenerationError(f"CSS background-repeat 暂无无损 Compose 映射：{repeat}")
    size = str(style.get("backgroundSize", "")).strip().lower()
    if size and size not in {"cover", "contain", "100% 100%"}:
        raise GenerationError(f"CSS background-size 暂无无损 Compose 映射：{size}")
    urls = [match.group(2) for match in _URL_PATTERN.finditer(value)]
    unparsed = _URL_PATTERN.sub("", value).strip(" ,\t\r\n")
    if len(urls) != 1 or unparsed:
        raise GenerationError(f"CSS background-image 无法精确映射为单一 Android 资源：{value}")
    record = _record_for_source(urls[0], records)
    if record is None:
        raise GenerationError(f"CSS 背景图没有确定的 images.json 映射：{urls[0]}")
    return record


def _color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not value or value == "transparent":
        return None
    match = _HEX_PATTERN.match(value)
    if match:
        raw = match.group(1)
        if len(raw) in {3, 4}:
            raw = "".join(character * 2 for character in raw)
        if len(raw) == 6:
            raw = "ff" + raw
        elif len(raw) == 8:
            raw = raw[6:8] + raw[:6]
        else:
            return None
        return f"Color(0x{raw.upper()})" if raw != "00000000" else None
    match = _RGB_PATTERN.match(value)
    if match is None:
        return None
    parts = [part.strip() for part in match.group(1).split(",")]
    if len(parts) not in {3, 4}:
        return None
    try:
        rgb = [max(0, min(255, round(float(part.rstrip("%")) * (2.55 if "%" in part else 1)))) for part in parts[:3]]
        alpha_value = float(parts[3].rstrip("%")) / (100 if "%" in parts[3] else 1) if len(parts) == 4 else 1
    except ValueError:
        return None
    alpha = max(0, min(255, round(alpha_value * 255)))
    if alpha == 0:
        return None
    return f"Color(0x{alpha:02X}{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X})"


def _text_color(value: Any) -> str | None:
    """文字的完全透明色必须显式保留，不能退回 Material 默认黑色。"""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "transparent":
            return "Color.Transparent"
        rgba = _RGB_PATTERN.match(normalized)
        if rgba is not None:
            parts = [part.strip() for part in rgba.group(1).split(",")]
            if len(parts) == 4:
                try:
                    alpha = float(parts[3].rstrip("%")) / (100 if "%" in parts[3] else 1)
                except ValueError:
                    alpha = 1
                if alpha <= 0:
                    return "Color.Transparent"
        hexadecimal = _HEX_PATTERN.match(normalized)
        if hexadecimal is not None:
            raw = hexadecimal.group(1)
            if (len(raw) == 4 and raw[-1] == "0") or (len(raw) == 8 and raw[-2:] == "00"):
                return "Color.Transparent"
    result = _color(value)
    if result is None and isinstance(value, str) and value.strip() and value.strip().lower() != "transparent":
        raise GenerationError(f"CSS 文字颜色无法可靠转换为 Compose sRGB：{value}")
    return result


def _strict_color(value: Any, context: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    result = _color(value)
    normalized = value.strip().lower()
    if result is None and normalized != "transparent" and "rgba(" not in normalized and not normalized.endswith("00"):
        raise GenerationError(f"CSS {context} 颜色无法可靠转换为 Compose sRGB：{value}")
    return result


def _css_radius(value: Any) -> float:
    raw = str(value or "0").strip().lower().replace("/", " ")
    tokens = raw.split()
    values: list[float] = []
    for token in tokens or ["0"]:
        match = re.fullmatch(r"(-?(?:\d+(?:\.\d+)?|\.\d+))(px)?", token)
        if match is None or (match.group(2) is None and float(match.group(1)) != 0):
            raise GenerationError(f"border-radius 暂不支持非像素值：{value}")
        values.append(float(match.group(1)))
    if any(radius < 0 for radius in values) or any(abs(radius - values[0]) > 0.001 for radius in values[1:]):
        raise GenerationError(f"border-radius 暂不支持椭圆或负半径：{value}")
    return values[0]


def _shape(style: dict[str, Any]) -> str | None:
    corner_keys = (
        "borderTopLeftRadius",
        "borderTopRightRadius",
        "borderBottomRightRadius",
        "borderBottomLeftRadius",
    )
    if any(key in style for key in corner_keys):
        radii = [_css_radius(style.get(key)) for key in corner_keys]
    else:
        shorthand = str(style.get("borderRadius", "0")).strip()
        if len(shorthand.replace("/", " ").split()) > 2:
            raise GenerationError(f"非统一 border-radius 缺少四角 computed style：{shorthand}")
        radii = [_css_radius(shorthand)] * 4
    if not any(radius > 0 for radius in radii):
        return None
    if all(abs(radius - radii[0]) <= 0.001 for radius in radii[1:]):
        return f"RoundedCornerShape(designDp({_format_float(radii[0])}, scaleY))"
    return (
        "AbsoluteRoundedCornerShape("
        f"topLeft = designDp({_format_float(radii[0])}, scaleY), "
        f"topRight = designDp({_format_float(radii[1])}, scaleY), "
        f"bottomRight = designDp({_format_float(radii[2])}, scaleY), "
        f"bottomLeft = designDp({_format_float(radii[3])}, scaleY))"
    )


def _border(style: dict[str, Any]) -> tuple[float, str] | None:
    raw_width = style.get("borderWidth")
    if isinstance(raw_width, str):
        widths = [_number(token) for token in raw_width.split()]
        if len(widths) > 1 and (any(width is None for width in widths) or len({round(float(width), 4) for width in widths if width is not None}) > 1):
            raise GenerationError(f"非统一 border-width 暂无无损 Compose 映射：{raw_width}")
    raw_color = style.get("borderColor")
    if isinstance(raw_color, str):
        colors = re.findall(r"rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}|transparent", raw_color, re.I)
        if len({_color(color) for color in colors}) > 1:
            raise GenerationError(f"非统一 border-color 暂无无损 Compose 映射：{raw_color}")
    width = _number(raw_width)
    color = _strict_color(raw_color, "border")
    border_style = str(style.get("borderStyle", "")).strip().lower()
    raw_border = str(style.get("border", "")).lower()
    unsupported_styles = {"dashed", "dotted", "double", "groove", "ridge", "inset", "outset"}
    if any(token in unsupported_styles for token in border_style.split()) or any(
        re.search(rf"\b{token}\b", raw_border) for token in unsupported_styles
    ):
        raise GenerationError(f"非 solid CSS border 暂无无损 Compose 映射：{border_style or raw_border}")
    if width is None or color is None:
        raw = style.get("border")
        if isinstance(raw, str):
            width = width or _number(raw)
            rgb = _RGB_PATTERN.search(raw)
            hex_value = re.search(r"#[0-9a-fA-F]{3,8}", raw)
            color = color or _color(rgb.group(0) if rgb else hex_value.group(0) if hex_value else None)
    if width is None or width <= 0 or color is None:
        return None
    return width, color


def _content_scale(value: Any) -> str:
    value = str(value or "").lower()
    if value == "cover":
        return "ContentScale.Crop"
    if value == "contain":
        return "ContentScale.Fit"
    if value == "scale-down":
        return "ContentScale.Inside"
    if value == "none":
        return "ContentScale.None"
    return "ContentScale.FillBounds"


def _image_alignment(value: Any) -> str:
    """映射 CSS object/background-position；无法确定的长度值必须显式失败。"""
    raw = str(value or "50% 50%").strip().lower()
    tokens = raw.split()
    if len(tokens) == 1:
        tokens = ["50%", tokens[0]] if tokens[0] in {"top", "bottom"} else [tokens[0], "50%"]
    if len(tokens) != 2:
        raise GenerationError(f"CSS 图片位置无法精确映射：{value}")
    if tokens[0] in {"top", "bottom"} and tokens[1] in {"left", "center", "right"}:
        tokens.reverse()
    horizontal_names = {"left": 0.0, "center": 50.0, "right": 100.0}
    vertical_names = {"top": 0.0, "center": 50.0, "bottom": 100.0}

    def percentage(token: str, names: dict[str, float]) -> float:
        if token in names:
            return names[token]
        if token.endswith("%"):
            try:
                return float(token[:-1])
            except ValueError:
                pass
        raise GenerationError(f"CSS 图片位置暂不支持非百分比长度：{value}")

    x = percentage(tokens[0], horizontal_names)
    y = percentage(tokens[1], vertical_names)
    constants = {
        (0.0, 0.0): "Alignment.TopStart",
        (50.0, 0.0): "Alignment.TopCenter",
        (100.0, 0.0): "Alignment.TopEnd",
        (0.0, 50.0): "Alignment.CenterStart",
        (50.0, 50.0): "Alignment.Center",
        (100.0, 50.0): "Alignment.CenterEnd",
        (0.0, 100.0): "Alignment.BottomStart",
        (50.0, 100.0): "Alignment.BottomCenter",
        (100.0, 100.0): "Alignment.BottomEnd",
    }
    constant = constants.get((x, y))
    if constant is not None:
        return constant
    return f"BiasAlignment({_format_float(x / 50.0 - 1.0)}, {_format_float(y / 50.0 - 1.0)})"


def _relative_bounds(layout: dict[str, Any], root: dict[str, float]) -> dict[str, float] | None:
    value = _bounds(layout)
    if value is None:
        return None
    return {
        "x": value["x"] - root["x"],
        "y": value["y"] - root["y"],
        "width": value["width"],
        "height": value["height"],
    }


def _modifier(
    bounds: dict[str, float] | None,
    style: dict[str, Any],
    *,
    clip_shape: str | None = None,
    background: str | None = None,
    border: tuple[float, str] | None = None,
) -> str:
    parts = ["Modifier"]
    if bounds is not None:
        parts.append(
            f"offset(designDp({_format_float(bounds['x'])}, scaleX), designDp({_format_float(bounds['y'])}, scaleY))"
        )
        if bounds["width"] > 0 and bounds["height"] > 0:
            parts.append(
                f"size(designDp({_format_float(bounds['width'])}, scaleX), designDp({_format_float(bounds['height'])}, scaleY))"
            )
    # Chrome paintOrder 已经把 CSS stacking context 展平；再次应用原始 z-index
    # 会让嵌套 context 的子节点逃逸到兄弟 context 之上。
    opacity = _number(style.get("effectiveOpacity", style.get("opacity")))
    if opacity is not None and 0 < opacity < 1:
        parts.append(f"alpha({_format_float(opacity)})")
    if clip_shape is not None:
        parts.append(f"clip({clip_shape})")
    if background is not None:
        shape_argument = f", shape = {clip_shape}" if clip_shape is not None else ""
        parts.append(f"background(color = {background}{shape_argument})")
    if border is not None:
        shape_argument = f", shape = {clip_shape}" if clip_shape is not None else ""
        parts.append(f"border(designDp({_format_float(border[0])}, fontScale), {border[1]}{shape_argument})")
    return ".".join(parts)


def _font_family(value: Any) -> str | None:
    family = str(value or "").lower()
    if "monospace" in family:
        return "FontFamily.Monospace"
    if "serif" in family and "sans-serif" not in family:
        return "FontFamily.Serif"
    if "sans-serif" in family:
        return "FontFamily.SansSerif"
    return None


def _text_align(value: Any) -> str | None:
    return {
        "center": "TextAlign.Center",
        "right": "TextAlign.Right",
        "end": "TextAlign.End",
        "justify": "TextAlign.Justify",
        "left": "TextAlign.Left",
        "start": "TextAlign.Start",
    }.get(str(value or "").lower())


def _walk_dom(root: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> Iterable[dict[str, Any]]:
    yield root
    for child_id in root.get("childrenIds", []):
        child = by_id.get(child_id)
        if child is not None:
            yield from _walk_dom(child, by_id)


def _validate_flattening_safety(
    root: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    layouts: dict[str, dict[str, Any]],
    text_runs: list[dict[str, Any]],
) -> None:
    """检测扁平绝对布局无法无损表达的分组变换、透明度与裁剪。"""
    for ancestor in _walk_dom(root, by_id):
        ancestor_id = ancestor.get("nodeId")
        if not isinstance(ancestor_id, str):
            continue
        layout = layouts.get(ancestor_id)
        if layout is None or layout.get("visible") is False:
            continue
        style = _style(layout)
        transform = str(style.get("transform", "none")).strip().lower()
        if transform not in {"", "none"}:
            matrix = re.fullmatch(r"matrix\(\s*([^)]*)\)", transform)
            try:
                values = [float(value.strip()) for value in matrix.group(1).split(",")] if matrix else []
            except ValueError:
                values = []
            if len(values) != 6 or any(
                abs(actual - expected) > 0.0001
                for actual, expected in zip(values[:4], (1.0, 0.0, 0.0, 1.0), strict=True)
            ):
                raise GenerationError(f"节点 {ancestor_id} 的 CSS transform 无法只靠 bounds 无损还原：{transform}")
        descendants = list(_walk_dom(ancestor, by_id))[1:]
        descendant_ids = {str(item.get("nodeId")) for item in descendants}
        descendant_ids.add(ancestor_id)
        visible_descendants = [
            item
            for item in descendants
            if (candidate := layouts.get(str(item.get("nodeId")))) is not None
            and candidate.get("visible") is not False
        ]
        visible_runs = [run for run in text_runs if run.get("hostNodeId") in descendant_ids]
        own_opacity = _number(style.get("opacity"))
        primitive_count = sum(
            (
                bool(_color(style.get("backgroundColor"))),
                isinstance(style.get("backgroundImage"), str) and style.get("backgroundImage") not in {"", "none"},
                _number(style.get("borderWidth")) not in {None, 0},
                str(ancestor.get("tag", "")) == "img",
            )
        )
        if own_opacity is not None and 0 < own_opacity < 1 and (
            visible_descendants or visible_runs or primitive_count > 1
        ):
            raise GenerationError(f"节点 {ancestor_id} 的子树 opacity 需要分组合成，当前扁平基线无法无损表达")
        overflow_x = str(style.get("overflowX", style.get("overflow", "visible"))).lower()
        overflow_y = str(style.get("overflowY", style.get("overflow", "visible"))).lower()
        clips_x = overflow_x in {"hidden", "clip"}
        clips_y = overflow_y in {"hidden", "clip"}
        if not clips_x and not clips_y:
            continue
        ancestor_bounds = _bounds(layout)
        if ancestor_bounds is None:
            raise GenerationError(f"overflow 裁剪节点缺少浏览器边界：{ancestor_id}")
        if _shape(style) is not None and (visible_descendants or visible_runs):
            raise GenerationError(f"节点 {ancestor_id} 的圆角 overflow 需要裁剪整个子树，当前扁平基线无法无损表达")
        for descendant in descendants:
            descendant_id = descendant.get("nodeId")
            child_layout = layouts.get(str(descendant_id))
            if child_layout is None or child_layout.get("visible") is False:
                continue
            child_bounds = _bounds(child_layout)
            if child_bounds is None:
                continue
            outside_x = child_bounds["x"] < ancestor_bounds["x"] - 0.5 or (
                child_bounds["x"] + child_bounds["width"] > ancestor_bounds["x"] + ancestor_bounds["width"] + 0.5
            )
            outside_y = child_bounds["y"] < ancestor_bounds["y"] - 0.5 or (
                child_bounds["y"] + child_bounds["height"] > ancestor_bounds["y"] + ancestor_bounds["height"] + 0.5
            )
            if (clips_x and outside_x) or (clips_y and outside_y):
                raise GenerationError(
                    f"父节点 {ancestor_id} 的 overflow 裁剪会截断子节点 {descendant_id}；"
                    "当前扁平 Compose 基线无法无损表达"
                )
        for run in visible_runs:
            run_bounds = _bounds(run)
            if run_bounds is None:
                continue
            outside_x = run_bounds["x"] < ancestor_bounds["x"] - 0.5 or (
                run_bounds["x"] + run_bounds["width"] > ancestor_bounds["x"] + ancestor_bounds["width"] + 0.5
            )
            outside_y = run_bounds["y"] < ancestor_bounds["y"] - 0.5 or (
                run_bounds["y"] + run_bounds["height"] > ancestor_bounds["y"] + ancestor_bounds["height"] + 0.5
            )
            if (clips_x and outside_x) or (clips_y and outside_y):
                raise GenerationError(f"父节点 {ancestor_id} 的 overflow 裁剪会截断文本片段 {run.get('nodeId')}")


def _render_image(
    record: dict[str, Any],
    bounds: dict[str, float] | None,
    style: dict[str, Any],
    description: str | None,
    scale: str,
    shape: str | None,
    indent: str,
    border: tuple[float, str] | None = None,
    alignment: str = "Alignment.Center",
) -> list[str]:
    modifier = _modifier(bounds, style, clip_shape=shape, border=border)
    return [
        f"{indent}Image(",
        f"{indent}    painter = painterResource(id = R.{_resource_namespace(record)}.{_android_resource_name(record)}),",
        f"{indent}    contentDescription = {_kotlin_string(description) if description else 'null'},",
        f"{indent}    modifier = {modifier},",
        f"{indent}    contentScale = {scale},",
        f"{indent}    alignment = {alignment},",
        f"{indent})",
    ]


def _render_text(
    text: str,
    bounds: dict[str, float] | None,
    style: dict[str, Any],
    indent: str,
) -> list[str]:
    text_transform = str(style.get("textTransform", "none")).lower()
    if text_transform not in {"", "none"}:
        raise GenerationError(f"CSS text-transform 暂无逐文本片段的可靠映射：{text_transform}")
    arguments = [
        f"text = {_kotlin_string(text)}",
        f"modifier = {_modifier(bounds, style)}",
    ]
    color = _text_color(style.get("color"))
    if color:
        arguments.append(f"color = {color}")
    font_size = _number(style.get("fontSize"))
    if font_size is not None and font_size > 0:
        arguments.append(f"fontSize = designSp({_format_float(font_size)}, fontScale)")
    font_weight = _number(style.get("fontWeight"))
    if font_weight is not None:
        arguments.append(f"fontWeight = FontWeight({round(font_weight)})")
    family = _font_family(style.get("fontFamily"))
    if family:
        arguments.append(f"fontFamily = {family}")
    font_style = str(style.get("fontStyle", "normal")).lower()
    if font_style == "italic":
        arguments.append("fontStyle = FontStyle.Italic")
    elif font_style not in {"", "normal"}:
        raise GenerationError(f"CSS font-style 暂无可靠映射：{font_style}")
    line_height = _number(style.get("lineHeight"))
    if line_height is not None and line_height > 0:
        arguments.append(f"lineHeight = designSp({_format_float(line_height)}, fontScale)")
    letter_spacing = _number(style.get("letterSpacing"))
    if letter_spacing is not None and letter_spacing != 0:
        arguments.append(f"letterSpacing = designSp({_format_float(letter_spacing)}, fontScale)")
    text_align = _text_align(style.get("textAlign"))
    if text_align:
        arguments.append(f"textAlign = {text_align}")
    decoration_tokens = set(str(style.get("textDecorationLine", "none")).lower().split())
    decoration_tokens.discard("none")
    if decoration_tokens:
        if not decoration_tokens <= {"underline", "line-through"}:
            raise GenerationError(f"CSS text-decoration-line 暂无可靠映射：{sorted(decoration_tokens)}")
        decorations = []
        if "underline" in decoration_tokens:
            decorations.append("TextDecoration.Underline")
        if "line-through" in decoration_tokens:
            decorations.append("TextDecoration.LineThrough")
        value = decorations[0] if len(decorations) == 1 else f"TextDecoration.combine(listOf({', '.join(decorations)}))"
        arguments.append(f"textDecoration = {value}")
    if bounds is not None and line_height is not None and line_height > 0:
        arguments.append(f"maxLines = {max(1, round(bounds['height'] / line_height))}")
        arguments.append("overflow = TextOverflow.Clip")
    lines = [f"{indent}Text("]
    lines.extend(f"{indent}    {argument}," for argument in arguments)
    lines.append(f"{indent})")
    return lines


def _render_visual_tree(
    root: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    layouts: dict[str, dict[str, Any]],
    image_records: dict[str, dict[str, Any]],
    manifest_records: list[dict[str, Any]],
    root_bounds: dict[str, float],
    text_runs: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    events: list[tuple[float, int, list[str]]] = []
    sequence = 0
    counters = {"styledNodeCount": 0, "textCount": 0, "imageCount": 0, "backgroundImageCount": 0}
    dom_nodes = list(_walk_dom(root, by_id))
    allowed_node_ids = {str(node.get("nodeId")) for node in dom_nodes}
    for dom_index, node in enumerate(dom_nodes):
        node_id = node.get("nodeId")
        if not isinstance(node_id, str):
            continue
        tag = str(node.get("tag", ""))
        if tag in {"document", "html", "head", "#comment", "#doctype", "script", "style", "link", "meta", "title"}:
            continue
        layout = layouts.get(node_id)
        if layout is None:
            raise GenerationError(f"视觉 DOM 节点缺少浏览器布局证据：{node_id} ({tag})")
        if layout.get("visible") is False:
            continue
        style = _style(layout)
        bounds = _relative_bounds(layout, root_bounds)
        shape = _shape(style)
        background = _strict_color(style.get("backgroundColor"), "background")
        border = _border(style)
        background_image = _background_record(style, manifest_records)
        node_lines: list[str] = []
        standalone_border = border if background_image is None and tag != "img" else None
        if background or standalone_border:
            node_lines.extend(
                [
                    f"        // {node_id}: {tag} 背景/边框",
                    f"        Box(modifier = {_modifier(bounds, style, clip_shape=shape, background=background, border=standalone_border)})",
                ]
            )
            counters["styledNodeCount"] += 1
        if background_image is not None:
            node_lines.append(f"        // {node_id}: CSS background-image")
            node_lines.extend(
                _render_image(
                    background_image,
                    bounds,
                    style,
                    None,
                    _content_scale(style.get("backgroundSize")),
                    shape,
                    "        ",
                    border=border if tag != "img" else None,
                    alignment=_image_alignment(style.get("backgroundPosition")),
                )
            )
            counters["backgroundImageCount"] += 1
            counters["styledNodeCount"] += 1
        if tag == "img":
            record = image_records.get(node_id)
            if record is None:
                raise GenerationError(f"可见图片节点没有确定的 images.json 映射：{node_id}")
            node_lines.append(f"        // {node_id}: img")
            node_lines.extend(
                _render_image(
                    record,
                    bounds,
                    style,
                    node.get("attributes", {}).get("alt") or None,
                    _content_scale(style.get("objectFit")),
                    shape,
                    "        ",
                    border=border,
                    alignment=_image_alignment(style.get("objectPosition")),
                )
            )
            counters["imageCount"] += 1
            counters["styledNodeCount"] += 1
        else:
            direct_text = " ".join(str(node.get("directText", "")).split())
            if direct_text and not text_runs:
                node_lines.append(f"        // {node_id}: direct text")
                node_lines.extend(_render_text(direct_text, bounds, style, "        "))
                counters["textCount"] += 1
                counters["styledNodeCount"] += 1
        if node_lines:
            paint_order = _number(layout.get("paintOrder"))
            events.append((paint_order if paint_order is not None else float(dom_index * 2), sequence, node_lines))
            sequence += 1
    for index, run in enumerate(text_runs):
        if run["hostNodeId"] not in allowed_node_ids:
            continue
        style = _style(run)
        raw_text = str(run["text"])
        text = raw_text if str(style.get("whiteSpace", "")).startswith("pre") else " ".join(raw_text.split())
        if not text:
            continue
        run_lines = [f"        // {run['hostNodeId']}: browser text run {index}"]
        run_lines.extend(_render_text(text, _relative_bounds(run, root_bounds), style, "        "))
        paint_order = _number(run.get("paintOrder"))
        events.append(
            (
                paint_order if paint_order is not None else float(len(dom_nodes) * 2 + index),
                sequence,
                run_lines,
            )
        )
        sequence += 1
        counters["textCount"] += 1
        counters["styledNodeCount"] += 1
    lines = [line for _, _, event_lines in sorted(events) for line in event_lines]
    return lines, counters


def _visible_pseudo_elements(design: dict[str, Any]) -> list[dict[str, Any]]:
    source = design.get("pseudoElements", design.get("伪元素", []))
    if not isinstance(source, list):
        return []
    return [item for item in source if isinstance(item, dict) and item.get("visible") is not False]


def _text_runs(design: dict[str, Any]) -> list[dict[str, Any]]:
    source = design.get("textRuns", design.get("文本片段", []))
    if not isinstance(source, list):
        return []
    return [
        item
        for item in source
        if isinstance(item, dict)
        and isinstance(item.get("hostNodeId"), str)
        and isinstance(item.get("text"), str)
        and item.get("visible") is not False
    ]


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
    pseudo_elements = _visible_pseudo_elements(design)
    if pseudo_elements:
        ids = [str(item.get("nodeId") or item.get("hostNodeId")) for item in pseudo_elements]
        raise GenerationError(f"检测到尚无可靠边界的可见伪元素，拒绝静默丢失：{ids}")
    layouts = _layout_by_id(design)
    root = _find_generation_root(nodes, layouts, design)
    by_id = {node.get("nodeId"): node for node in nodes if isinstance(node, dict)}
    text_runs = _text_runs(design)
    _validate_flattening_safety(root, by_id, layouts, text_runs)
    root_layout = layouts.get(str(root.get("nodeId")), {})
    root_bounds = _root_bounds(design, root_layout)
    canvas_width, canvas_height = _canvas_size(design, root_bounds)
    manifest_records = _manifest_records(images_path)
    image_records = _image_records(dom, design, manifest_records)
    visual_lines, counters = _render_visual_tree(
        root,
        by_id,
        layouts,
        image_records,
        manifest_records,
        root_bounds,
        text_runs,
    )
    if not visual_lines:
        raise GenerationError(f"DOM 根节点没有可生成的可见内容：{root.get('nodeId')}")
    uses_images = counters["imageCount"] > 0 or counters["backgroundImageCount"] > 0
    if uses_images and not resource_package:
        raise GenerationError("页面使用了 Android 图片资源，但无法从目标模块确定 R 资源包")

    page_name = _safe_identifier(output_path.stem)
    semantic_container = _container_name(root_layout, len(root.get("childrenIds", [])))
    imports = [
        "import android.annotation.SuppressLint",
        "import androidx.compose.foundation.Image",
        "import androidx.compose.foundation.background",
        "import androidx.compose.foundation.border",
        "import androidx.compose.foundation.layout.Box",
        "import androidx.compose.foundation.layout.BoxWithConstraints",
        "import androidx.compose.foundation.layout.Column",
        "import androidx.compose.foundation.layout.Row",
        "import androidx.compose.foundation.layout.fillMaxSize",
        "import androidx.compose.foundation.layout.offset",
        "import androidx.compose.foundation.layout.size",
        "import androidx.compose.foundation.shape.AbsoluteRoundedCornerShape",
        "import androidx.compose.foundation.shape.RoundedCornerShape",
        "import androidx.compose.material3.Text",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.ui.Alignment",
        "import androidx.compose.ui.BiasAlignment",
        "import androidx.compose.ui.Modifier",
        "import androidx.compose.ui.draw.alpha",
        "import androidx.compose.ui.draw.clip",
        "import androidx.compose.ui.graphics.Color",
        "import androidx.compose.ui.layout.ContentScale",
        "import androidx.compose.ui.res.painterResource",
        "import androidx.compose.ui.text.font.FontFamily",
        "import androidx.compose.ui.text.font.FontStyle",
        "import androidx.compose.ui.text.font.FontWeight",
        "import androidx.compose.ui.text.style.TextAlign",
        "import androidx.compose.ui.text.style.TextDecoration",
        "import androidx.compose.ui.text.style.TextOverflow",
        "import androidx.compose.ui.unit.Dp",
        "import androidx.compose.ui.unit.TextUnit",
        "import androidx.compose.ui.unit.dp",
        "import androidx.compose.ui.unit.sp",
        "import kotlin.math.min",
    ]
    if uses_images:
        imports.insert(-1, f"import {_kotlin_qualified_name(resource_package)}.R")
    body = [
        f"package {_kotlin_qualified_name(package_name)}",
        "",
        *imports,
        "",
        f"private const val DESIGN_WIDTH = {_format_float(canvas_width)}",
        f"private const val DESIGN_HEIGHT = {_format_float(canvas_height)}",
        "",
        f"/** 由 DOM IR 与浏览器最终边界自动生成；输入：{dom_path.name}。 */",
        '@SuppressLint("UnusedBoxWithConstraintsScope")',
        "@Composable",
        f"fun {page_name}(modifier: Modifier = Modifier) {{",
        "    BoxWithConstraints(modifier = modifier.fillMaxSize()) {",
        "        val scaleX = maxWidth.value / DESIGN_WIDTH",
        "        val scaleY = maxHeight.value / DESIGN_HEIGHT",
        "        val fontScale = min(scaleX, scaleY)",
        f"        {semantic_container}(modifier = Modifier.fillMaxSize()) {{",
        "            Box(modifier = Modifier.fillMaxSize()) {",
        *visual_lines,
        "            }",
        "        }",
        "    }",
        "}",
        "",
        "private fun designDp(value: Float, scale: Float): Dp = (value * scale).dp",
        "",
        "private fun designSp(value: Float, scale: Float): TextUnit = (value * scale).sp",
        "",
    ]
    source = "\n".join(body)
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    changed = True
    try:
        changed = output_path.read_text(encoding="utf-8") != source
    except OSError:
        pass
    if changed:
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(source, encoding="utf-8")
        os.replace(temporary, output_path)
    compose_md5 = hashlib.md5(source.encode("utf-8")).hexdigest()
    return {
        "outputPath": str(output_path),
        "nodeCount": len(nodes),
        "rootNodeId": root["nodeId"],
        "sourceDom": str(dom_path),
        "composeMd5": compose_md5,
        "changed": changed,
        **counters,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="从已存储 DOM IR 和浏览器最终事实生成 Compose 源码")
    parser.add_argument("--dom", required=True, type=Path)
    parser.add_argument("--design", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--images", type=Path)
    parser.add_argument("--resource-package")
    args = parser.parse_args()
    print(
        json.dumps(
            generate_compose(args.dom, args.design, args.output, args.package, args.images, args.resource_package),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
