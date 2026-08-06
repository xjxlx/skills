#!/usr/bin/env python3
"""按单个图片输入生成 Android 资源名，并维护项目内映射。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path
    original_path: str
    original_name: str
    output_name: str
    identity: str
    resource_family: str
    compose_file: str | None
    file_hash: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snake_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", ascii_value)
    ascii_value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", ascii_value)
    return re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value)).strip("_").lower()


def normalize_namespace(compose_path: Path) -> str:
    stem = re.sub(r"(?i)(?:layout|page)$", "", compose_path.stem)
    token = snake_token(stem)
    if not token:
        token = "screen_" + hashlib.sha256(compose_path.stem.encode()).hexdigest()[:6]
    return "screen_" + token if token[0].isdigit() else token


def normalize_asset_stem(original_stem: str) -> str:
    without_copy_suffix = re.sub(r"(?:\(\d+\)|[_-]\d+)$", "", original_stem)
    token = snake_token(without_copy_suffix)
    if not token:
        token = "image_" + hashlib.sha256(original_stem.encode()).hexdigest()[:6]
    return "image_" + token if token[0].isdigit() else token


def find_project_root(image_path: Path) -> Path:
    resolved = image_path.resolve()
    for parent in (resolved.parent, *resolved.parents):
        if (parent / ".git").exists() or (parent / "settings.gradle").exists() or (parent / "settings.gradle.kts").exists():
            return parent
        if parent.name == "app":
            return parent.parent
    return resolved.parent


def relative_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resource_family_root(image_path: Path) -> Path:
    parent = image_path.parent
    if parent.name != "mipmap" and not parent.name.startswith("mipmap-"):
        raise ValueError(f"图片必须位于 mipmap 资源目录：{image_path}")
    return parent.parent


def resource_directories(image_path: Path) -> list[Path]:
    root = resource_family_root(image_path)
    return sorted(
        directory
        for directory in root.iterdir()
        if directory.is_dir() and (directory.name == "mipmap" or directory.name.startswith("mipmap-"))
    )


def load_resources(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "resources": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"无法读取资源记录：{path}") from error
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise ValueError(f"资源记录格式错误：{path}")
    return data


def _find_record(records: list[dict], current_path: str, file_hash: str, family: str) -> dict | None:
    for record in records:
        if current_path == record.get("outputPath"):
            return record
        if current_path == record.get("originalPath") and record.get("originalHash") == file_hash:
            return record
    matched = [
        record
        for record in records
        if record.get("originalHash") == file_hash and record.get("resourceFamily") == family
    ]
    return matched[0] if len(matched) == 1 else None


def _is_normalized(name: str) -> bool:
    return Path(name).stem.lower().startswith("icon_")


def _has_conflict(candidate: str, source: Path, directories: list[Path], record: dict | None) -> bool:
    for directory in directories:
        target = directory / candidate
        if not target.exists() or target.resolve() == source.resolve():
            continue
        if record and record.get("outputName") == candidate and directory != source.parent:
            continue
        return True
    return False


def build_plan(
    image_path: Path,
    project_root: Path,
    compose_path: Path | None = None,
    resources_path: Path | None = None,
) -> RenamePlan:
    source = Path(image_path).resolve()
    project_root = Path(project_root).resolve()
    if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"不是支持的图片文件：{source}")
    try:
        source.relative_to(project_root)
    except ValueError as error:
        raise ValueError(f"图片位于项目外：{source}") from error

    directories = resource_directories(source)
    family = relative_path(resource_family_root(source), project_root)
    current_path = relative_path(source, project_root)
    file_hash = sha256_file(source)
    resources_path = resources_path or project_root / ".code-image/resources.json"
    manifest = load_resources(resources_path)
    record = _find_record(manifest["resources"], current_path, file_hash, family)
    original_path = record.get("originalPath") if record else current_path
    original_name = record.get("originalName") if record else source.name
    recorded_compose = record.get("composeFile") if record else None
    compose_file = relative_path(compose_path, project_root) if compose_path else recorded_compose

    if record and compose_path is None:
        output_name = record["outputName"]
    elif _is_normalized(source.name):
        output_name = source.name
    else:
        namespace = normalize_namespace(compose_path) if compose_path else None
        prefix = f"icon_{namespace}_" if namespace else "icon_"
        output_name = prefix + normalize_asset_stem(Path(original_name).stem) + source.suffix.lower()

    if _has_conflict(output_name, source, directories, record):
        base = Path(output_name).stem
        suffix = hashlib.sha256(f"{family}:{original_name}:{file_hash}".encode()).hexdigest()[:6]
        output_name = f"{base}_{suffix}{source.suffix.lower()}"
        if _has_conflict(output_name, source, directories, record):
            raise FileExistsError(f"目标资源名已被占用：{output_name}")

    identity = record.get("identity") if record else f"{family}:{current_path}:{file_hash}"
    return RenamePlan(
        source=source,
        target=source.with_name(output_name),
        original_path=original_path,
        original_name=original_name,
        output_name=output_name,
        identity=identity,
        resource_family=family,
        compose_file=compose_file,
        file_hash=file_hash,
    )


def write_resources(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def apply_plan(plan: RenamePlan, resources_path: Path, project_root: Path) -> None:
    if plan.source != plan.target:
        if plan.target.exists():
            raise FileExistsError(f"目标文件已存在，拒绝覆盖：{plan.target}")
        os.replace(plan.source, plan.target)

    manifest = load_resources(resources_path)
    records = [record for record in manifest["resources"] if record.get("identity") != plan.identity]
    records.append(
        {
            "identity": plan.identity,
            "originalPath": plan.original_path,
            "originalName": plan.original_name,
            "originalHash": plan.file_hash,
            "outputPath": relative_path(plan.target, project_root),
            "outputName": plan.output_name,
            "composeFile": plan.compose_file,
            "resourceFamily": plan.resource_family,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    manifest["version"] = 1
    manifest["resources"] = sorted(records, key=lambda record: record["identity"])
    write_resources(resources_path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="规范单个 Android 图片资源名并记录映射")
    parser.add_argument(
        "--image",
        required=True,
        action="append",
        help="待处理的单个图片文件路径；每次只能提供一次",
    )
    parser.add_argument("--compose", help="可选的 Compose 布局文件，用于生成页面命名空间")
    parser.add_argument("--project-root", help="项目根目录，默认从图片路径推断")
    parser.add_argument("--apply", action="store_true", help="实际重命名；默认只输出预览")
    args = parser.parse_args()

    if len(args.image) != 1:
        parser.error("每次只允许一个 --image")
    image = Path(args.image[0]).resolve()
    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root(image)
    compose = Path(args.compose).resolve() if args.compose else None
    if compose and not compose.is_file():
        raise ValueError(f"Compose 文件不存在：{compose}")
    resources_path = project_root / ".code-image/resources.json"
    plan = build_plan(image, project_root, compose, resources_path)
    marker = "保持" if plan.source == plan.target else "重命名"
    print(f"{marker}: {plan.source.name} -> {plan.output_name}")
    print(f"  Hash: {plan.file_hash[:12]} | Compose: {plan.compose_file or '未提供'}")
    if args.apply:
        apply_plan(plan, resources_path, project_root)
        print(f"已更新资源记录：{resources_path}")
    else:
        print("当前为 Dry Run，确认名称后追加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
