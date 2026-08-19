#!/usr/bin/env python3
"""code-lanhu-compose 的固定编排器。

脚本负责可确定、可重放的流程、DOM IR、Compose 首稿和状态；大模型只在
项目适配、异常确认和视觉修正阶段通过白名单决策契约参与。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote, urlparse

from generate_compose import GenerationError, generate_compose
from import_zip_images import EXTRACTION_MARKER_NAME
from import_zip_images import artifact_directory as image_artifact_directory
from import_zip_images import normalized_zip_path
from import_zip_images import safe_entries as validated_zip_entries
from import_zip_images import safe_extraction_target
from parse_html_dom import parse_html_archive


PHASES = (
    "created",
    "inspected",
    "validated",
    "preflight",
    "assets_imported",
    "generated",
    "compiled",
    "installed",
    "screenshot",
    "diffed",
    "completed",
)
ALLOWED_ACTIONS = {"ask_user", "apply_patch", "continue", "stop"}
SAFE_TASK = re.compile(r"^:(?:[A-Za-z0-9_.-]+:)*[A-Za-z0-9_.-]+$")
GRADLE_COMPILE_TASK = re.compile(
    r"^\s*((?::?[A-Za-z0-9_.-]+:)*compile[A-Za-z0-9_.-]*Kotlin)\s+-"
)
SAFE_SERIAL = re.compile(r"^[A-Za-z0-9_.:-]+$")
DESIGN_SERVER_PROCESSES: dict[int, subprocess.Popen[Any]] = {}
MD5_CACHE: dict[tuple[str, int, int, int, int], str] = {}
DESIGN_DOCUMENT_NAME = "设计解析.json"
DESIGN_DOCUMENT_VERSION = 5
PIPELINE_STATE_VERSION = 2
DOM_DOCUMENT_NAME = "dom.json"
CHROME_EXECUTABLE = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DOM_NODE_ID_ATTRIBUTE = "data-code-lanhu-node-id"


class PipelineError(RuntimeError):
    """可直接报告给用户的流程错误。"""


class UserInputRequired(PipelineError):
    """证据不足，需要用户决定而不是猜测。"""


class _StartTagLocator(HTMLParser):
    """记录源码起始标签的原始位置，不重新序列化 HTML。"""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = [0]
        self.line_starts.extend(index + 1 for index, character in enumerate(source) if character == "\n")
        self.tags: list[tuple[int, str, str]] = []

    def _record(self, tag: str) -> None:
        line, column = self.getpos()
        raw = self.get_starttag_text()
        if not raw:
            raise PipelineError(f"无法取得 HTML 起始标签原文：{tag}")
        self.tags.append((self.line_starts[line - 1] + column, tag.lower(), raw))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag)


def instrument_html_node_ids(source: str, dom: dict[str, Any]) -> str:
    """给原始起始标签注入稳定 nodeId，避免浏览器规范化 DOM 后按下标错绑。"""
    if DOM_NODE_ID_ATTRIBUTE in source:
        raise PipelineError(f"设计 HTML 已包含保留属性 {DOM_NODE_ID_ATTRIBUTE}，无法安全注入")
    expected = [
        (str(node["nodeId"]), str(node["tag"]).lower())
        for node in dom.get("nodes", [])
        if isinstance(node, dict)
        and isinstance(node.get("nodeId"), str)
        and str(node.get("tag", "")) not in {"document", "#comment", "#doctype"}
    ]
    locator = _StartTagLocator(source)
    locator.feed(source)
    locator.close()
    if len(locator.tags) != len(expected):
        raise PipelineError(f"DOM nodeId 注入数量不一致：源码 {len(locator.tags)}，DOM IR {len(expected)}")
    insertions: list[tuple[int, str]] = []
    for (offset, actual_tag, raw), (node_id, expected_tag) in zip(locator.tags, expected, strict=True):
        if actual_tag != expected_tag:
            raise PipelineError(f"DOM nodeId 注入标签错位：{node_id} 期望 {expected_tag}，实际 {actual_tag}")
        closing = re.search(r"\s*/?>\s*$", raw)
        if closing is None:
            raise PipelineError(f"HTML 起始标签没有可识别的闭合位置：{raw[:80]}")
        insertions.append((offset + closing.start(), f' {DOM_NODE_ID_ATTRIBUTE}="{node_id}"'))
    result = source
    for offset, attribute in reversed(insertions):
        result = result[:offset] + attribute + result[offset:]
    return result


def ensure_utf8_html(source: str) -> str:
    """让本地 http.server 的 HTML 明确以 UTF-8 解码，避免中文进入浏览器后乱码。"""
    charset = re.search(r"<meta\b[^>]*\bcharset\s*=\s*[\"']?\s*([^\s\"'/>;]+)", source, re.I)
    if charset is not None:
        encoding = charset.group(1).replace("-", "").lower()
        if encoding != "utf8":
            raise PipelineError(f"设计 HTML 声明了暂不支持的字符集：{charset.group(1)}")
        return source
    head = re.search(r"<head\b[^>]*>", source, re.I)
    if head is not None:
        return source[: head.end()] + '<meta charset="utf-8">' + source[head.end() :]
    html = re.search(r"<html\b[^>]*>", source, re.I)
    if html is not None:
        return source[: html.end()] + '<head><meta charset="utf-8"></head>' + source[html.end() :]
    return '<meta charset="utf-8">' + source


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def md5_file(path: Path) -> str:
    path = path.expanduser().resolve()
    before = path.stat()
    key = (str(path), before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    cached = MD5_CACHE.get(key)
    if cached is not None:
        return cached
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        return md5_file(path)
    value = digest.hexdigest()
    MD5_CACHE[key] = value
    if len(MD5_CACHE) > 64:
        MD5_CACHE.pop(next(iter(MD5_CACHE)))
    return value


def safe_zip_name(name: str) -> str:
    try:
        path = normalized_zip_path(name)
    except ValueError as error:
        raise PipelineError(str(error)) from error
    if path.is_absolute() or ".." in path.parts:
        raise PipelineError(f"ZIP 包含不安全路径：{name}")
    return path.as_posix()


def zip_entries(archive: Path) -> list[zipfile.ZipInfo]:
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise PipelineError(f"ZIP 文件不存在或扩展名不正确：{archive}")
    with zipfile.ZipFile(archive) as zipped:
        try:
            checked = validated_zip_entries(zipped)
        except ValueError as error:
            raise PipelineError(str(error)) from error
        entries = []
        for info in checked:
            safe_zip_name(info.filename)
            if info.is_dir():
                continue
            entries.append(info)
        return entries


def _entry_path(name: str) -> str:
    return safe_zip_name(name).lower()


def _referenced_css(html: str, names: Iterable[str], html_name: str) -> list[str]:
    available = {safe_zip_name(name): safe_zip_name(name) for name in names}
    links = re.findall(r"(?:href|src)=[\"']([^\"']+\.css(?:\?[^\"']*)?)[\"']", html, re.I)
    selected: list[str] = []
    for link in links:
        clean = link.split("?", 1)[0]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(html_name), clean))
        candidates = [candidate for candidate in available if candidate == resolved]
        if len(candidates) != 1:
            raise PipelineError(f"HTML 引用的 CSS 无法唯一解析：{link} -> {resolved}")
        if candidates[0] not in selected:
            selected.append(candidates[0])
    if not selected:
        raise UserInputRequired("HTML 未声明 CSS 引用，请确认要采用哪个 CSS 文件")
    return selected


def artifact_dir(archive: Path, project_root: Path, source_sha: str) -> Path:
    return image_artifact_directory(archive, source_sha, project_root)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def new_state(source_sha: str, compose_file: str | None) -> dict[str, Any]:
    return {
        "version": PIPELINE_STATE_VERSION,
        "sourceMd5": source_sha,
        "composeFile": compose_file,
        "phase": "created",
        "attempts": {"compile": 0, "repair": 0},
        "history": [],
    }


def transition(state: dict[str, Any], phase: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    if phase not in PHASES:
        raise PipelineError(f"未知流程阶段：{phase}")
    current_index = PHASES.index(state.get("phase", "created"))
    next_index = PHASES.index(phase)
    # Compose 源码发生变化后，允许从已编译状态回退到 generated，重新执行同一编译任务。
    # 这是可重复运行固定管线所必需的状态迁移，不代表设计解析或资源阶段需要重做。
    can_recompile = state.get("phase") == "compiled" and phase == "generated"
    if next_index != current_index + 1 and next_index != current_index and not can_recompile:
        raise PipelineError(f"阶段顺序不允许：{state.get('phase')} -> {phase}")
    state["phase"] = phase
    state.setdefault("history", []).append({"phase": phase, "at": utc_now(), "detail": detail or {}})
    return state


def _write_state(artifact: Path, state: dict[str, Any]) -> None:
    atomic_json(artifact / "pipeline.json", state)


def _load_cached_inspection(artifact: Path, source_sha: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """读取同一 ZIP 的已验证检查结果，避免重置后续阶段。"""
    source_path = artifact / "source.json"
    state_path = artifact / "pipeline.json"
    if not source_path.is_file() or not state_path.is_file():
        return None
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        source.get("sourceMd5") != source_sha
        or state.get("sourceMd5") != source_sha
        or state.get("version") != PIPELINE_STATE_VERSION
    ):
        return None
    if state.get("phase") not in PHASES:
        return None
    return source, state


def select_entry_html(archive: Path, project_root: Path, html_path: str) -> dict[str, Any]:
    """从当前 ZIP 的真实 HTML 候选中登记入口，解除 inspect 暂停。"""
    archive = archive.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    source_sha = md5_file(archive)
    candidates = sorted(
        safe_zip_name(info.filename)
        for info in zip_entries(archive)
        if _entry_path(info.filename).endswith((".html", ".htm"))
    )
    selected = safe_zip_name(html_path)
    if selected not in candidates:
        raise PipelineError(f"HTML 入口不属于当前 ZIP 候选：{selected}，候选：{candidates}")
    artifact = artifact_dir(archive, project_root, source_sha)
    atomic_json(
        artifact / "entry-selection.json",
        {"version": 1, "sourceMd5": source_sha, "html": selected, "selectedAt": utc_now()},
    )
    (artifact / "needs-user-input.json").unlink(missing_ok=True)
    return {"artifactPath": str(artifact), "sourceMd5": source_sha, "html": selected, "candidates": candidates}


def _reject_artifact_identity_collision(artifact: Path, source_sha: str) -> None:
    """短目录名只用于可读性；完整 MD5 不同的 artifact 绝不能复用或覆盖。"""
    for name in ("source.json", "pipeline.json"):
        identity_path = artifact / name
        if not identity_path.is_file():
            continue
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"已有 artifact 身份文件损坏，拒绝覆盖：{identity_path}") from error
        existing_sha = identity.get("sourceMd5") if isinstance(identity, dict) else None
        if isinstance(existing_sha, str) and existing_sha != source_sha:
            raise PipelineError(
                f"检测到 MD5 前缀碰撞，拒绝复用或覆盖 artifact：{existing_sha} != {source_sha}"
            )


def inspect_archive(archive: Path, project_root: Path, compose_file: Path | None = None) -> dict[str, Any]:
    archive = archive.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    source_sha = md5_file(archive)
    artifact = artifact_dir(archive, project_root, source_sha)
    _reject_artifact_identity_collision(artifact, source_sha)
    cached = _load_cached_inspection(artifact, source_sha)
    if cached is not None:
        source_manifest, state = cached
        requested_compose = str(compose_file.expanduser().resolve()) if compose_file is not None else None
        existing_compose = state.get("composeFile")
        if requested_compose and isinstance(existing_compose, str) and existing_compose != requested_compose:
            previous = state
            state = new_state(source_sha, requested_compose)
            state["targetHistory"] = [
                *previous.get("targetHistory", []),
                {
                    "composeFile": existing_compose,
                    "phase": previous.get("phase"),
                    "preflightTask": previous.get("preflightTask"),
                    "reboundAt": utc_now(),
                },
            ]
            if isinstance(previous.get("designScreenshot"), dict):
                state["designScreenshot"] = previous["designScreenshot"]
            transition(
                state,
                "inspected",
                {
                    "html": source_manifest["html"],
                    "cssCount": len(source_manifest.get("css", [])),
                    "targetChangedFrom": existing_compose,
                    "previousPhase": previous.get("phase"),
                },
            )
            _write_state(artifact, state)
        dom_path = artifact / DOM_DOCUMENT_NAME
        if not dom_path.is_file() or "dom" not in source_manifest:
            if dom_path.is_file():
                try:
                    dom = json.loads(dom_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    dom = parse_html_archive(archive, source_manifest["html"]["path"])
            else:
                dom = parse_html_archive(archive, source_manifest["html"]["path"])
            dom["sourceMd5"] = source_sha
            atomic_json(dom_path, dom)
            source_manifest["dom"] = {"path": dom_path.name, "nodeCount": len(dom["nodes"]), "resourceCount": len(dom["resources"])}
            atomic_json(artifact / "source.json", source_manifest)
        return {**source_manifest, "phase": state["phase"], "cacheHit": True}

    entries = zip_entries(archive)
    html_entries = [info for info in entries if _entry_path(info.filename).endswith((".html", ".htm"))]
    if not html_entries:
        raise PipelineError("ZIP 中没有 HTML 入口文件")
    if len(html_entries) > 1:
        candidates = [safe_zip_name(info.filename) for info in html_entries]
        selection_path = artifact / "entry-selection.json"
        try:
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            selection = None
        selected_html = selection.get("html") if isinstance(selection, dict) and selection.get("sourceMd5") == source_sha else None
        matching = [info for info in html_entries if safe_zip_name(info.filename) == selected_html]
        if len(matching) != 1:
            raise UserInputRequired(f"ZIP 包含多个 HTML 入口候选，请执行 select-entry-html 明确选择：{candidates}")
        html_info = matching[0]
    else:
        html_info = html_entries[0]
    artifact.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        html_text = zipped.read(html_info).decode("utf-8", errors="replace")
    names = [safe_zip_name(info.filename) for info in entries]
    css_files = _referenced_css(html_text, names, safe_zip_name(html_info.filename))
    dom = parse_html_archive(archive, safe_zip_name(html_info.filename))
    dom["sourceMd5"] = source_sha
    dom_path = artifact / DOM_DOCUMENT_NAME
    atomic_json(dom_path, dom)
    source_manifest = {
        "version": 1,
        "sourceName": archive.name,
        "sourcePath": str(archive),
        "sourceMd5": source_sha,
        "artifactPath": str(artifact),
        "html": {"path": safe_zip_name(html_info.filename)},
        "css": [{"path": path} for path in css_files],
        "dom": {"path": dom_path.name, "nodeCount": len(dom["nodes"]), "resourceCount": len(dom["resources"])},
        "assets": [{"path": name} for name in names if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"))],
        "createdAt": utc_now(),
    }
    atomic_json(artifact / "source.json", source_manifest)
    state = new_state(source_sha, str(compose_file.resolve()) if compose_file else None)
    transition(state, "inspected", {"html": source_manifest["html"], "cssCount": len(css_files)})
    _write_state(artifact, state)
    return {**source_manifest, "phase": state["phase"], "cacheHit": False}


def load_source(archive: Path, project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    source_sha = md5_file(archive.expanduser().resolve())
    artifact = artifact_dir(archive.expanduser().resolve(), project_root.expanduser().resolve(), source_sha)
    source_path = artifact / "source.json"
    state_path = artifact / "pipeline.json"
    if not source_path.is_file() or not state_path.is_file():
        raise PipelineError("尚未 inspect，缺少 source.json 或 pipeline.json")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if source.get("sourceMd5") != source_sha or state.get("sourceMd5") != source_sha:
        raise PipelineError("输入 ZIP 已变化，不能复用旧状态；请重新 inspect")
    if state.get("version") != PIPELINE_STATE_VERSION:
        raise PipelineError("pipeline.json 状态版本已过期，请重新执行 inspect/run-fixed 迁移证据")
    return artifact, source, state


def _compose_call_arguments(source: str, open_index: int) -> tuple[str, int]:
    """读取 Compose 函数调用参数，支持 padding 内部的 dp(...) 嵌套调用。"""
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(open_index, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"\"", "'"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return source[open_index + 1 : index], index
    raise PipelineError("Compose 中存在未闭合的 padding(...) 调用")


def validate_compose_source(compose_path: Path) -> None:
    """在 Gradle/运行前拒绝 Compose padding 中的负值，避免运行时 PaddingElement 崩溃。"""
    try:
        source = compose_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PipelineError(f"无法读取 Compose 文件：{compose_path}") from error

    for match in re.finditer(r"\bpadding\s*\(", source):
        arguments, _ = _compose_call_arguments(source, match.end() - 1)
        negative = re.search(r"(?<![\w.])-\s*(?:[A-Za-z_][\w.]*|\d+(?:\.\d+)?(?:[fFdD])?)", arguments)
        if negative is None:
            continue
        absolute_index = match.end() - 1 + 1 + negative.start()
        line = source.count("\n", 0, absolute_index) + 1
        preceding_argument = arguments[: negative.start()]
        parameter_match = re.search(r"(?:^|,)\s*([A-Za-z_]\w*)\s*=\s*[^,]*$", preceding_argument, re.DOTALL)
        parameter = parameter_match.group(1) if parameter_match else "未命名参数"
        axis = "y" if parameter in {"top", "bottom"} else "x" if parameter in {"start", "end"} else "x/y"
        raise PipelineError(
            f"Compose 文件 {compose_path}:{line} 的 padding({parameter}) 包含负值；"
            f"Compose padding 参数必须非负，请将该设计位移改为 Modifier.offset({axis} = ...) "
            "或使用父级布局表达，保留原有视觉位移"
        )


def design_server_state_path(artifact: Path) -> Path:
    """返回本次 ZIP 专属的本地设计稿服务状态文件。"""
    return artifact / "design-server.json"


def design_server_source_state_path(artifact: Path) -> Path:
    """返回设计静态服务解压缓存的身份记录。"""
    return artifact / "design-server-source.json"


def _load_cached_design(
    artifact: Path,
    source: dict[str, Any],
    viewport: tuple[int, int, float] | None = None,
) -> tuple[dict[str, Any], Path] | None:
    """仅复用与当前 ZIP 匹配且包含公共截图的完整设计产物。"""
    design_path = artifact / DESIGN_DOCUMENT_NAME
    screenshot_path = artifact / "runs" / "设计截图.png"
    try:
        design = json.loads(design_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    root = design.get("设计根节点")
    painted_items = [
        item
        for key in ("节点", "文本片段")
        for item in design.get(key, [])
        if isinstance(item, dict) and item.get("visible") is not False
    ]
    browser = design.get("浏览器环境", {})
    captured_viewport = browser.get("viewport", {}) if isinstance(browser, dict) else {}
    viewport_mismatch = viewport is not None and (
        captured_viewport.get("width") != viewport[0]
        or captured_viewport.get("height") != viewport[1]
        or browser.get("deviceScaleFactor") != viewport[2]
    )
    if (
        design.get("版本") != DESIGN_DOCUMENT_VERSION
        or design.get("sourceMd5") != source["sourceMd5"]
        or not isinstance(root, dict)
        or not isinstance(root.get("选择器"), str)
        or not root["选择器"]
        or not screenshot_path.is_file()
        or design.get("设计截图Md5") != md5_file(screenshot_path)
        or viewport_mismatch
        or any(isinstance(item.get("paintOrder"), bool) or not isinstance(item.get("paintOrder"), int) for item in painted_items)
    ):
        return None
    try:
        validate_png_evidence(screenshot_path)
    except PipelineError:
        return None
    return design, screenshot_path


def is_allowed_design_request(url: str, server_url: str) -> bool:
    """设计采集只允许本地静态服务与内嵌资源，保证 ZIP 可离线重放。"""
    parsed = urlparse(url)
    if parsed.scheme in {"data", "blob", "about"}:
        return True
    server = urlparse(server_url)
    return (
        parsed.scheme == server.scheme
        and parsed.hostname == server.hostname
        and parsed.port == server.port
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )


def browser_paint_orders(snapshot: dict[str, Any]) -> dict[str, int]:
    """把 Chrome DOMSnapshot 的真实绘制序号绑定到稳定节点/文本片段 ID。"""
    documents = snapshot.get("documents")
    strings = snapshot.get("strings")
    if not isinstance(documents, list) or not documents or not isinstance(strings, list):
        raise PipelineError("Chrome DOMSnapshot 缺少 documents/strings")
    document = documents[0]
    nodes = document.get("nodes", {})
    layout = document.get("layout", {})
    parent_indices = nodes.get("parentIndex", [])
    node_names = nodes.get("nodeName", [])
    attributes = nodes.get("attributes", [])
    layout_indices = layout.get("nodeIndex", [])
    paint_orders = layout.get("paintOrders", [])
    if not all(isinstance(value, list) for value in (parent_indices, node_names, attributes, layout_indices, paint_orders)):
        raise PipelineError("Chrome DOMSnapshot 结构无效")
    if len(layout_indices) != len(paint_orders):
        raise PipelineError("Chrome DOMSnapshot paintOrders 数量不一致")

    stable_ids: dict[int, str] = {}
    children: dict[int, list[int]] = {}
    for node_index, parent_index in enumerate(parent_indices):
        if isinstance(parent_index, int) and parent_index >= 0:
            children.setdefault(parent_index, []).append(node_index)
        raw_attributes = attributes[node_index] if node_index < len(attributes) else []
        if not isinstance(raw_attributes, list):
            continue
        decoded = [strings[index] for index in raw_attributes if isinstance(index, int) and 0 <= index < len(strings)]
        for offset in range(0, len(decoded) - 1, 2):
            if decoded[offset] == DOM_NODE_ID_ATTRIBUTE:
                stable_ids[node_index] = str(decoded[offset + 1])
                break

    result: dict[str, int] = {}
    for layout_index, node_index in enumerate(layout_indices):
        if not isinstance(node_index, int) or not 0 <= node_index < len(node_names):
            continue
        order = paint_orders[layout_index]
        if isinstance(order, bool) or not isinstance(order, int):
            raise PipelineError("Chrome DOMSnapshot 包含非整数 paintOrder")
        key = stable_ids.get(node_index)
        name_index = node_names[node_index]
        node_name = strings[name_index] if isinstance(name_index, int) and 0 <= name_index < len(strings) else ""
        if key is None and node_name == "#text":
            parent_index = parent_indices[node_index]
            parent_id = stable_ids.get(parent_index)
            if parent_id is not None:
                child_index = children.get(parent_index, []).index(node_index)
                key = f"{parent_id}:text:{child_index}"
        if key is not None:
            result[key] = max(order, result.get(key, order))
    return result


def is_pid_alive(pid: int) -> bool:
    """判断 PID 是否仍然存在，不把权限错误误判为服务已停止。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe_extract_archive(archive: Path, destination: Path) -> None:
    """安全解压 ZIP，供仅本机的静态服务读取。"""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for info in zip_entries(archive):
            relative = safe_zip_name(info.filename)
            try:
                target = safe_extraction_target(destination, PurePosixPath(relative))
            except ValueError as error:
                raise PipelineError(str(error)) from error
            if root not in target.resolve().parents:
                raise PipelineError(f"ZIP 解压路径越界：{relative}")
            with zipped.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _has_complete_design_server_source(archive: Path, destination: Path, source_sha: str) -> bool:
    """仅在来源一致且所有 ZIP 文件均完整落盘时复用设计服务解压目录。"""
    marker = design_server_source_state_path(destination.parent)
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if cached.get("sourceMd5") != source_sha:
        return False
    root = destination.resolve()
    for info in zip_entries(archive):
        if info.is_dir():
            continue
        candidate = root / safe_zip_name(info.filename)
        target = candidate.resolve()
        if root not in target.parents or candidate.is_symlink() or not target.is_file():
            return False
        if target.stat().st_size != info.file_size:
            return False
    return True


