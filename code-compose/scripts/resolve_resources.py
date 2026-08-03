#!/usr/bin/env python3
"""按 code-image 缓存解析蓝湖原始图片对应的 Android 资源。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
MIPMAP_PREFIX = "mipmap"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取资源缓存 {path}: {error}") from error


def _relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def discover_resource_files(project_root: Path, resource_dirs: list[Path] | None = None) -> list[Path]:
    """只扫描 mipmap 资源族；调用方可用 --resource-dir 限定范围。"""
    roots = resource_dirs or [
        project_root / "app/src/main/res",
        project_root / "res",
    ]
    files = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in IMAGE_EXTENSIONS
                and any(parent.name.startswith(MIPMAP_PREFIX) for parent in path.parents)
            ):
                files.append(path.resolve())
    return sorted(set(files), key=lambda path: path.as_posix())


def _input_variants(original: str) -> list[str]:
    raw = original.strip().replace("\\", "/")
    if not raw:
        return []
    parsed = urlparse(raw)
    decoded = unquote(raw)
    values = [raw, decoded]
    if parsed.path:
        values.extend([parsed.path, unquote(parsed.path)])
    values.extend([PurePosixPath(value).name for value in list(values)])
    variants = []
    for value in values:
        value = value.strip().replace("\\", "/")
        if value and value not in variants:
            variants.append(value)
        stem = Path(value).stem
        if stem and stem not in variants:
            variants.append(stem)
    return variants


def _match_score(candidate: str, variants: list[str]) -> int | None:
    candidate = candidate.replace("\\", "/")
    candidate_name = PurePosixPath(candidate).name
    candidate_stem = Path(candidate_name).stem
    for index, variant in enumerate(variants):
        if candidate == variant:
            return index
    for index, variant in enumerate(variants):
        if candidate_name == PurePosixPath(variant).name:
            return 100 + index
    for index, variant in enumerate(variants):
        if candidate_stem == Path(PurePosixPath(variant).name).stem:
            return 200 + index
    return None


def _resource_name(path_or_name: str) -> str:
    return Path(PurePosixPath(path_or_name).name).stem


def _existing_paths(output: str, files: list[Path], project_root: Path) -> list[Path]:
    output_path = Path(output)
    direct = output_path if output_path.is_absolute() else project_root / output_path
    if direct.is_file():
        return [direct.resolve()]
    output_name = PurePosixPath(output).name
    exact = [path for path in files if path.name == output_name]
    if exact:
        return exact
    stem = Path(output_name).stem
    return [path for path in files if path.stem == stem]


def resolve_resource(
    project_root: Path,
    original: str,
    resource_dirs: list[Path] | None = None,
    mapping_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict:
    """返回当前资源名和实际路径；无法唯一解析时抛出 ValueError。"""
    project_root = project_root.resolve()
    files = discover_resource_files(project_root, resource_dirs)
    variants = _input_variants(original)
    if not variants:
        raise ValueError("原始图片名不能为空")

    # 1. 先看仍保留原始文件名的本地资源，避免缓存过期时误指向其他文件。
    local_matches = [
        path for path in files if _match_score(path.name, variants) is not None
    ]
    local_names = {_resource_name(path.name) for path in local_matches}
    if len(local_names) == 1 and local_matches:
        path = local_matches[0]
        return {
            "source": "local",
            "original": original,
            "resource_name": path.name,
            "resource_stem": _resource_name(path.name),
            "path": _relative(path, project_root),
        }
    if len(local_names) > 1:
        paths = ", ".join(_relative(path, project_root) for path in local_matches)
        raise ValueError(f"原始图片名对应多个本地资源：{original} -> {paths}")

    mapping_path = mapping_path or project_root / ".codex/lanhu-resources.json"
    manifest_path = manifest_path or project_root / ".codex/code-image-manifest.json"
    mapping = load_json(mapping_path, {})
    if not isinstance(mapping, dict):
        raise ValueError(f"资源映射格式错误：{mapping_path}")

    mapped = []
    for key, output in mapping.items():
        if not isinstance(key, str) or not isinstance(output, str):
            continue
        score = _match_score(key, variants)
        if score is None:
            continue
        for path in _existing_paths(output, files, project_root):
            mapped.append((score, key, output, path))
    mapped.sort(key=lambda item: (item[0], item[1], item[3].as_posix()))
    mapped_names = {Path(item[2]).stem for item in mapped}
    if len(mapped_names) == 1 and mapped:
        _, _, output, path = mapped[0]
        return {
            "source": "lanhu-resources",
            "original": original,
            "resource_name": Path(output).name,
            "resource_stem": _resource_name(output),
            "path": _relative(path, project_root),
        }
    if len(mapped_names) > 1:
        candidates = ", ".join(
            f"{item[1]} -> {_relative(item[3], project_root)}" for item in mapped
        )
        raise ValueError(f"缓存映射存在多个候选：{original} -> {candidates}")

    # 3. 映射不存在时再从完整 manifest 回退，仍要求 currentPath 实际存在。
    manifest = load_json(manifest_path, {})
    records = manifest.get("resources", []) if isinstance(manifest, dict) else []
    manifest_matches = []
    for record in records:
        if not isinstance(record, dict):
            continue
        names = [record.get("originalName"), record.get("previousOriginalName")]
        score = min(
            (value for value in (_match_score(name, variants) for name in names if isinstance(name, str)) if value is not None),
            default=None,
        )
        if score is None:
            continue
        output = record.get("outputName") or record.get("currentPath")
        current = record.get("currentPath") or record.get("outputPath")
        if not isinstance(output, str) or not isinstance(current, str):
            continue
        paths = _existing_paths(current, files, project_root)
        if paths:
            manifest_matches.append((score, output, paths[0]))
    manifest_names = {Path(item[1]).stem for item in manifest_matches}
    if len(manifest_names) == 1 and manifest_matches:
        _, output, path = sorted(manifest_matches, key=lambda item: (item[0], item[2].as_posix()))[0]
        return {
            "source": "manifest",
            "original": original,
            "resource_name": Path(output).name,
            "resource_stem": _resource_name(output),
            "path": _relative(path, project_root),
        }
    if len(manifest_names) > 1:
        candidates = ", ".join(
            f"{item[1]} -> {_relative(item[2], project_root)}" for item in manifest_matches
        )
        raise ValueError(f"manifest 存在多个候选：{original} -> {candidates}")

    raise FileNotFoundError(f"未找到原始图片对应的本地资源：{original}")


def main() -> int:
    parser = argparse.ArgumentParser(description="解析蓝湖原始图片对应的 Android 资源")
    parser.add_argument("--project-root", default=".", help="项目根目录，默认当前目录")
    parser.add_argument("--original", required=True, help="蓝湖原始文件名、路径或 URL")
    parser.add_argument("--resource-dir", action="append", help="额外限定的 mipmap 资源目录，可重复")
    parser.add_argument("--mapping", help="lanhu-resources.json 路径")
    parser.add_argument("--manifest", help="code-image-manifest.json 路径")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    dirs = [Path(value).resolve() for value in args.resource_dir] if args.resource_dir else None
    try:
        result = resolve_resource(
            root,
            args.original,
            resource_dirs=dirs,
            mapping_path=Path(args.mapping).resolve() if args.mapping else None,
            manifest_path=Path(args.manifest).resolve() if args.manifest else None,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
