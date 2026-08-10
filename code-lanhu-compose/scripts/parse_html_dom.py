#!/usr/bin/env python3
"""把蓝湖入口 HTML 的完整 DOM 和本地资源引用固化为稳定 JSON。"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class DomParseError(ValueError):
    """HTML DOM 或本地资源引用无法安全解析。"""


VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
URL_PATTERN = re.compile(r"url\(\s*([^)]*?)\s*\)", re.IGNORECASE)


def _normalise_zip_path(value: str) -> str:
    value = value.replace("\\", "/")
    if value.startswith("/") or ".." in Path(value).parts:
        raise DomParseError(f"资源路径不安全：{value}")
    return value.lstrip("./")


def _resolve_local_path(document_path: str, raw: str, available: set[str]) -> str | None:
    reference = raw.strip().strip("'\"").split("?", 1)[0].split("#", 1)[0]
    if not reference or reference.startswith("data:") or "://" in reference:
        return None
    base = posixpath.dirname(document_path)
    resolved = posixpath.normpath(posixpath.join(base, reference.replace("\\", "/")))
    if resolved == ".." or resolved.startswith("../"):
        raise DomParseError(f"资源路径越过 ZIP 根目录：{raw}")
    resolved = _normalise_zip_path(resolved)
    if resolved not in available:
        raise DomParseError(f"HTML 引用的本地资源不存在：{resolved}")
    return resolved


class _DomBuilder(HTMLParser):
    def __init__(self, html_path: str, available: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.html_path = html_path
        self.available = available
        self.nodes: list[dict[str, Any]] = []
        self.stack: list[str] = []
        self.resources: list[dict[str, Any]] = []
        self._add_node("document", None, {}, "")

    def _add_node(self, tag: str, parent_id: str | None, attributes: dict[str, str], text: str) -> str:
        node_id = f"n{len(self.nodes)}"
        node = {
            "nodeId": node_id,
            "parentId": parent_id,
            "tag": tag.lower(),
            "attributes": attributes,
            "classTokens": attributes.get("class", "").split(),
            "directText": text,
            "childrenIds": [],
        }
        self.nodes.append(node)
        if parent_id is not None:
            parent = self.nodes[int(parent_id[1:])]
            parent["childrenIds"].append(node_id)
        return node_id

    def _parent(self) -> str:
        return self.stack[-1] if self.stack else "n0"

    def _attrs(self, attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name.lower(): value or "" for name, value in attrs}

    def _resource(self, kind: str, node_id: str, source: str) -> None:
        resolved = _resolve_local_path(self.html_path, source, self.available)
        item: dict[str, Any] = {"kind": kind, "source": source, "nodeId": node_id}
        if resolved is not None:
            item["resolvedPath"] = resolved
        self.resources.append(item)

    def _collect_resources(self, tag: str, node_id: str, attributes: dict[str, str]) -> None:
        if tag == "link" and "stylesheet" in attributes.get("rel", "").lower().split() and attributes.get("href"):
            self._resource("stylesheet", node_id, attributes["href"])
        if tag in {"img", "source", "video", "audio", "iframe", "script"}:
            attribute = "src"
            if tag == "video" and not attributes.get(attribute):
                attribute = "poster"
            if attributes.get(attribute):
                self._resource("image" if tag in {"img", "source", "video"} else "source", node_id, attributes[attribute])
        if attributes.get("srcset"):
            for source in attributes["srcset"].split(","):
                self._resource("image", node_id, source.strip().split()[0])
        for source in URL_PATTERN.findall(attributes.get("style", "")):
            self._resource("style-url", node_id, source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = self._attrs(attrs)
        node_id = self._add_node(tag, self._parent(), attributes, "")
        self._collect_resources(tag.lower(), node_id, attributes)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node_id)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = self._attrs(attrs)
        node_id = self._add_node(tag, self._parent(), attributes, "")
        self._collect_resources(tag.lower(), node_id, attributes)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.nodes[int(self.stack[index][1:])]["tag"] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not data or not self.stack:
            return
        node = self.nodes[int(self.stack[-1][1:])]
        node["directText"] += data

    def handle_comment(self, data: str) -> None:
        self._add_node("#comment", self._parent(), {}, data)

    def handle_decl(self, decl: str) -> None:
        self._add_node("#doctype", self._parent(), {}, decl)


def parse_html_archive(archive: Path, html_path: str | None = None) -> dict[str, Any]:
    """读取 ZIP 中指定入口 HTML，返回完整 DOM IR，不依赖 class 语义。"""
    archive = archive.expanduser().resolve()
    with zipfile.ZipFile(archive) as zipped:
        available = {_normalise_zip_path(info.filename) for info in zipped.infolist() if not info.is_dir()}
        html_candidates = sorted(path for path in available if path.lower().endswith((".html", ".htm")))
        if html_path is None:
            if len(html_candidates) != 1:
                raise DomParseError(f"无法唯一确定入口 HTML：发现 {len(html_candidates)} 个")
            html_path = html_candidates[0]
        html_path = _normalise_zip_path(html_path)
        if html_path not in available:
            raise DomParseError(f"入口 HTML 不存在：{html_path}")
        html = zipped.read(html_path).decode("utf-8", errors="replace")
    parser = _DomBuilder(html_path, available)
    parser.feed(html)
    parser.close()
    return {
        "version": 1,
        "htmlPath": html_path,
        "rootNodeId": "n0",
        "nodes": parser.nodes,
        "resources": parser.resources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="解析蓝湖 HTML 的完整 DOM 和本地资源引用")
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--html", type=str)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = parse_html_archive(args.zip, args.html)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output.resolve()), "nodeCount": len(result["nodes"]), "resourceCount": len(result["resources"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