def _wait_for_loopback_server(port: int, process: subprocess.Popen[bytes]) -> None:
    """确认 http.server 已能接受本机连接，避免浏览器读到尚未启动的页面。"""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PipelineError(f"本地静态服务启动失败，退出码：{process.returncode}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.1)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise PipelineError("本地静态服务在 3 秒内未就绪")


def _server_command_matches(pid: int, serving_root: Path) -> bool:
    """macOS 上只终止由本脚本启动且仍指向该解压目录的 http.server。"""
    inspected = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        text=True,
        capture_output=True,
        check=False,
    )
    command = inspected.stdout.strip()
    return (
        inspected.returncode == 0
        and "http.server" in command
        and "--bind 127.0.0.1" in command
        and str(serving_root) in command
    )


def stop_design_server(archive: Path, project_root: Path) -> dict[str, Any]:
    """停止本次 ZIP 启动的静态服务，不触碰其他本地进程。"""
    artifact, _, _ = load_source(archive, project_root)
    state_path = design_server_state_path(artifact)
    if not state_path.is_file():
        return {"artifactPath": str(artifact), "status": "not_running"}
    try:
        server_state = json.loads(state_path.read_text(encoding="utf-8"))
        pid = int(server_state["pid"])
        serving_root = Path(server_state["servingRoot"]).resolve()
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise PipelineError(f"静态服务状态文件无效：{state_path}") from error

    if is_pid_alive(pid):
        if not _server_command_matches(pid, serving_root):
            raise PipelineError(f"拒绝终止未验证的进程 PID {pid}；请手动检查：{state_path}")
        process = DESIGN_SERVER_PROCESSES.pop(pid, None)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        else:
            deadline = time.monotonic() + 2
            while is_pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            if is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    state_path.unlink(missing_ok=True)
    return {"artifactPath": str(artifact), "status": "stopped", "pid": pid}


