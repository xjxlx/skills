#!/usr/bin/env python3
"""导入单张图片或 ZIP mipmap 资源，并规范 Android 资源名。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path
    original_path: str
    original_name: str
    output_name: str
    identity: str
    compose_file: str | None
    file_hash: str
    previous_target: Path | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return token or "design"


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


def normalize_asset_stem(original_stem: str, remove_copy_suffix: bool = True) -> str:
    without_copy_suffix = (
        re.sub(r"(?:\(\d+\)|[_-]\d+)$", "", original_stem)
        if remove_copy_suffix
        else original_stem
    )
    token = snake_token(without_copy_suffix)
    if not token:
        token = "image_" + hashlib.sha256(original_stem.encode()).hexdigest()[:6]
    return "image_" + token if token[0].isdigit() else token


def find_project_root(source_path: Path) -> Path:
    resolved = source_path.resolve()
    for parent in (resolved.parent, *resolved.parents):
        if (parent / ".git").exists() or (parent / "settings.gradle").exists() or (parent / "settings.gradle.kts").exists():
            return parent
        if parent.name == "app":
            return parent.parent
    return Path.cwd()


def relative_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


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


def resources_path_for_source(project_root: Path, source_path: Path) -> Path:
    """以稳定来源身份定位可复用的资源清单。"""
    source_hash = sha256_file(source_path)
    prefix = f"{safe_token(source_path.stem)}-{source_hash[:6]}"
    return project_root / ".code-image" / f"{prefix}.resources.json"


def requested_resources_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser().resolve()
    records_directory = (project_root / ".code-image").resolve()
    if path.parent != records_directory or not re.fullmatch(
        r".+-[0-9a-f]{6}\.resources\.json", path.name
    ):
        raise ValueError(
            "--resources-file 必须是项目 .code-image/ 下 "
            "<来源名>-<hash前6位>.resources.json 格式的来源清单"
        )
    return path


def _find_record(records: list[dict], current_path: str, file_hash: str) -> dict | None:
    for record in records:
        if current_path == record.get("originalPath") and file_hash == record.get("originalHash"):
            return record
        if current_path == record.get("outputPath") and file_hash == record.get("originalHash"):
            return record
    return None


def _record_output_path(record: dict, project_root: Path) -> Path | None:
    output_path = record.get("outputPath")
    if not isinstance(output_path, str) or not output_path:
        return None
    path = Path(output_path)
    return path if path.is_absolute() else project_root / path


def _find_record_by_hash(
    records: list[dict],
    file_hash: str,
    target_dir: Path,
    project_root: Path,
) -> dict | None:
    """同一来源清单内的同密度重复切图复用首个已记录资源。"""
    for record in records:
        output_path = _record_output_path(record, project_root)
        if (
            record.get("originalHash") == file_hash
            and output_path is not None
            and output_path.parent.resolve() == target_dir.resolve()
        ):
            return record
    return None


def _is_normalized(name: str) -> bool:
    return Path(name).stem.lower().startswith("icon_")


def next_output_path(
    target_dir: Path,
    output_name: str,
    source: Path,
    reserved: set[Path],
    replaceable: set[Path],
) -> Path:
    candidate = target_dir / output_name
    if (
        (not candidate.exists() or candidate.resolve() in replaceable)
        and candidate.resolve() not in reserved
    ):
        return candidate
    if candidate.resolve() == source.resolve() and candidate.resolve() not in reserved:
        return candidate
    base = Path(output_name).stem
    extension = Path(output_name).suffix
    number = 1
    while True:
        candidate = target_dir / f"{base}_{number}{extension}"
        if not candidate.exists() and candidate.resolve() not in reserved:
            return candidate
        number += 1


def build_plan(
    source_path: Path,
    target_dir: Path,
    project_root: Path,
    compose_path: Path | None,
    resources_path: Path,
    reserved: set[Path] | None = None,
    asset_name: str | None = None,
) -> RenamePlan:
    source = Path(source_path).resolve()
    if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"不是支持的图片文件：{source}")
    target_dir = Path(target_dir).resolve()
    project_root = Path(project_root).resolve()
    current_path = relative_path(source, project_root)
    file_hash = sha256_file(source)
    manifest = load_resources(resources_path)
    record = _find_record(manifest["resources"], current_path, file_hash)
    if record is None:
        record = _find_record_by_hash(manifest["resources"], file_hash, target_dir, project_root)
    original_path = record.get("originalPath") if record else current_path
    original_name = record.get("originalName") if record else source.name
    compose_file = relative_path(compose_path, project_root) if compose_path else (record.get("composeFile") if record else None)

    previous_target = _record_output_path(record, project_root) if record else None
    if record:
        output_name = record["outputName"]
    elif _is_normalized(source.name):
        output_name = source.name
    else:
        namespace = normalize_namespace(compose_path) if compose_path else None
        prefix = f"icon_{namespace}_" if namespace else "icon_"
        name_source = asset_name if asset_name else Path(original_name).stem
        output_name = (
            prefix
            + normalize_asset_stem(name_source, remove_copy_suffix=asset_name is None)
            + source.suffix.lower()
        )

    replaceable = {previous_target.resolve()} if previous_target else set()
    target = next_output_path(
        target_dir,
        output_name,
        source,
        set() if record else reserved or set(),
        replaceable,
    )
    identity = record.get("identity") if record else f"{original_path}:{file_hash}"
    return RenamePlan(
        source=source,
        target=target,
        original_path=original_path,
        original_name=original_name,
        output_name=target.name,
        identity=identity,
        compose_file=compose_file,
        file_hash=file_hash,
        previous_target=previous_target,
    )


def write_resources(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def apply_plans(plans: list[RenamePlan], resources_path: Path, project_root: Path) -> None:
    manifest = load_resources(resources_path)
    records = {record.get("identity"): record for record in manifest["resources"]}
    for plan in plans:
        plan.target.parent.mkdir(parents=True, exist_ok=True)
        if plan.source.resolve() != plan.target.resolve():
            if plan.target.exists() and plan.previous_target != plan.target:
                if sha256_file(plan.target) != plan.file_hash:
                    raise FileExistsError(f"目标文件已存在，拒绝覆盖：{plan.target}")
            else:
                shutil.copyfile(plan.source, plan.target)
        if plan.previous_target and plan.previous_target.resolve() != plan.target.resolve():
            if plan.previous_target.is_file():
                plan.previous_target.unlink()
        records[plan.identity] = {
            "identity": plan.identity,
            "originalPath": plan.original_path,
            "originalName": plan.original_name,
            "originalHash": plan.file_hash,
            "outputPath": relative_path(plan.target, project_root),
            "outputName": plan.output_name,
            "composeFile": plan.compose_file,
        }
    manifest["version"] = 1
    manifest["resources"] = sorted(records.values(), key=lambda record: record["identity"])
    write_resources(resources_path, manifest)


def _safe_zip_entries(archive: ZipFile):
    entries = []
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        mode = (entry.external_attr >> 16) & 0o170000
        if path.is_absolute() or ".." in path.parts or mode == 0o120000:
            raise ValueError(f"ZIP 包含不安全路径或符号链接：{entry.filename}")
        entries.append(entry)
    return entries


def archive_mipmap_directory(entry_name: str) -> str | None:
    path = PurePosixPath(entry_name)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    for part in reversed(path.parts[:-1]):
        if part == "mipmap" or part.startswith("mipmap-"):
            return part
    return None


def extract_zip_to_downloads(zip_path: Path) -> Path:
    source_hash = sha256_file(zip_path)
    destination = Path.home() / "Downloads" / f"{safe_token(zip_path.stem)}-{source_hash[:6]}"
    with ZipFile(zip_path) as archive:
        entries = _safe_zip_entries(archive)
        if not any(
            not entry.is_dir() and archive_mipmap_directory(entry.filename)
            for entry in entries
        ):
            raise ValueError("ZIP 不含 mipmap 图片，不能按 ZIP 处理；请传入单个图片使用 --image")
        for entry in entries:
            if entry.is_dir():
                continue
            target = destination / PurePosixPath(entry.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as input_stream, target.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream)
    return destination


def mipmap_directory_name(path: Path, extraction_root: Path) -> str | None:
    for parent in (path.parent, *path.parents):
        if parent == extraction_root.parent:
            return None
        if parent.name == "mipmap" or parent.name.startswith("mipmap-"):
            return parent.name
    return None


def zip_image_sources(extraction_root: Path) -> list[tuple[Path, str]]:
    sources = []
    for path in sorted(extraction_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        directory_name = mipmap_directory_name(path, extraction_root)
        if directory_name:
            sources.append((path, directory_name))
    if not sources:
        raise ValueError("ZIP 中没有位于 mipmap 目录的图片")
    return sources


def _print_plans(plans: list[RenamePlan]) -> None:
    for plan in plans:
        print(f"导入: {plan.source.name} -> {plan.target}")
        print(f"  Hash: {plan.file_hash[:12]} | Compose: {plan.compose_file or '未提供'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="导入并规范 Android 图片资源名")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--image", action="append", help="单个图片文件路径；每次只能提供一次")
    source_group.add_argument("--zip", action="append", help="包含 mipmap 图片目录的 ZIP；每次只能提供一次")
    parser.add_argument("--compose", help="可选的 Compose 布局文件，用于生成页面命名空间")
    parser.add_argument("--asset-name", help="可选的语义资源名，仅支持单图导入")
    parser.add_argument("--project-root", default=".", help="Android 项目根目录，默认当前目录")
    parser.add_argument(
        "--resources-file",
        help="可选的新资源清单路径；仅允许项目 .code-image/ 下的专属文件",
    )
    parser.add_argument("--apply", action="store_true", help="实际复制/改名；默认只输出预览")
    args = parser.parse_args()
    if args.image and len(args.image) != 1:
        parser.error("每次只允许一个 --image")
    if args.zip and len(args.zip) != 1:
        parser.error("每次只允许一个 --zip")
    if args.asset_name and args.zip:
        parser.error("--asset-name 仅支持与 --image 一起使用")

    project_root = Path(args.project_root).resolve()
    compose = Path(args.compose).resolve() if args.compose else None
    if compose and not compose.is_file():
        raise ValueError(f"Compose 文件不存在：{compose}")
    source_path = Path(args.image[0] if args.image else args.zip[0]).resolve()
    resources_path = (
        requested_resources_path(args.resources_file, project_root)
        if args.resources_file
        else resources_path_for_source(project_root, source_path)
    )
    res_root = project_root / "app/src/main/res"

    if args.image:
        source = source_path
        plans = [
            build_plan(
                source,
                res_root / "mipmap-xxhdpi",
                project_root,
                compose,
                resources_path,
                asset_name=args.asset_name,
            )
        ]
    else:
        extraction_root = extract_zip_to_downloads(source_path)
        reserved: set[Path] = set()
        imported_hashes: set[tuple[Path, str]] = set()
        plans = []
        for source, directory_name in zip_image_sources(extraction_root):
            target_dir = (res_root / directory_name).resolve()
            source_hash = sha256_file(source)
            if (target_dir, source_hash) in imported_hashes:
                continue
            plan = build_plan(source, res_root / directory_name, project_root, compose, resources_path, reserved)
            plans.append(plan)
            reserved.add(plan.target.resolve())
            imported_hashes.add((target_dir, source_hash))

    _print_plans(plans)
    if args.apply:
        apply_plans(plans, resources_path, project_root)
        print(f"已更新资源记录：{resources_path}")
    else:
        print("当前为 Dry Run，确认名称后追加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