def start_design_server(
    archive: Path,
    project_root: Path,
    port: int = 0,
    viewport_width: int = 1600,
    viewport_height: int = 900,
    dpr: float = 1.0,
) -> dict[str, Any]:
    """启动只监听 127.0.0.1 的设计稿静态服务，并记录可安全回收的 PID。"""
    if not 0 <= port <= 65535:
        raise PipelineError(f"端口必须在 0 到 65535 之间：{port}")
    artifact, source, _ = load_source(archive, project_root)
    state_path = design_server_state_path(artifact)
    if state_path.is_file():
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        previous_pid = int(previous.get("pid", -1))
        if is_pid_alive(previous_pid):
            raise PipelineError(f"设计稿静态服务已在运行（PID {previous_pid}）；请先执行 stop-design-server")
        state_path.unlink()

    cached_design = _load_cached_design(artifact, source, (viewport_width, viewport_height, dpr))
    if cached_design is not None:
        design, screenshot_path = cached_design
        return {
            "artifactPath": str(artifact),
            "designPath": str(artifact / DESIGN_DOCUMENT_NAME),
            "screenshotPath": str(screenshot_path),
            "设计根节点": design["设计根节点"],
            "cacheHit": True,
            "sourceReused": True,
        }

    serving_root = artifact / "design-server-source"
    source_reused = _has_complete_design_server_source(archive, serving_root, source["sourceMd5"])
    if not source_reused:
        if serving_root.exists():
            shutil.rmtree(serving_root)
        _safe_extract_archive(archive.expanduser().resolve(), serving_root)
        atomic_json(
            design_server_source_state_path(artifact),
            {"version": 1, "sourceMd5": source["sourceMd5"], "createdAt": utc_now()},
        )
    atomic_json(
        serving_root / EXTRACTION_MARKER_NAME,
        {"version": 1, "sourceMd5": source["sourceMd5"]},
    )
    html_path = serving_root / source["html"]["path"]
    if not html_path.is_file():
        raise PipelineError(f"解压后找不到设计入口 HTML：{html_path}")
    dom_path = artifact / DOM_DOCUMENT_NAME
    try:
        dom = json.loads(dom_path.read_text(encoding="utf-8"))
        html_source = html_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as error:
        raise PipelineError(f"无法为设计页注入稳定 DOM nodeId：{html_path}") from error
    instrumented_path = html_path.with_name(f".code-lanhu-{html_path.name}")
    instrumented_source = ensure_utf8_html(instrument_html_node_ids(html_source, dom))
    if not instrumented_path.is_file() or instrumented_path.read_text(encoding="utf-8") != instrumented_source:
        temporary = instrumented_path.with_suffix(instrumented_path.suffix + ".tmp")
        temporary.write_text(instrumented_source, encoding="utf-8")
        os.replace(temporary, instrumented_path)
    instrumented_relative = instrumented_path.relative_to(serving_root).as_posix()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", port))
    selected_port = listener.getsockname()[1]
    listener.close()
    command = [sys.executable, "-m", "http.server", str(selected_port), "--bind", "127.0.0.1", "--directory", str(serving_root)]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    DESIGN_SERVER_PROCESSES[process.pid] = process
    try:
        _wait_for_loopback_server(selected_port, process)
    except Exception:
        if is_pid_alive(process.pid):
            os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
        DESIGN_SERVER_PROCESSES.pop(process.pid, None)
        raise
    state = {
        "version": 1,
        "pid": process.pid,
        "port": selected_port,
        "url": f"http://127.0.0.1:{selected_port}/{quote(instrumented_relative, safe='/')}",
        "servingRoot": str(serving_root.resolve()),
        "sourceMd5": source["sourceMd5"],
        "startedAt": utc_now(),
    }
    atomic_json(state_path, state)
    return {"artifactPath": str(artifact), "statePath": str(state_path), "cacheHit": False, "sourceReused": source_reused, **state}


def capture_rendered_design(
    archive: Path,
    project_root: Path,
    viewport_width: int = 1600,
    viewport_height: int = 900,
    dpr: float = 1.0,
) -> dict[str, Any]:
    """读取本机浏览器最终渲染结果，并原子写入可追溯的设计解析文件。"""
    artifact, source, _ = load_source(archive, project_root)
    if not 1 <= viewport_width <= 10000 or not 1 <= viewport_height <= 10000 or not 0.5 <= dpr <= 4:
        raise PipelineError(f"浏览器 viewport/DPR 无效：{viewport_width}×{viewport_height} @ {dpr}")
    cached_design = _load_cached_design(artifact, source, (viewport_width, viewport_height, dpr))
    if cached_design is not None:
        design, screenshot_path = cached_design
        return {
            "artifactPath": str(artifact),
            "designPath": str(artifact / DESIGN_DOCUMENT_NAME),
            "screenshotPath": str(screenshot_path),
            "设计根节点": design["设计根节点"],
            "cacheHit": True,
        }
    state_path = design_server_state_path(artifact)
    if not state_path.is_file():
        raise PipelineError("尚未启动设计稿静态服务，请先执行 start-design-server")
    try:
        server = json.loads(state_path.read_text(encoding="utf-8"))
        if server.get("sourceMd5") != source["sourceMd5"]:
            raise PipelineError("设计稿静态服务与当前 ZIP 不匹配")
        if not is_pid_alive(int(server["pid"])):
            raise PipelineError("设计稿静态服务已停止，请重新执行 start-design-server")
        url = str(server["url"])
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise PipelineError(f"静态服务状态文件无效：{state_path}") from error

    if not CHROME_EXECUTABLE.is_file():
        raise PipelineError(f"未找到本机 Google Chrome，无法采集最终布局：{CHROME_EXECUTABLE}")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise PipelineError("缺少 Playwright，无法采集浏览器最终布局") from error

    dom_path = artifact / DOM_DOCUMENT_NAME
    try:
        dom = json.loads(dom_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError(f"缺少完整 DOM IR，无法采集设计：{dom_path}") from error
    expected_nodes = {
        str(node["nodeId"]): str(node["tag"]).lower()
        for node in dom.get("nodes", [])
        if isinstance(node, dict)
        and isinstance(node.get("nodeId"), str)
        and not str(node.get("tag", "")).startswith("#")
        and node.get("tag") != "document"
    }
    script = """
        (expectedNodes) => {
          const body = document.body;
          const visualRootCandidates = body ? Array.from(body.children).filter((node) => {
            if (['script', 'noscript', 'template'].includes(node.tagName.toLowerCase())) return false;
            const style = getComputedStyle(node);
            const bounds = node.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity || 1) > 0 && bounds.width > 0 && bounds.height > 0;
          }) : [];
          const root = visualRootCandidates.length === 1 ? visualRootCandidates[0]
            : visualRootCandidates.length > 1 ? body : null;
          if (!root) return null;
          const nodeId = (node) => node.getAttribute('data-code-lanhu-node-id');
          const rect = (node) => {
            const value = node.getBoundingClientRect();
            return { x: value.x, y: value.y, width: value.width, height: value.height };
          };
          const effectiveOpacity = (node) => {
            let value = 1;
            for (let current = node; current instanceof Element; current = current.parentElement) {
              const style = getComputedStyle(current);
              if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return 0;
              value *= Number(style.opacity || 1);
            }
            return value;
          };
          const visible = (node, style, bounds) =>
            effectiveOpacity(node) > 0 && bounds.width > 0 && bounds.height > 0;
          const styleData = (style) => ({
            display: style.display, flexDirection: style.flexDirection, justifyContent: style.justifyContent,
            alignItems: style.alignItems, alignSelf: style.alignSelf, flexWrap: style.flexWrap,
            flexGrow: style.flexGrow, flexShrink: style.flexShrink, flexBasis: style.flexBasis, order: style.order,
            gridTemplateColumns: style.gridTemplateColumns, gridTemplateRows: style.gridTemplateRows,
            gridColumn: style.gridColumn, gridRow: style.gridRow,
            gap: style.gap, rowGap: style.rowGap, columnGap: style.columnGap,
            padding: style.padding, paddingTop: style.paddingTop, paddingRight: style.paddingRight,
            paddingBottom: style.paddingBottom, paddingLeft: style.paddingLeft,
            margin: style.margin, marginTop: style.marginTop, marginRight: style.marginRight,
            marginBottom: style.marginBottom, marginLeft: style.marginLeft,
            position: style.position, inset: style.inset, top: style.top, right: style.right,
            bottom: style.bottom, left: style.left, width: style.width, height: style.height,
            minWidth: style.minWidth, minHeight: style.minHeight, maxWidth: style.maxWidth, maxHeight: style.maxHeight,
            boxSizing: style.boxSizing, overflow: style.overflow, overflowX: style.overflowX, overflowY: style.overflowY,
            visibility: style.visibility, color: style.color, backgroundColor: style.backgroundColor,
            backgroundImage: style.backgroundImage, backgroundSize: style.backgroundSize,
            backgroundPosition: style.backgroundPosition, backgroundRepeat: style.backgroundRepeat,
            border: style.border, borderWidth: style.borderWidth, borderColor: style.borderColor,
            borderStyle: style.borderStyle, borderTopStyle: style.borderTopStyle,
            borderRightStyle: style.borderRightStyle, borderBottomStyle: style.borderBottomStyle,
            borderLeftStyle: style.borderLeftStyle,
            borderRadius: style.borderRadius, borderTopLeftRadius: style.borderTopLeftRadius,
            borderTopRightRadius: style.borderTopRightRadius, borderBottomRightRadius: style.borderBottomRightRadius,
            borderBottomLeftRadius: style.borderBottomLeftRadius,
            boxShadow: style.boxShadow, opacity: style.opacity, zIndex: style.zIndex, transform: style.transform,
            fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight,
            fontStyle: style.fontStyle, textTransform: style.textTransform,
            lineHeight: style.lineHeight, letterSpacing: style.letterSpacing, textAlign: style.textAlign,
            textDecorationLine: style.textDecorationLine,
            whiteSpace: style.whiteSpace, textOverflow: style.textOverflow, objectFit: style.objectFit,
            objectPosition: style.objectPosition
          });
          const nodes = [];
          const pseudoElements = [];
          const textRuns = [];
          const collectPseudo = (node, hostNodeId, pseudo) => {
            if (!hostNodeId) return;
            const style = getComputedStyle(node, pseudo);
            const content = style.content;
            if (!content || content === 'none' || content === 'normal' || style.display === 'none') return;
            pseudoElements.push({
              nodeId: `${hostNodeId}:${pseudo.slice(2)}`, hostNodeId, pseudo, content,
              visible: effectiveOpacity(node) * Number(style.opacity || 1) > 0,
              bounds: null, style: styleData(style)
            });
          };
          const walk = (node, parentIndex) => {
            const bounds = rect(node);
            const style = getComputedStyle(node);
            const index = nodes.length;
            const stableNodeId = nodeId(node);
            nodes.push({
              nodeId: stableNodeId, parentIndex,
              tag: node.tagName.toLowerCase(), id: node.id || null,
              classNames: Array.from(node.classList), text: Array.from(node.childNodes)
                .filter((child) => child.nodeType === Node.TEXT_NODE)
                .map((child) => child.textContent.trim()).filter(Boolean).join(' '),
              bounds, visible: visible(node, style, bounds),
              style: { ...styleData(style), effectiveOpacity: String(effectiveOpacity(node)) }
            });
            collectPseudo(node, stableNodeId, '::before');
            Array.from(node.childNodes).forEach((child, childIndex) => {
              if (child.nodeType === Node.ELEMENT_NODE) {
                walk(child, index);
                return;
              }
              if (child.nodeType !== Node.TEXT_NODE || !child.textContent || !child.textContent.trim()) return;
              const range = document.createRange();
              range.selectNodeContents(child);
              const textBounds = range.getBoundingClientRect();
              textRuns.push({
                nodeId: stableNodeId ? `${stableNodeId}:text:${childIndex}` : null,
                hostNodeId: stableNodeId,
                text: child.textContent,
                bounds: { x: textBounds.x, y: textBounds.y, width: textBounds.width, height: textBounds.height },
                visible: visible(node, style, textBounds),
                style: { ...styleData(style), effectiveOpacity: String(effectiveOpacity(node)) }
              });
              range.detach();
            });
            collectPseudo(node, stableNodeId, '::after');
          };
          walk(root, null);
          const mappingErrors = [];
          const seen = new Set();
          const allowedBrowserContainers = new Set(['tbody', 'thead', 'tfoot', 'colgroup']);
          for (const item of nodes) {
            if (!item.nodeId) {
              if (item.visible && !allowedBrowserContainers.has(item.tag)) {
                mappingErrors.push(`unmapped-visible:${item.tag}`);
              }
              continue;
            }
            if (seen.has(item.nodeId)) mappingErrors.push(`duplicate:${item.nodeId}`);
            seen.add(item.nodeId);
            if (expectedNodes[item.nodeId] !== item.tag) {
              mappingErrors.push(`tag:${item.nodeId}:${expectedNodes[item.nodeId]}!=${item.tag}`);
            }
          }
          const expectedInRoot = [root, ...root.querySelectorAll('[data-code-lanhu-node-id]')]
            .filter((node) => !node.closest('template,noscript,script'))
            .map((node) => nodeId(node)).filter(Boolean);
          for (const expectedNodeId of expectedInRoot) {
            if (!seen.has(expectedNodeId)) mappingErrors.push(`missing:${expectedNodeId}`);
          }
          const rootStableId = nodeId(root);
          const rootSelector = root === body ? 'body'
            : `[data-code-lanhu-node-id="${CSS.escape(rootStableId || '')}"]`;
          return {
            root: { selector: rootSelector, nodeId: rootStableId, bounds: rect(root) },
            browser: { userAgent: navigator.userAgent, viewport: { width: window.innerWidth, height: window.innerHeight }, deviceScaleFactor: window.devicePixelRatio },
            nodes, pseudoElements, textRuns, mappingErrors,
            images: Array.from(root.querySelectorAll('img')).map((image) => ({
              nodeId: nodeId(image), source: image.currentSrc || image.src, naturalWidth: image.naturalWidth,
              naturalHeight: image.naturalHeight, bounds: rect(image), objectFit: getComputedStyle(image).objectFit
            }))
          };
        }
    """
    runs_root = artifact / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    screenshot_path = runs_root / "设计截图.png"
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True, executable_path=str(CHROME_EXECUTABLE))
            try:
                blocked_requests: list[str] = []
                blocked_websockets: list[str] = []
                blocked_popups: list[str] = []
                blocked_downloads: list[str] = []

                def route_design_request(route: Any) -> None:
                    request_url = route.request.url
                    if is_allowed_design_request(request_url, url):
                        route.continue_()
                    else:
                        blocked_requests.append(request_url)
                        route.abort()

                context = browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    device_scale_factor=dpr,
                    service_workers="block",
                    accept_downloads=False,
                )
                context.route("**/*", route_design_request)

                def block_websocket(route: Any) -> None:
                    blocked_websockets.append(route.url)
                    route.close(code=1008, reason="design capture is offline")

                context.route_web_socket("**/*", block_websocket)
                page = context.new_page()

                def block_popup(popup: Any) -> None:
                    blocked_popups.append(popup.url)
                    popup.close()

                page.on("popup", block_popup)
                page.on("download", lambda download: blocked_downloads.append(download.suggested_filename))
                page.goto(url, wait_until="networkidle")
                page.add_style_tag(
                    content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
                )
                page.evaluate(
                    """async () => {
                      document.getAnimations().forEach((animation) => animation.cancel());
                      await document.fonts.ready;
                      await Promise.all(Array.from(document.images).map(async (image) => {
                        if (!image.complete) {
                          await new Promise((resolve) => {
                            image.addEventListener('load', resolve, { once: true });
                            image.addEventListener('error', resolve, { once: true });
                          });
                        }
                        if (image.decode) await image.decode().catch(() => {});
                      }));
                      let previous = '';
                      let stableFrames = 0;
                      for (let frame = 0; frame < 30 && stableFrames < 3; frame += 1) {
                        await new Promise((resolve) => requestAnimationFrame(resolve));
                        const current = JSON.stringify(Array.from(document.querySelectorAll('[data-code-lanhu-node-id]')).map((node) => {
                          const bounds = node.getBoundingClientRect();
                          const style = getComputedStyle(node);
                          return [node.getAttribute('data-code-lanhu-node-id'),
                            ...[bounds.x, bounds.y, bounds.width, bounds.height].map((value) => Math.round(value * 100) / 100),
                            style.display, style.visibility, style.opacity, style.transform,
                            node instanceof HTMLImageElement ? node.currentSrc : ''];
                        }));
                        stableFrames = current === previous ? stableFrames + 1 : 0;
                        previous = current;
                      }
                      if (stableFrames < 3) throw new Error('设计布局在连续帧内未稳定');
                    }"""
                )
                result = page.evaluate(script, expected_nodes)
                if result is not None:
                    snapshot = page.context.new_cdp_session(page).send(
                        "DOMSnapshot.captureSnapshot",
                        {"computedStyles": [], "includePaintOrder": True, "includeDOMRects": True},
                    )
                    order_by_id = browser_paint_orders(snapshot)
                    for item in [*result["nodes"], *result["textRuns"]]:
                        item_id = item.get("nodeId")
                        if isinstance(item_id, str) and item_id in order_by_id:
                            item["paintOrder"] = order_by_id[item_id]
                        elif item.get("visible") is not False:
                            result["mappingErrors"].append(f"paint-order-missing:{item_id}")
                    if blocked_requests or blocked_websockets or blocked_popups or blocked_downloads:
                        raise PipelineError(
                            "设计包含不可离线重放的浏览器副作用："
                            f"requests={blocked_requests[:5]}, websockets={blocked_websockets[:5]}, "
                            f"popups={blocked_popups[:5]}, downloads={blocked_downloads[:5]}"
                        )
                    page.locator(result["root"]["selector"]).screenshot(path=str(screenshot_path))
            finally:
                browser.close()
    except PlaywrightError as error:
        raise PipelineError(f"浏览器采集设计失败：{error}") from error
    if result is None:
        raise UserInputRequired("设计页没有可确定的 body 根节点，无法确定有效截图区域")
    if result.get("mappingErrors"):
        raise PipelineError(f"浏览器 DOM 与固定 nodeId 映射冲突：{result['mappingErrors']}")

    bounds = result["root"]["bounds"]
    design = {
        "版本": DESIGN_DOCUMENT_VERSION,
        "来源名称": source["sourceName"],
        "来源路径": source["sourcePath"],
        "sourceMd5": source["sourceMd5"],
        "入口文件": source["html"]["path"],
        "样式文件": [item["path"] for item in source["css"]],
        "设计画布": {"宽度像素": round(bounds["width"]), "高度像素": round(bounds["height"])},
        "设计根节点": {"选择器": result["root"]["selector"], "nodeId": result["root"].get("nodeId"), "边界": bounds},
        "浏览器环境": result["browser"],
        "节点": result["nodes"],
        "伪元素": result["pseudoElements"],
        "文本片段": result["textRuns"],
        "图片资源": result["images"],
        "设计截图Md5": md5_file(screenshot_path),
        "domPath": str(dom_path),
        "采集时间": utc_now(),
    }
    design_path = artifact / DESIGN_DOCUMENT_NAME
    atomic_json(design_path, design)
    return {
        "artifactPath": str(artifact),
        "designPath": str(design_path),
        "screenshotPath": str(screenshot_path),
        "设计根节点": design["设计根节点"],
        "cacheHit": False,
    }


def complete_design_screenshot(archive: Path, project_root: Path, image: Path) -> dict[str, Any]:
    """登记浏览器已保存的设计截图，并在任何结果下回收本地静态服务。"""
    artifact, source, state = load_source(archive, project_root)
    try:
        design_path = artifact / DESIGN_DOCUMENT_NAME
        if not design_path.is_file():
            raise PipelineError(f"缺少设计解析结果，无法登记设计截图：{design_path}")
        design = json.loads(design_path.read_text(encoding="utf-8"))
        if design.get("sourceMd5") != source["sourceMd5"]:
            raise PipelineError(f"设计解析结果与当前 ZIP 不匹配：{design_path}")
        image = image.expanduser().resolve()
        expected_image = (artifact / "runs" / "设计截图.png").resolve()
        if image != expected_image or not image.is_file():
            raise PipelineError("设计截图必须位于 artifact/runs/设计截图.png")
        width, height = validate_png_evidence(image)
        state["designScreenshot"] = {"image": str(image), "md5": md5_file(image), "capturedAt": utc_now()}
        state["designScreenshot"]["width"] = width
        state["designScreenshot"]["height"] = height
        state.setdefault("history", []).append({"phase": "design_screenshot", "at": utc_now(), "detail": state["designScreenshot"]})
        _write_state(artifact, state)
        return {"artifactPath": str(artifact), "image": str(image), "status": "recorded"}
    finally:
        stop_design_server(archive, project_root)


def ensure_design_evidence(
    archive: Path,
    project_root: Path,
    viewport_width: int = 1600,
    viewport_height: int = 900,
    dpr: float = 1.0,
) -> dict[str, Any]:
    """自动完成设计服务、浏览器采集、设计截图登记和服务回收。"""
    artifact, source, _ = load_source(archive, project_root)
    cached = _load_cached_design(artifact, source, (viewport_width, viewport_height, dpr))
    if cached is not None:
        _, screenshot = cached
        return {"artifactPath": str(artifact), "status": "cached", "image": str(screenshot)}
    default_environment = (viewport_width, viewport_height, dpr) == (1600, 900, 1.0)
    started = (
        start_design_server(archive, project_root)
        if default_environment
        else start_design_server(archive, project_root, 0, viewport_width, viewport_height, dpr)
    )
    try:
        captured = (
            capture_rendered_design(archive, project_root)
            if default_environment
            else capture_rendered_design(archive, project_root, viewport_width, viewport_height, dpr)
        )
        return complete_design_screenshot(archive, project_root, Path(captured["screenshotPath"]))
    finally:
        if not started.get("cacheHit"):
            stop_design_server(archive, project_root)


def import_assets(archive: Path, project_root: Path, compose_file: Path, apply: bool = True) -> dict[str, Any]:
    """由 Python 固定执行逐图导入、Hash 清单写入和生成基线记录。"""
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"preflight", "assets_imported"}:
        raise PipelineError(f"当前阶段不能 assets：{state['phase']}")
    compose_file = compose_file.expanduser().resolve()
    command = [
        sys.executable,
        str(Path(__file__).with_name("import_zip_images.py")),
        "--zip",
        str(archive),
        "--compose",
        str(compose_file),
        "--project-root",
        str(project_root),
        "--extraction-root",
        str(artifact / "design-server-source"),
    ]
    if apply:
        command.append("--apply")
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)
    (artifact / "logs").mkdir(exist_ok=True)
    (artifact / "logs" / "assets.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise PipelineError(f"资源导入失败，日志已写入：{artifact / 'logs' / 'assets.log'}")
    if not apply:
        return {"artifactPath": str(artifact), "phase": state["phase"], "preview": True}
    state["composeFile"] = str(compose_file)
    if state["phase"] != "assets_imported":
        transition(state, "assets_imported", {"composeFile": str(compose_file), "apply": True})
    state["composeBaselineMd5"] = md5_file(compose_file)
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "composeBaselineMd5": state["composeBaselineMd5"]}


def infer_package_name(compose_file: Path) -> str:
    try:
        source = compose_file.read_text(encoding="utf-8")
    except OSError as error:
        raise PipelineError(f"无法读取 Compose 包名：{compose_file}") from error
    identifier = r"(?:[A-Za-z_][\w]*|`[^`\r\n]+`)"
    match = re.search(rf"^\s*package\s+({identifier}(?:\.{identifier})*)\s*$", source, flags=re.MULTILINE)
    if not match:
        raise UserInputRequired(f"目标 Compose 缺少 package 声明，无法确定代码生成包名：{compose_file}")
    return ".".join(part[1:-1] if part.startswith("`") else part for part in match.group(1).split("."))


def infer_resource_package(project_root: Path, compose_file: Path) -> str | None:
    """优先复用显式 R import，否则读取目标模块 namespace/Manifest package。"""
    try:
        source = compose_file.read_text(encoding="utf-8")
    except OSError as error:
        raise PipelineError(f"无法读取资源包名：{compose_file}") from error
    identifier = r"(?:[A-Za-z_][\w]*|`[^`\r\n]+`)"
    match = re.search(rf"^\s*import\s+({identifier}(?:\.{identifier})*)\.R\s*$", source, flags=re.MULTILINE)
    if match:
        return ".".join(part[1:-1] if part.startswith("`") else part for part in match.group(1).split("."))
    root = project_root.expanduser().resolve()
    target = compose_file.expanduser().resolve()
    try:
        relative = target.relative_to(root)
        source_index = relative.parts.index("src")
    except (ValueError, OSError):
        return None
    module_root = root.joinpath(*relative.parts[:source_index])
    for build_file in (module_root / "build.gradle.kts", module_root / "build.gradle"):
        if not build_file.is_file():
            continue
        build_source = build_file.read_text(encoding="utf-8", errors="replace")
        namespace = re.search(
            r"\bnamespace\s*(?:=\s*)?[\"']([A-Za-z_][\w.]*)[\"']",
            build_source,
        )
        if namespace:
            return namespace.group(1)
    manifest = module_root / "src" / "main" / "AndroidManifest.xml"
    if manifest.is_file():
        package = re.search(
            r"<manifest\b[^>]*\bpackage\s*=\s*[\"']([A-Za-z_][\w.]*)[\"']",
            manifest.read_text(encoding="utf-8", errors="replace"),
        )
        if package:
            return package.group(1)
    return None


def _stable_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.md5(encoded).hexdigest()


def generation_input_fingerprint(artifact: Path, project_root: Path, compose_file: Path) -> str:
    """绑定生成器、DOM、浏览器事实、图片清单和目标代码/资源包。"""
    inputs: dict[str, Any] = {
        "generatorMd5": md5_file(Path(__file__).with_name("generate_compose.py")),
        "composePath": str(compose_file.expanduser().resolve()),
        "package": infer_package_name(compose_file),
        "resourcePackage": infer_resource_package(project_root, compose_file),
    }
    for name in (DOM_DOCUMENT_NAME, DESIGN_DOCUMENT_NAME, "images.json"):
        path = artifact / name
        if not path.is_file():
            raise PipelineError(f"生成缓存缺少固定输入：{path}")
        inputs[name] = md5_file(path)
    return _stable_fingerprint(inputs)


def _compose_module_root(project_root: Path, compose_file: Path) -> Path:
    root = project_root.expanduser().resolve()
    compose = compose_file.expanduser().resolve()
    try:
        relative = compose.relative_to(root)
        source_index = relative.parts.index("src")
    except (ValueError, IndexError) as error:
        raise PipelineError(f"无法从 Compose 路径确定目标模块：{compose}") from error
    return root.joinpath(*relative.parts[:source_index]).resolve()


def _build_configuration_files(project_root: Path, compose_file: Path) -> list[Path]:
    root = project_root.expanduser().resolve()
    module_root = _compose_module_root(root, compose_file)
    candidates = [
        *(root / name for name in ("settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts", "gradle.properties")),
        *(module_root / name for name in ("build.gradle", "build.gradle.kts", "gradle.properties")),
        root / "gradle" / "libs.versions.toml",
        root / "gradle" / "wrapper" / "gradle-wrapper.properties",
    ]
    build_src = root / "buildSrc"
    if build_src.is_dir():
        candidates.extend(
            path
            for path in build_src.rglob("*")
            if path.is_file() and path.suffix.lower() in {".gradle", ".kts", ".kt", ".java", ".toml", ".properties"}
        )
    return sorted({path.resolve() for path in candidates if path.is_file()}, key=str)


def compile_input_snapshot(
    artifact: Path,
    project_root: Path,
    compose_file: Path,
    task: str,
) -> dict[str, Any]:
    """生成可审计的编译缓存键，并报告已登记但丢失的 Android 资源。"""
    root = project_root.expanduser().resolve()
    compose = compose_file.expanduser().resolve()
    images_path = artifact / "images.json"
    try:
        images = json.loads(images_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError(f"编译缓存缺少有效图片清单：{images_path}") from error
    records = images.get("images", []) if isinstance(images, dict) else None
    if not isinstance(records, list):
        raise PipelineError(f"图片清单 images 必须是数组：{images_path}")
    resource_files: list[dict[str, str]] = []
    missing_resources: list[str] = []
    for record in records:
        output = record.get("outputPath") if isinstance(record, dict) else None
        if not isinstance(output, str) or not output:
            raise PipelineError(f"图片清单缺少 outputPath：{record}")
        candidate = Path(output).expanduser()
        candidate = candidate if candidate.is_absolute() else root / candidate
        resolved = candidate.resolve()
        if root not in resolved.parents or candidate.is_symlink():
            raise PipelineError(f"图片资源必须位于项目目录且不能是符号链接：{candidate}")
        if not resolved.is_file():
            missing_resources.append(str(resolved))
            continue
        resource_files.append({"path": str(resolved.relative_to(root)), "md5": md5_file(resolved)})
    build_files = [
        {"path": str(path.relative_to(root)), "md5": md5_file(path)}
        for path in _build_configuration_files(root, compose)
    ]
    module_source_root = _compose_module_root(root, compose) / "src"
    source_files = [
        {"path": str(path.relative_to(root)), "md5": md5_file(path)}
        for path in sorted(module_source_root.rglob("*"), key=str)
        if path.is_file() and not path.is_symlink()
    ] if module_source_root.is_dir() else []
    payload = {
        "task": task,
        "composePath": str(compose),
        "composeMd5": md5_file(compose),
        "imagesManifestMd5": md5_file(images_path),
        "resources": resource_files,
        "buildFiles": build_files,
        "moduleSourceFiles": source_files,
    }
    return {
        **payload,
        "fingerprint": _stable_fingerprint(payload),
        "missingResources": missing_resources,
    }


def require_current_compile_evidence(
    artifact: Path,
    project_root: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    compose_value = state.get("composeFile")
    task = state.get("preflightTask")
    if not isinstance(compose_value, str) or not isinstance(task, str):
        raise PipelineError("缺少 Compose/Gradle task，无法验证编译证据")
    snapshot = compile_input_snapshot(artifact, project_root, Path(compose_value), task)
    if snapshot["missingResources"]:
        raise PipelineError(f"已编译页面的图片资源已丢失：{snapshot['missingResources']}")
    if (
        state.get("lastCompiledComposeMd5") != snapshot["composeMd5"]
        or state.get("compileInputFingerprint") != snapshot["fingerprint"]
    ):
        raise PipelineError("Compose、模块源码、资源或 Gradle 配置已变化，当前编译证据已过期；请重新 run-fixed")
    return snapshot


def require_current_install_evidence(
    artifact: Path,
    project_root: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    snapshot = require_current_compile_evidence(artifact, project_root, state)
    apk_value = state.get("installedApk")
    if not isinstance(apk_value, str):
        raise PipelineError("缺少当前安装 APK 的证据")
    apk = Path(apk_value).expanduser().resolve()
    if (
        not apk.is_file()
        or state.get("installedApkMd5") != md5_file(apk)
        or state.get("installedComposeMd5") != snapshot["composeMd5"]
        or state.get("installedCompileInputFingerprint") != snapshot["fingerprint"]
    ):
        raise PipelineError("已安装 APK 与当前源码/编译输入不一致；请重新打包并安装")
    return snapshot


def generate_compose_from_dom(archive: Path, project_root: Path, compose_file: Path) -> dict[str, Any]:
    """由已保存的 DOM IR 和浏览器计算结果生成目标 Compose，不读取模型补丁。"""
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] not in {"assets_imported", "generated"}:
        raise PipelineError(f"当前阶段不能 generate-compose：{state['phase']}")
    dom_path = artifact / DOM_DOCUMENT_NAME
    design_path = artifact / DESIGN_DOCUMENT_NAME
    if not dom_path.is_file() or not design_path.is_file():
        raise PipelineError(f"缺少 DOM/设计解析输入：{dom_path}、{design_path}")
    try:
        dom_identity = json.loads(dom_path.read_text(encoding="utf-8"))
        design_identity = json.loads(design_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError("DOM/设计解析输入不是有效 JSON") from error
    if dom_identity.get("sourceMd5") != source["sourceMd5"] or design_identity.get("sourceMd5") != source["sourceMd5"]:
        raise PipelineError("DOM 或设计解析结果与当前 ZIP 的 sourceMd5 不一致，拒绝生成")
    cached_design = _load_cached_design(artifact, source)
    if cached_design is None or (artifact / DESIGN_DOCUMENT_NAME).resolve() != design_path.resolve():
        raise PipelineError("设计解析版本、paintOrder 或设计截图证据无效，请重新采集设计")
    compose_file = compose_file.expanduser().resolve()
    try:
        images_path = artifact / "images.json"
        result = generate_compose(
            dom_path,
            design_path,
            compose_file,
            infer_package_name(compose_file),
            images_path if images_path.is_file() else None,
            infer_resource_package(project_root, compose_file),
        )
    except GenerationError as error:
        raise PipelineError(str(error)) from error
    result["inputFingerprint"] = generation_input_fingerprint(artifact, project_root, compose_file)
    validate_compose_source(compose_file)
    state["composeFile"] = str(compose_file)
    if state["phase"] != "generated":
        transition(state, "generated", {"composeFile": str(compose_file), "generator": "generate_compose.py", **result})
    state["domPath"] = str(dom_path)
    state["designPath"] = str(design_path)
    state["composeGeneration"] = result
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], **result, "sourceMd5": source["sourceMd5"]}


def parse_dom(archive: Path, project_root: Path) -> dict[str, Any]:
    """显式重建并保存完整 DOM IR，供调试和固定管线复用。"""
    artifact, source, _ = load_source(archive, project_root)
    dom = parse_html_archive(archive, source["html"]["path"])
    dom["sourceMd5"] = source["sourceMd5"]
    dom_path = artifact / DOM_DOCUMENT_NAME
    atomic_json(dom_path, dom)
    return {"artifactPath": str(artifact), "domPath": str(dom_path), "nodeCount": len(dom["nodes"]), "resourceCount": len(dom["resources"]), "sourceMd5": source["sourceMd5"]}


def _invalidate_downstream_state(state: dict[str, Any], phase: str, reason: str) -> None:
    """缓存失效时回退到最小必要阶段，并移除与旧编译/APK/截图绑定的证据。"""
    state["phase"] = phase
    for key in (
        "packagedApk",
        "packagedComposeMd5",
        "packagedApkMd5",
        "installedApk",
        "lastScreenshot",
        "comparison",
        "lastDiffOutcome",
    ):
        state.pop(key, None)
    state.setdefault("history", []).append(
        {"phase": "cache_invalidated", "at": utc_now(), "detail": {"resumePhase": phase, "reason": reason}}
    )


def run_fixed_pipeline(
    archive: Path,
    project_root: Path,
    compose_file: Path,
    viewport_width: int = 1600,
    viewport_height: int = 900,
    dpr: float = 1.0,
) -> dict[str, Any]:
    """自动推进浏览器采集、资源导入和编译，只在等待页面代码时暂停。"""
    archive = archive.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    compose_file = compose_file.expanduser().resolve()
    inspect_archive(archive, project_root, compose_file)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "inspected":
        validate_project(archive, project_root, compose_file)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "validated":
        preflight_project(archive, project_root)
    design = (
        ensure_design_evidence(archive, project_root)
        if (viewport_width, viewport_height, dpr) == (1600, 900, 1.0)
        else ensure_design_evidence(archive, project_root, viewport_width, viewport_height, dpr)
    )
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "preflight":
        import_assets(archive, project_root, compose_file, apply=True)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "assets_imported":
        generated = generate_compose_from_dom(archive, project_root, compose_file)
        compile_project(archive, project_root)
        return {"artifactPath": str(artifact), "phase": "compiled", "status": "compose_generated_and_compile_started", "design": design, "generation": generated}
    if PHASES.index(state["phase"]) >= PHASES.index("compiled"):
        current = md5_file(compose_file)
        generation = state.get("composeGeneration")
        last_generated = generation.get("composeMd5") if isinstance(generation, dict) else None
        generated_input = generation.get("inputFingerprint") if isinstance(generation, dict) else None
        manual_adaptation = isinstance(last_generated, str) and current != last_generated
        task = state.get("preflightTask")
        if not isinstance(task, str) or not task:
            raise PipelineError("已编译状态缺少 preflightTask，不能验证热缓存")

        images_path = artifact / "images.json"
        snapshot = None
        if images_path.is_file():
            snapshot = compile_input_snapshot(artifact, project_root, compose_file, task)
        needs_asset_restore = snapshot is None or bool(snapshot["missingResources"])
        if needs_asset_restore:
            reason = "images.json 缺失" if snapshot is None else f"资源输出缺失：{snapshot['missingResources']}"
            _invalidate_downstream_state(state, "preflight", reason)
            _write_state(artifact, state)
            import_assets(archive, project_root, compose_file, apply=True)
            artifact, _, state = load_source(archive, project_root)

        current_generation_input = generation_input_fingerprint(artifact, project_root, compose_file)
        should_regenerate = not manual_adaptation and generated_input != current_generation_input
        if should_regenerate:
            _invalidate_downstream_state(state, "assets_imported", "Compose 生成输入或生成器发生变化")
            _write_state(artifact, state)
            generated = generate_compose_from_dom(archive, project_root, compose_file)
            compile_project(archive, project_root)
            return {
                "artifactPath": str(artifact),
                "phase": "compiled",
                "status": "regenerated_after_input_change",
                "design": design,
                "generation": generated,
            }

        if needs_asset_restore:
            _invalidate_downstream_state(
                state,
                "generated",
                "资源已恢复，保留当前 Compose" + ("（用户适配版）" if manual_adaptation else ""),
            )
            _write_state(artifact, state)
            compile_project(archive, project_root)
            return {
                "artifactPath": str(artifact),
                "phase": "compiled",
                "status": "recompiled_after_resource_restore",
                "design": design,
            }

        snapshot = compile_input_snapshot(artifact, project_root, compose_file, task)
        last_compiled = state.get("lastCompiledComposeMd5")
        last_compile_input = state.get("compileInputFingerprint")
        if current == last_compiled and snapshot["fingerprint"] == last_compile_input:
            return {"artifactPath": str(artifact), "phase": state["phase"], "status": "unchanged", "design": design}

        validate_compose_source(compose_file)
        _invalidate_downstream_state(
            state,
            "generated",
            "Compose 或资源/Gradle 编译输入发生变化",
        )
        if manual_adaptation:
            state["manualAdaptation"] = {"composeMd5": current, "recordedAt": utc_now()}
        _write_state(artifact, state)
        compile_project(archive, project_root)
        return {
            "artifactPath": str(artifact),
            "phase": "compiled",
            "status": "recompiled_after_compile_input_change",
            "design": design,
        }
    if state["phase"] == "generated":
        compile_project(archive, project_root)
        return {"artifactPath": str(artifact), "phase": "compiled", "status": "compile_started", "design": design}
    return {"artifactPath": str(artifact), "phase": state["phase"], "status": "unchanged", "design": design}


def restart_generation_cycle(archive: Path, project_root: Path, reason: str) -> dict[str, Any]:
    """在用户明确纠正实现方向后，从已停止的视觉结果重开代码生成周期。"""
    artifact, source, state = load_source(archive, project_root)
    if state.get("phase") != "diffed" or state.get("lastDiffOutcome") != "stop":
        raise PipelineError("只有 outcome=stop 的差异阶段才能重新开始代码生成")
    reason = reason.strip()
    if not reason:
        raise PipelineError("重新开始代码生成必须记录用户给出的原因")
    for name in (DOM_DOCUMENT_NAME, DESIGN_DOCUMENT_NAME, "images.json"):
        path = artifact / name
        if not path.is_file():
            raise PipelineError(f"重新生成缺少固定输入：{path}")
        try:
            identity = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"重新生成输入不是有效 JSON：{path}") from error
        if identity.get("sourceMd5") != source["sourceMd5"]:
            raise PipelineError(f"重新生成输入与当前 ZIP 的 sourceMd5 不一致：{path}")
    state["phase"] = "generated"
    state["generationCycle"] = state.get("generationCycle", 1) + 1
    state.setdefault("attempts", {})["repair"] = 0
    state.pop("lastDiffOutcome", None)
    state.setdefault("history", []).append(
        {
            "phase": "generation_restarted",
            "at": utc_now(),
            "detail": {"reason": reason, "generationCycle": state["generationCycle"]},
        }
    )
    _write_state(artifact, state)
    return {
        "artifactPath": str(artifact),
        "phase": state["phase"],
        "generationCycle": state["generationCycle"],
        "reason": reason,
    }


def validate_project(archive: Path, project_root: Path, compose_file: Path | None = None) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] not in {"inspected", "validated"}:
        raise PipelineError(f"当前阶段不能 validate：{state['phase']}")
    target = compose_file or (Path(state["composeFile"]) if state.get("composeFile") else None)
    if target is None:
        raise PipelineError("validate 必须提供目标 Compose 文件")
    if target is not None:
        target = target.expanduser().resolve()
        root = project_root.expanduser().resolve()
        if root not in target.parents and target != root:
            raise PipelineError(f"Compose 目标必须位于项目根目录内：{target}")
        if not target.is_file():
            raise PipelineError(f"Compose 目标不存在：{target}")
        validate_compose_source(target)
        state["composeFile"] = str(target)
    transition(state, "validated", {"composeFile": state.get("composeFile")})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "sourceMd5": source["sourceMd5"]}


def validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict) or decision.get("action") not in ALLOWED_ACTIONS:
        raise PipelineError(f"决策 action 必须属于 {sorted(ALLOWED_ACTIONS)}，禁止执行任意 shell")
    action = decision["action"]
    if action == "ask_user":
        question = decision.get("question")
        if not isinstance(question, str) or not question.strip():
            raise PipelineError("ask_user 必须提供 question")
    if action == "apply_patch":
        target = decision.get("target")
        patch = decision.get("patch")
        if not isinstance(target, str) or not target or not isinstance(patch, dict):
            raise PipelineError("apply_patch 必须提供 target 和结构化 patch")
        if any(token in target for token in ("..", "\\")) or target.startswith("/"):
            raise PipelineError("apply_patch target 必须是项目内相对路径")
    return decision


def validate_device_name(actual: str, expected: str = "K80") -> bool:
    if actual != expected:
        raise PipelineError(f"当前模拟器为 {actual!r}，项目约束要求 {expected!r}")
    return True


def _run_fixed(command: list[str], cwd: Path, log_path: Path) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    log_path.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    return completed


def gradle_command(project_root: Path) -> list[str]:
    """在项目根目录优先执行 Gradle Wrapper，缺失时回退系统 Gradle。"""
    root = project_root.expanduser().resolve()
    if (root / "gradlew").is_file():
        return ["./gradlew"]
    if shutil.which("gradle"):
        return ["gradle"]
    raise PipelineError(f"项目根目录缺少 ./gradlew，且系统未安装 gradle：{root}")


def compose_gradle_module(project_root: Path, compose_file: Path) -> str:
    """根据目标 Compose 文件路径确定 Gradle 模块，避免由调用方猜 task。"""
    root = project_root.expanduser().resolve()
    target = compose_file.expanduser().resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise PipelineError(f"Compose 文件必须位于项目根目录内：{target}") from error
    parts = relative.parts
    try:
        source_index = parts.index("src")
    except ValueError as error:
        raise PipelineError(f"无法从 Compose 路径识别 Gradle 模块（缺少 src）：{target}") from error
    module_parts = parts[:source_index]
    return ":" + ":".join(module_parts) if module_parts else ""


def _normalize_gradle_task(task: str) -> str:
    value = task.strip()
    return value if value.startswith(":") else f":{value}"


def discover_compile_task(project_root: Path, compose_file: Path, selected_task: str | None = None) -> str:
    """由 Gradle 任务列表确定目标模块的稳定 Debug Kotlin 编译任务。"""
    root = project_root.expanduser().resolve()
    module = compose_gradle_module(root, compose_file)
    result = subprocess.run(
        [*gradle_command(root), "tasks", "--all", "--console=plain"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise PipelineError(f"无法读取 Gradle 任务列表：{result.stderr.strip() or result.stdout.strip()}")

    candidates = []
    for line in result.stdout.splitlines():
        match = GRADLE_COMPILE_TASK.match(line)
        if not match:
            continue
        task = _normalize_gradle_task(match.group(1))
        if module and not task.startswith(f"{module}:"):
            continue
        task_name = task.rsplit(":", 1)[-1]
        if "AndroidTest" in task_name or "UnitTest" in task_name or task_name.endswith("TestKotlin"):
            continue
        candidates.append(task)

    candidates = sorted(set(candidates))
    if not candidates:
        raise PipelineError(f"未找到模块 {module or ':root'} 的 Kotlin 编译任务，不能让模型猜测 Gradle task")

    if selected_task is not None:
        selected = _normalize_gradle_task(selected_task)
        if not SAFE_TASK.fullmatch(selected) or selected not in candidates:
            raise PipelineError(f"用户选择的 Gradle task 不属于目标模块实际候选：{selected}，候选：{candidates}")
        return selected

    exact_debug = [task for task in candidates if task.endswith(":compileDebugKotlin")]
    if len(exact_debug) == 1:
        return exact_debug[0]
    debug_candidates = [task for task in candidates if task.endswith("DebugKotlin")]
    if len(debug_candidates) == 1:
        return debug_candidates[0]
    if len(debug_candidates) > 1:
        raise UserInputRequired(f"模块 {module or ':root'} 存在多个 Debug Kotlin 编译任务，请用户明确选择：{debug_candidates}")
    if len(candidates) == 1:
        return candidates[0]
    raise UserInputRequired(f"模块 {module or ':root'} 的 Kotlin 编译任务存在歧义，请用户明确选择：{candidates}")


def derive_package_task(compile_task: str) -> str:
    """把 preflight 确定的 Kotlin 编译任务映射为同变体 assemble 任务。"""
    if not SAFE_TASK.fullmatch(compile_task):
        raise PipelineError(f"Gradle task 不在白名单中：{compile_task}")
    task_name = compile_task.rsplit(":", 1)[-1]
    match = re.fullmatch(r"compile(.+)Kotlin", task_name)
    if match is None:
        raise PipelineError(f"无法从编译任务推导打包任务：{compile_task}")
    module = compile_task.rsplit(":", 1)[0]
    package_task = f"{module}:assemble{match.group(1)}"
    if not SAFE_TASK.fullmatch(package_task):
        raise PipelineError(f"推导出的打包任务不在白名单中：{package_task}")
    return package_task


def variant_name_from_compile_task(compile_task: str) -> str:
    task_name = compile_task.rsplit(":", 1)[-1]
    match = re.fullmatch(r"compile(.+)Kotlin", task_name)
    if match is None:
        raise PipelineError(f"无法从编译任务推导 variant：{compile_task}")
    value = match.group(1)
    return value[:1].lower() + value[1:]


def variant_apk_outputs(apk_output_root: Path, variant_name: str) -> set[Path]:
    outputs: set[Path] = set()
    for metadata_path in apk_output_root.rglob("output-metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"APK 输出元数据无效：{metadata_path}") from error
        if not isinstance(metadata, dict) or metadata.get("variantName") != variant_name:
            continue
        for element in metadata.get("elements", []):
            output_name = element.get("outputFile") if isinstance(element, dict) else None
            if isinstance(output_name, str) and output_name:
                candidate = (metadata_path.parent / output_name).resolve()
                if apk_output_root.resolve() in candidate.parents:
                    outputs.add(candidate)
    return outputs


def record_decision(archive: Path, project_root: Path, decision_path: Path) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    decision = validate_decision(json.loads(decision_path.read_text(encoding="utf-8")))
    if decision["action"] == "apply_patch":
        root = project_root.expanduser().resolve()
        target = (root / decision["target"]).resolve()
        if root not in target.parents:
            raise PipelineError("apply_patch target 必须解析到项目根目录内")
    index = len(list(artifact.glob("decision-*.json"))) + 1
    atomic_json(artifact / f"decision-{index:02d}.json", {**decision, "recordedAt": utc_now(), "phase": state["phase"]})
    if decision["action"] == "ask_user":
        atomic_json(artifact / "needs-user-input.json", {**decision, "recordedAt": utc_now()})
        raise UserInputRequired(decision["question"])
    return {"artifactPath": str(artifact), "action": decision["action"], "phase": state["phase"]}


def reserve_attempt(artifact: Path, state: dict[str, Any], name: str, limit: int = 3) -> int:
    attempts = state.setdefault("attempts", {})
    current = int(attempts.get(name, 0))
    if current >= limit:
        raise PipelineError(f"{name} 已达到最多 {limit} 次，停止自动重试")
    attempt = current + 1
    attempts[name] = attempt
    state.setdefault("history", []).append(
        {"phase": f"{name}_started", "at": utc_now(), "detail": {"attempt": attempt, "limit": limit}}
    )
    _write_state(artifact, state)
    return attempt


def compile_project(archive: Path, project_root: Path) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] not in {"generated", "compiled"}:
        raise PipelineError(f"当前阶段不能 compile：{state['phase']}")
    task = state.get("preflightTask")
    if not isinstance(task, str) or not task:
        raise PipelineError("compile 必须复用 Python preflight 已确定的任务")
    if not SAFE_TASK.fullmatch(task):
        raise PipelineError(f"Gradle task 不在白名单中：{task}")
    gradle = gradle_command(project_root)
    if state.get("preflightTask") != task:
        raise PipelineError(f"compile 必须复用 preflight 任务：{state.get('preflightTask')!r} != {task!r}")
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("compile 缺少 Compose 文件，无法执行布局安全检查")
    compose_path = Path(compose_file).expanduser().resolve()
    validate_compose_source(compose_path)
    cache_snapshot = compile_input_snapshot(artifact, project_root, compose_path, task)
    if cache_snapshot["missingResources"]:
        raise PipelineError(f"编译前发现图片资源缓存失效：{cache_snapshot['missingResources']}")
    attempt = reserve_attempt(artifact, state, "compile")
    log = artifact / "logs" / f"compile-{attempt:02d}.log"
    result = _run_fixed([*gradle, task, "--console=plain"], project_root, log)
    if result.returncode != 0:
        state.setdefault("history", []).append(
            {"phase": "compile_failed", "at": utc_now(), "detail": {"attempt": attempt, "task": task, "log": str(log)}}
        )
        _write_state(artifact, state)
        raise PipelineError(f"编译失败，日志已写入：{log}")
    if state["phase"] != "compiled":
        transition(
            state,
            "compiled",
            {"task": task, "log": str(log), "compileInputFingerprint": cache_snapshot["fingerprint"]},
        )
    state["lastCompiledComposeMd5"] = cache_snapshot["composeMd5"]
    state["compileInputFingerprint"] = cache_snapshot["fingerprint"]
    state["compileInputs"] = {
        "task": task,
        "imagesManifestMd5": cache_snapshot["imagesManifestMd5"],
        "resourceCount": len(cache_snapshot["resources"]),
        "buildFiles": cache_snapshot["buildFiles"],
        "moduleSourceCount": len(cache_snapshot["moduleSourceFiles"]),
    }
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "log": str(log)}


def package_debug(archive: Path, project_root: Path, apk: Path) -> dict[str, Any]:
    """执行与 preflight 编译变体一致的 assemble，并登记 APK 新鲜度。"""
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"compiled", "installed"}:
        raise PipelineError(f"当前阶段不能 package-debug：{state['phase']}")
    compile_task = state.get("preflightTask")
    if not isinstance(compile_task, str) or not compile_task:
        raise PipelineError("package-debug 必须复用 Python preflight 已确定的任务")
    task = derive_package_task(compile_task)
    apk = apk.expanduser().resolve()
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("package-debug 缺少 Compose 文件")
    compose = Path(compose_file).expanduser().resolve()
    if not compose.is_file():
        raise PipelineError(f"Compose 文件不存在：{compose}")
    root = project_root.expanduser().resolve()
    try:
        relative = compose.relative_to(root)
        source_index = relative.parts.index("src")
    except (ValueError, IndexError) as error:
        raise PipelineError(f"无法从 Compose 路径确定模块 APK 输出目录：{compose}") from error
    module_root = root.joinpath(*relative.parts[:source_index])
    apk_output_root = (module_root / "build" / "outputs" / "apk").resolve()
    if apk.suffix.lower() != ".apk" or apk_output_root not in apk.parents:
        raise PipelineError(f"APK 必须位于目标 Compose 模块的 APK 输出目录：{apk_output_root}")
    compile_snapshot = require_current_compile_evidence(artifact, project_root, state)
    attempt = reserve_attempt(artifact, state, "package")
    log = artifact / "logs" / f"package-{attempt:02d}.log"
    result = _run_fixed([*gradle_command(project_root), task, "--console=plain"], project_root, log)
    if result.returncode != 0:
        state.setdefault("history", []).append(
            {"phase": "package_failed", "at": utc_now(), "detail": {"attempt": attempt, "task": task, "log": str(log)}}
        )
        _write_state(artifact, state)
        raise PipelineError(f"打包失败，日志已写入：{log}")
    if not apk.is_file():
        raise PipelineError(f"assemble 完成但 APK 不存在：{apk}")
    variant_name = variant_name_from_compile_task(compile_task)
    expected_apks = variant_apk_outputs(apk_output_root, variant_name)
    if apk not in expected_apks:
        raise PipelineError(
            f"APK 不属于 preflight 变体 {variant_name} 的 output-metadata.json：{apk}，候选：{sorted(map(str, expected_apks))}"
        )
    if apk.stat().st_mtime < compose.stat().st_mtime:
        raise PipelineError(f"assemble 完成但 APK 仍早于 Compose 文件，疑似产物过期：{apk}")
    state["packagedApk"] = str(apk)
    state["packagedComposeMd5"] = md5_file(compose)
    state["packagedApkMd5"] = md5_file(apk)
    state["packagedCompileInputFingerprint"] = compile_snapshot["fingerprint"]
    state.setdefault("history", []).append(
        {"phase": "packaged", "at": utc_now(), "detail": {"task": task, "apk": str(apk), "log": str(log)}}
    )
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "task": task, "apk": str(apk), "log": str(log)}


def preflight_project(archive: Path, project_root: Path) -> dict[str, Any]:
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"validated", "preflight"}:
        raise PipelineError(f"当前阶段不能 preflight：{state['phase']}")
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("preflight 缺少 Compose 文件，无法由 Python 解析 Gradle 模块")
    selected = state.get("selectedCompileTask")
    task = discover_compile_task(project_root, Path(compose_file), selected if isinstance(selected, str) else None)
    if not SAFE_TASK.fullmatch(task):
        raise PipelineError(f"Gradle task 不在白名单中：{task}")
    log = artifact / "logs" / "preflight.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"已由 Gradle tasks --all 确认目标编译任务：{task}\n首稿生成后只执行一次正式编译。\n", encoding="utf-8")
    if state["phase"] != "preflight":
        transition(state, "preflight", {"task": task, "log": str(log), "mode": "task-discovery-only"})
    state["preflightTask"] = task
    state["preflightTaskSource"] = "python-discovered"
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "log": str(log)}


def select_compile_task(archive: Path, project_root: Path, task: str) -> dict[str, Any]:
    """只登记 Gradle 实际列出的目标模块候选，解除多 variant 预检歧义。"""
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] != "validated":
        raise PipelineError(f"只有 validated 阶段可以选择编译任务：{state['phase']}")
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("选择编译任务前缺少目标 Compose 文件")
    root = project_root.expanduser().resolve()
    compose = Path(compose_file).expanduser().resolve()
    selected = discover_compile_task(root, compose, task)
    state["selectedCompileTask"] = selected
    (artifact / "needs-user-input.json").unlink(missing_ok=True)
    state.setdefault("history", []).append(
        {"phase": "compile_task_selected", "at": utc_now(), "detail": {"task": selected}}
    )
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "task": selected}


def install_k80(archive: Path, project_root: Path, serial: str, expected_avd: str, apk: Path) -> dict[str, Any]:
    if expected_avd != "K80":
        raise PipelineError("install-k80 固定要求项目约束中的 K80 模拟器")
    if not SAFE_SERIAL.fullmatch(serial):
        raise PipelineError(f"ADB serial 不安全：{serial}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"compiled", "installed"}:
        raise PipelineError(f"当前阶段不能 install：{state['phase']}")
    if not apk.is_file():
        raise PipelineError(f"APK 不存在：{apk}")
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("install-k80 缺少 Compose 文件，无法校验 APK 新鲜度")
    compose = Path(compose_file).expanduser().resolve()
    if not compose.is_file() or apk.stat().st_mtime < compose.stat().st_mtime:
        raise PipelineError(f"APK 已过期，请先执行 package-debug：{apk}")
    if state.get("packagedApk") != str(apk.expanduser().resolve()) or state.get("packagedComposeMd5") != md5_file(compose):
        raise PipelineError("APK 未由当前 Compose 源码的 package-debug 产出，请先执行 package-debug")
    packaged_apk_md5 = state.get("packagedApkMd5")
    if not isinstance(packaged_apk_md5, str) or packaged_apk_md5 != md5_file(apk):
        raise PipelineError("APK 内容已变化，必须重新执行 package-debug")
    compile_snapshot = require_current_compile_evidence(artifact, project_root, state)
    if state.get("packagedCompileInputFingerprint") != compile_snapshot["fingerprint"]:
        raise PipelineError("APK 绑定的编译输入已变化，必须重新执行 package-debug")
    probe = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise PipelineError(f"无法读取模拟器名称：{probe.stderr.strip()}")
    validate_device_name(probe.stdout.strip(), expected_avd)
    installed = subprocess.run(["adb", "-s", serial, "install", "-r", str(apk.resolve())], text=True, capture_output=True, check=False)
    if installed.returncode != 0:
        raise PipelineError(f"安装 APK 失败：{installed.stdout.strip()} {installed.stderr.strip()}")
    if state["phase"] != "installed":
        transition(state, "installed", {"serial": serial, "avd": expected_avd, "apk": str(apk.resolve())})
    state["installedApk"] = str(apk.resolve())
    state["installedApkMd5"] = packaged_apk_md5
    state["installedComposeMd5"] = compile_snapshot["composeMd5"]
    state["installedCompileInputFingerprint"] = compile_snapshot["fingerprint"]
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "serial": serial, "avd": expected_avd}


def next_evidence_path(directory: Path, filename: str) -> Path:
    """返回目录内未占用的证据文件名：先用原名，再追加 _1、_2……。"""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    suffix = candidate.suffix
    stem = candidate.stem
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def validate_png_evidence(image: Path) -> tuple[int, int]:
    """拒绝空文件、ADB 文本错误页和损坏 PNG，避免把无效截图推进为视觉证据。"""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise PipelineError("缺少 Pillow，无法校验截图 PNG") from error
    try:
        with Image.open(image) as captured:
            if captured.format != "PNG" or captured.width <= 0 or captured.height <= 0:
                raise ValueError("格式或尺寸无效")
            size = captured.size
            captured.verify()
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise PipelineError(f"ADB 截图不是有效 PNG：{image}") from error
    return size


def screenshot_k80(archive: Path, project_root: Path, serial: str, expected_avd: str = "K80") -> dict[str, Any]:
    if not SAFE_SERIAL.fullmatch(serial):
        raise PipelineError(f"ADB serial 不安全：{serial}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"installed", "screenshot"}:
        raise PipelineError(f"当前阶段不能 screenshot：{state['phase']}")
    if expected_avd != "K80":
        raise PipelineError("screenshot-k80 固定要求项目约束中的 K80 模拟器")
    install_snapshot = (
        require_current_install_evidence(artifact, project_root, state)
        if "installedCompileInputFingerprint" in state
        else None
    )
    probe = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise PipelineError(f"无法读取模拟器名称：{probe.stderr.strip()}")
    validate_device_name(probe.stdout.strip(), expected_avd)
    destination = artifact / "runs"
    destination.mkdir(parents=True, exist_ok=True)
    image = next_evidence_path(destination, "应用截图.png")
    valid = False
    try:
        with image.open("wb") as output:
            result = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], stdout=output, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise PipelineError(f"截图失败：{result.stderr.decode(errors='replace').strip()}")
        width, height = validate_png_evidence(image)
        valid = True
    finally:
        if not valid:
            image.unlink(missing_ok=True)
    image_md5 = md5_file(image)
    if state["phase"] != "screenshot":
        transition(
            state,
            "screenshot",
            {"serial": serial, "image": str(image), "imageMd5": image_md5, "width": width, "height": height},
        )
    state["lastScreenshot"] = str(image)
    state["lastScreenshotMd5"] = image_md5
    if install_snapshot is not None:
        state["screenshotCompileInputFingerprint"] = install_snapshot["fingerprint"]
        state["screenshotInstalledApkMd5"] = state["installedApkMd5"]
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "image": str(image)}


def code_image_compare_script() -> Path:
    """定位 code-image 的独立图片对比脚本，不把对比实现复制到本 Skill。"""
    candidates: list[Path] = []
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "skills" / "code-image" / "scripts" / "compare_images.py")
    candidates.append(Path.home() / ".codex" / "skills" / "code-image" / "scripts" / "compare_images.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise PipelineError(f"找不到 code-image 图片对比脚本，已检查：{searched}")


def _latest_app_screenshot(artifact: Path, state: dict[str, Any]) -> Path:
    """只接受最近一次截图及其内容 Hash，不回退到上一轮证据。"""
    runs = (artifact / "runs").resolve()
    candidate = state.get("lastScreenshot")
    expected_md5 = state.get("lastScreenshotMd5")
    if isinstance(candidate, str) and isinstance(expected_md5, str):
        resolved = Path(candidate).expanduser().resolve()
        if runs in resolved.parents and resolved.is_file() and md5_file(resolved) == expected_md5:
            return resolved
    raise PipelineError("找不到最近一次 App 截图，请先执行 screenshot-k80")


def compare_screenshots(archive: Path, project_root: Path, app_override: Path | None = None) -> dict[str, Any]:
    """调用 code-image 的独立视觉对比脚本，生成可追溯的差异证据。"""
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] != "screenshot":
        raise PipelineError(f"当前阶段不能 compare-screenshots：{state['phase']}")
    if "screenshotCompileInputFingerprint" in state:
        install_snapshot = require_current_install_evidence(artifact, project_root, state)
        if (
            state.get("screenshotCompileInputFingerprint") != install_snapshot["fingerprint"]
            or state.get("screenshotInstalledApkMd5") != state.get("installedApkMd5")
        ):
            raise PipelineError("截图对应的源码或已安装 APK 已变化，请重新截图")
    runs = artifact / "runs"
    design = runs / "设计截图.png"
    if not design.is_file():
        raise PipelineError(f"设计截图不存在：{design}")
    cached_design = _load_cached_design(artifact, source)
    if cached_design is None or cached_design[1].resolve() != design.resolve():
        raise PipelineError("设计截图与设计解析证据不一致，请重新采集设计")
    raw_app = _latest_app_screenshot(artifact, state)
    app = raw_app if app_override is None else app_override.expanduser().resolve()
    runs = (artifact / "runs").resolve()
    if runs not in app.parents or not app.is_file():
        raise PipelineError(f"对比截图不存在或不在当前 artifact/runs 内：{app}")
    normalization: dict[str, Any] | None = None
    if app != raw_app:
        provenance = app.with_suffix(app.suffix + ".normalization.json")
        try:
            normalization = json.loads(provenance.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"归一化截图缺少有效来源证明：{provenance}") from error
        if not isinstance(normalization, dict):
            raise PipelineError(f"归一化来源证明必须是 JSON 对象：{provenance}")
        if (
            Path(str(normalization.get("design", ""))).expanduser().resolve() != design.resolve()
            or Path(str(normalization.get("app", ""))).expanduser().resolve() != raw_app.resolve()
            or Path(str(normalization.get("output", ""))).expanduser().resolve() != app
            or normalization.get("designMd5") != md5_file(design)
            or normalization.get("appMd5") != md5_file(raw_app)
            or normalization.get("outputMd5") != md5_file(app)
        ):
            raise PipelineError("归一化截图的输入/输出路径或 Hash 与当前流程不一致")
    output_dir = runs
    log_path = artifact / "logs" / "compare-images.log"
    command = [
        sys.executable,
        str(code_image_compare_script()),
        "--design",
        str(design),
        "--app",
        str(app),
        "--output-dir",
        str(output_dir),
    ]
    completed = _run_fixed(command, project_root.resolve(), log_path)
    if completed.returncode != 0:
        raise PipelineError(f"图片对比失败，日志已写入：{log_path}")
    report = output_dir / "diff.json"
    if not report.is_file():
        raise PipelineError(f"图片对比未生成差异报告：{report}")
    try:
        report_data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError(f"图片对比生成的报告不是有效 JSON：{report}") from error
    if not isinstance(report_data, dict):
        raise PipelineError(f"图片对比报告必须是 JSON 对象：{report}")
    report_data["sourceMd5"] = source["sourceMd5"]
    report_data["designScreenshot"] = str(design)
    report_data["appScreenshot"] = str(app)
    report_data["designScreenshotMd5"] = md5_file(design)
    report_data["appScreenshotMd5"] = md5_file(app)
    atomic_json(report, report_data)
    state["comparison"] = {
        "report": str(report),
        "reportMd5": md5_file(report),
        "designScreenshot": str(design),
        "appScreenshot": str(app),
        "designScreenshotMd5": report_data["designScreenshotMd5"],
        "appScreenshotMd5": report_data["appScreenshotMd5"],
        "metrics": report_data.get("metrics", {}),
    }
    if normalization is not None:
        state["comparison"]["normalization"] = normalization
    state.setdefault("history", []).append(
        {"phase": "compared", "at": utc_now(), "detail": state["comparison"]}
    )
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], **state["comparison"]}


def mark_diff(archive: Path, project_root: Path, report: Path | None, outcome: str) -> dict[str, Any]:
    if outcome not in {"pass", "repair", "stop"}:
        raise PipelineError("diff outcome 必须是 pass、repair 或 stop")
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] != "screenshot":
        raise PipelineError(f"当前阶段不能 mark-diff：{state['phase']}")
    if "screenshotCompileInputFingerprint" in state:
        install_snapshot = require_current_install_evidence(artifact, project_root, state)
        if state.get("screenshotCompileInputFingerprint") != install_snapshot["fingerprint"]:
            raise PipelineError("截图之后源码/编译输入已变化，不能登记视觉结论")
    if report is None:
        report = Path(compare_screenshots(archive, project_root)["report"])
        artifact, source, state = load_source(archive, project_root)
    report = report.expanduser().resolve()
    if artifact not in report.parents or not report.is_file():
        raise PipelineError(f"差异报告不存在：{report}")
    try:
        report_data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError(f"差异报告不是有效 JSON：{report}") from error
    if not isinstance(report_data, dict):
        raise PipelineError(f"差异报告必须是 JSON 对象：{report}")
    comparison = state.get("comparison")
    if not isinstance(comparison, dict) or Path(str(comparison.get("report", ""))).expanduser().resolve() != report:
        raise PipelineError("差异报告未由当前流程的 compare-screenshots 登记")
    if not isinstance(comparison.get("reportMd5"), str) or md5_file(report) != comparison["reportMd5"]:
        raise PipelineError("差异报告内容在 compare 后已发生变化")
    if report_data.get("sourceMd5") != source["sourceMd5"]:
        raise PipelineError("差异报告 sourceMd5 与当前 ZIP 不一致")
    if report_data.get("designScreenshot") != comparison.get("designScreenshot") or report_data.get("appScreenshot") != comparison.get("appScreenshot"):
        raise PipelineError("差异报告绑定的设计图或 App 截图与当前流程不一致")
    if (
        report_data.get("designScreenshotMd5") != comparison.get("designScreenshotMd5")
        or report_data.get("appScreenshotMd5") != comparison.get("appScreenshotMd5")
    ):
        raise PipelineError("差异报告中的截图 Hash 与当前流程登记不一致")
    design_image = Path(str(comparison["designScreenshot"])).expanduser().resolve()
    app_image = Path(str(comparison["appScreenshot"])).expanduser().resolve()
    registered_design_md5 = comparison.get("designScreenshotMd5")
    registered_app_md5 = comparison.get("appScreenshotMd5")
    if not isinstance(registered_design_md5, str) or not isinstance(registered_app_md5, str):
        raise PipelineError("当前流程未登记差异截图 Hash")
    if (
        not design_image.is_file()
        or not app_image.is_file()
        or md5_file(design_image) != registered_design_md5
        or md5_file(app_image) != registered_app_md5
    ):
        raise PipelineError("差异报告绑定的截图内容在 compare 后已发生变化")
    if not isinstance(report_data.get("metrics"), dict) or not report_data["metrics"]:
        raise PipelineError("差异报告缺少结构化 metrics，不能决定 pass/repair/stop")
    if report_data["metrics"] != comparison.get("metrics"):
        raise PipelineError("差异报告 metrics 与当前流程登记不一致")
    state["lastDiffOutcome"] = outcome
    if outcome == "repair":
        state["attempts"]["repair"] = state["attempts"].get("repair", 0) + 1
        if state["attempts"]["repair"] > 3:
            raise PipelineError("视觉修正已达到最多三轮")
        state["phase"] = "generated"
        state.setdefault("history", []).append({"phase": "repair_requested", "at": utc_now(), "detail": {"report": str(report), "round": state["attempts"]["repair"]}})
    else:
        transition(state, "diffed", {"report": str(report), "outcome": outcome})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "outcome": outcome, "report": str(report)}


def complete_pipeline(archive: Path, project_root: Path) -> dict[str, Any]:
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] != "diffed" or state.get("lastDiffOutcome") != "pass":
        raise PipelineError("只有差异报告 outcome=pass 时才能完成流程")
    if "screenshotCompileInputFingerprint" in state:
        install_snapshot = require_current_install_evidence(artifact, project_root, state)
        if state.get("screenshotCompileInputFingerprint") != install_snapshot["fingerprint"]:
            raise PipelineError("视觉通过后源码/编译输入已变化，不能完成流程")
    comparison = state.get("comparison")
    if not isinstance(comparison, dict):
        raise PipelineError("完成流程前缺少已登记差异证据")
    report = Path(str(comparison.get("report", ""))).expanduser().resolve()
    design = Path(str(comparison.get("designScreenshot", ""))).expanduser().resolve()
    app = Path(str(comparison.get("appScreenshot", ""))).expanduser().resolve()
    if (
        not report.is_file()
        or md5_file(report) != comparison.get("reportMd5")
        or not design.is_file()
        or md5_file(design) != comparison.get("designScreenshotMd5")
        or not app.is_file()
        or md5_file(app) != comparison.get("appScreenshotMd5")
    ):
        raise PipelineError("差异报告或绑定截图在 mark-diff 后已变化，不能完成流程")
    transition(state, "completed", {"reason": "visual-diff-pass"})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="固定执行蓝湖 Compose 还原流程")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--zip", required=True, type=Path)
    inspect.add_argument("--project-root", required=True, type=Path)
    inspect.add_argument("--compose", type=Path)
    select_entry = subparsers.add_parser("select-entry-html", help="登记多 HTML ZIP 的入口选择")
    select_entry.add_argument("--zip", required=True, type=Path)
    select_entry.add_argument("--project-root", required=True, type=Path)
    select_entry.add_argument("--html", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--zip", required=True, type=Path)
    validate.add_argument("--project-root", required=True, type=Path)
    validate.add_argument("--compose", required=True, type=Path)
    assets = subparsers.add_parser("assets")
    assets.add_argument("--zip", required=True, type=Path)
    assets.add_argument("--project-root", required=True, type=Path)
    assets.add_argument("--compose", required=True, type=Path)
    assets.add_argument("--apply", action="store_true")
    parse_dom_command = subparsers.add_parser("parse-dom", help="解析并保存入口 HTML 的完整 DOM IR")
    parse_dom_command.add_argument("--zip", required=True, type=Path)
    parse_dom_command.add_argument("--project-root", required=True, type=Path)
    generate = subparsers.add_parser("generate-compose", help="根据 DOM IR 和浏览器计算结果生成 Compose")
    generate.add_argument("--zip", required=True, type=Path)
    generate.add_argument("--project-root", required=True, type=Path)
    generate.add_argument("--compose", required=True, type=Path)
    fixed = subparsers.add_parser("run-fixed", help="自动执行 DOM 解析、设计采集、资源导入、Compose 生成和编译")
    fixed.add_argument("--zip", required=True, type=Path)
    fixed.add_argument("--project-root", required=True, type=Path)
    fixed.add_argument("--compose", required=True, type=Path)
    fixed.add_argument("--viewport-width", type=int, default=1600)
    fixed.add_argument("--viewport-height", type=int, default=900)
    fixed.add_argument("--dpr", type=float, default=1.0)
    restart = subparsers.add_parser("restart-generation", help="在用户纠正实现方向后重开已停止的代码生成周期")
    restart.add_argument("--zip", required=True, type=Path)
    restart.add_argument("--project-root", required=True, type=Path)
    restart.add_argument("--reason", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--zip", required=True, type=Path)
    preflight.add_argument("--project-root", required=True, type=Path)
    select_task = subparsers.add_parser("select-compile-task", help="从 Gradle 实际候选中登记用户选择的编译任务")
    select_task.add_argument("--zip", required=True, type=Path)
    select_task.add_argument("--project-root", required=True, type=Path)
    select_task.add_argument("--task", required=True)
    compile_command = subparsers.add_parser("compile")
    compile_command.add_argument("--zip", required=True, type=Path)
    compile_command.add_argument("--project-root", required=True, type=Path)
    package_command = subparsers.add_parser("package-debug", help="打包与 preflight 编译任务同变体的 APK")
    package_command.add_argument("--zip", required=True, type=Path)
    package_command.add_argument("--project-root", required=True, type=Path)
    package_command.add_argument("--apk", required=True, type=Path)
    install = subparsers.add_parser("install-k80")
    install.add_argument("--zip", required=True, type=Path)
    install.add_argument("--project-root", required=True, type=Path)
    install.add_argument("--serial", required=True)
    install.add_argument("--expected-avd", default="K80")
    install.add_argument("--apk", required=True, type=Path)
    screenshot = subparsers.add_parser("screenshot-k80")
    screenshot.add_argument("--zip", required=True, type=Path)
    screenshot.add_argument("--project-root", required=True, type=Path)
    screenshot.add_argument("--serial", required=True)
    screenshot.add_argument("--expected-avd", default="K80")
    start_design_server_command = subparsers.add_parser("start-design-server")
    start_design_server_command.add_argument("--zip", required=True, type=Path)
    start_design_server_command.add_argument("--project-root", required=True, type=Path)
    start_design_server_command.add_argument("--port", type=int, default=0)
    start_design_server_command.add_argument("--viewport-width", type=int, default=1600)
    start_design_server_command.add_argument("--viewport-height", type=int, default=900)
    start_design_server_command.add_argument("--dpr", type=float, default=1.0)
    capture_design = subparsers.add_parser("采集设计", help="采集浏览器最终布局并写入设计解析文件")
    capture_design.add_argument("--zip", required=True, type=Path)
    capture_design.add_argument("--project-root", required=True, type=Path)
    capture_design.add_argument("--viewport-width", type=int, default=1600)
    capture_design.add_argument("--viewport-height", type=int, default=900)
    capture_design.add_argument("--dpr", type=float, default=1.0)
    screenshot_design = subparsers.add_parser("screenshot-design")
    screenshot_design.add_argument("--zip", required=True, type=Path)
    screenshot_design.add_argument("--project-root", required=True, type=Path)
    screenshot_design.add_argument("--image", required=True, type=Path)
    stop_design_server_command = subparsers.add_parser("stop-design-server")
    stop_design_server_command.add_argument("--zip", required=True, type=Path)
    stop_design_server_command.add_argument("--project-root", required=True, type=Path)
    compare = subparsers.add_parser("compare-screenshots", help="调用 code-image 独立视觉对比脚本")
    compare.add_argument("--zip", required=True, type=Path)
    compare.add_argument("--project-root", required=True, type=Path)
    compare.add_argument("--app", type=Path, help="已归一化的 App 截图；省略时使用最近一次 screenshot-k80 原图")
    diff = subparsers.add_parser("mark-diff")
    diff.add_argument("--zip", required=True, type=Path)
    diff.add_argument("--project-root", required=True, type=Path)
    diff.add_argument("--report", type=Path, help="已有差异报告；省略时自动调用 compare-screenshots")
    diff.add_argument("--outcome", required=True, choices=("pass", "repair", "stop"))
    complete = subparsers.add_parser("complete")
    complete.add_argument("--zip", required=True, type=Path)
    complete.add_argument("--project-root", required=True, type=Path)
    decision = subparsers.add_parser("record-decision")
    decision.add_argument("--zip", required=True, type=Path)
    decision.add_argument("--project-root", required=True, type=Path)
    decision.add_argument("--decision", required=True, type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("--zip", required=True, type=Path)
    status.add_argument("--project-root", required=True, type=Path)
    return parser


def persist_user_input_request(args: argparse.Namespace, question: str) -> Path | None:
    """尽力把退出码 2 的问题固化到本次 ZIP artifact，避免只存在于终端滚屏。"""
    archive = getattr(args, "zip", None)
    project_root = getattr(args, "project_root", None)
    if not isinstance(archive, Path) or not isinstance(project_root, Path):
        return None
    try:
        archive = archive.expanduser().resolve()
        project_root = project_root.expanduser().resolve()
        source_sha = md5_file(archive)
        request = artifact_dir(archive, project_root, source_sha) / "needs-user-input.json"
        atomic_json(
            request,
            {
                "status": "needs_user_input",
                "command": str(getattr(args, "command", "unknown")),
                "question": question,
                "sourcePath": str(archive),
                "sourceMd5": source_sha,
                "requestedAt": utc_now(),
            },
        )
        return request
    except (OSError, ValueError, zipfile.BadZipFile):
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_archive(args.zip, args.project_root, args.compose)
        elif args.command == "select-entry-html":
            result = select_entry_html(args.zip, args.project_root, args.html)
        elif args.command == "validate":
            result = validate_project(args.zip, args.project_root, args.compose)
        elif args.command == "assets":
            result = import_assets(args.zip, args.project_root, args.compose, apply=args.apply)
        elif args.command == "parse-dom":
            result = parse_dom(args.zip, args.project_root)
        elif args.command == "generate-compose":
            result = generate_compose_from_dom(args.zip, args.project_root, args.compose)
        elif args.command == "run-fixed":
            result = run_fixed_pipeline(
                args.zip,
                args.project_root,
                args.compose,
                args.viewport_width,
                args.viewport_height,
                args.dpr,
            )
        elif args.command == "restart-generation":
            result = restart_generation_cycle(args.zip, args.project_root, args.reason)
        elif args.command == "preflight":
            result = preflight_project(args.zip, args.project_root)
        elif args.command == "select-compile-task":
            result = select_compile_task(args.zip, args.project_root, args.task)
        elif args.command == "compile":
            result = compile_project(args.zip, args.project_root)
        elif args.command == "package-debug":
            result = package_debug(args.zip, args.project_root, args.apk)
        elif args.command == "install-k80":
            result = install_k80(args.zip, args.project_root, args.serial, args.expected_avd, args.apk)
        elif args.command == "screenshot-k80":
            result = screenshot_k80(args.zip, args.project_root, args.serial, args.expected_avd)
        elif args.command == "start-design-server":
            result = start_design_server(
                args.zip,
                args.project_root,
                args.port,
                args.viewport_width,
                args.viewport_height,
                args.dpr,
            )
        elif args.command == "采集设计":
            result = capture_rendered_design(
                args.zip,
                args.project_root,
                args.viewport_width,
                args.viewport_height,
                args.dpr,
            )
        elif args.command == "screenshot-design":
            result = complete_design_screenshot(args.zip, args.project_root, args.image)
        elif args.command == "stop-design-server":
            result = stop_design_server(args.zip, args.project_root)
        elif args.command == "compare-screenshots":
            result = compare_screenshots(args.zip, args.project_root, args.app)
        elif args.command == "mark-diff":
            result = mark_diff(args.zip, args.project_root, args.report, args.outcome)
        elif args.command == "complete":
            result = complete_pipeline(args.zip, args.project_root)
        elif args.command == "record-decision":
            result = record_decision(args.zip, args.project_root, args.decision)
        elif args.command == "status":
            artifact, source, state = load_source(args.zip, args.project_root)
            result = {"artifactPath": str(artifact), "sourceMd5": source["sourceMd5"], **state}
        else:
            raise PipelineError(f"未知命令：{args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except UserInputRequired as error:
        payload = {"status": "needs_user_input", "question": str(error)}
        request = persist_user_input_request(args, str(error))
        if request is not None:
            payload["requestPath"] = str(request)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2
    except PipelineError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "blocked", "error": f"输入或状态文件无法处理：{error}"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
