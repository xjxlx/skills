#!/usr/bin/env python3
"""为蓝湖图片生成稳定的 Android 资源名，并维护 code-compose 可用的映射。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
MIPMAP_PREFIX = "mipmap-"


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path
    original_name: str
    output_name: str
    identity: str
    resource_family: str
    compose_file: str
    file_hash: str
    previous_output_name: str | None = None
    previous_original_name: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ascii_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]", "", ascii_value).lower()


def _snake_token(value: str) -> str:
    """将英文、数字和分隔符转换为 Android 资源常用的 snake_case。"""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", ascii_value)
    ascii_value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", ascii_value)
    token = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value)
    return re.sub(r"_+", "_", token).strip("_").lower()


def normalize_namespace(compose_path: Path) -> str:
    """使用 Compose 文件名生成 snake_case 命名空间，并去掉末尾 Layout。"""
    stem = re.sub(r"(?i)layout$", "", compose_path.stem)
    token = _snake_token(stem)
    if not token:
        token = "screen_" + hashlib.sha256(compose_path.stem.encode()).hexdigest()[:6]
    if token[0].isdigit():
        token = "screen_" + token
    return token


def normalize_asset_stem(original_stem: str) -> str:
    """将图片原名转换为小写 snake_case；中文名使用稳定 Hash 兜底。"""
    # 蓝湖常见的重复下载后缀不参与基础名，真正冲突由资源身份 Hash 解决。
    without_copy_suffix = re.sub(r"(?:\(\d+\)|[_-]\d+)$", "", original_stem)
    token = _snake_token(without_copy_suffix)
    if not token:
        token = "image_" + hashlib.sha256(original_stem.encode()).hexdigest()[:6]
    if token[0].isdigit():
        token = "image_" + token
    return token


def find_project_root(compose_path: Path) -> Path:
    resolved = compose_path.resolve()
    for parent in (resolved.parent, *resolved.parents):
        if (parent / ".git").exists() or (parent / "settings.gradle.kts").exists():
            return parent
        if parent.name == "app":
            return parent.parent
    return resolved.parent


def resolve_mipmap_path(project_root: Path, value: str | None) -> Path:
    """解析 res/mipmap、res.mipmap 以及项目内 app/src/main/res/... 写法。"""
    raw = (value or "res/mipmap").strip()
    normalized = raw.replace(".", "/") if "/" not in raw else raw
    path = Path(normalized)
    candidates = [
        path if path.is_absolute() else project_root / path,
        project_root / "app/src/main" / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def resolve_mipmap_dirs(mipmap_path: Path) -> list[Path]:
    """把 mipmap 基础目录扩展为基础目录及其密度目录。"""
    path = mipmap_path.resolve()
    if path.name.startswith(MIPMAP_PREFIX):
        return [path] if path.is_dir() else []

    directories = []
    if path.is_dir():
        directories.append(path)
    siblings = sorted(path.parent.glob(path.name + "-*"))
    directories.extend(directory for directory in siblings if directory.is_dir())
    return list(dict.fromkeys(directories))


def iter_image_files(directories: Iterable[Path]) -> list[Path]:
    files = []
    for directory in directories:
        files.extend(
            path
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
    return files


def family_root(path: Path) -> Path:
    return path.parent.parent if path.parent.name.startswith(MIPMAP_PREFIX) else path.parent


def relative_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "resources": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"无法读取资源缓存 {path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("resources", []), list):
        raise ValueError(f"资源缓存格式错误：{path}")
    return data


def _find_cached_record(
    records: list[dict],
    current_path: str,
    current_hash: str,
    resource_family: str,
) -> dict | None:
    for record in records:
        if record.get("currentPath") == current_path or record.get("outputPath") == current_path:
            return record
    for record in records:
        if (
            record.get("hash") == current_hash
            and record.get("resourceFamily") == resource_family
        ):
            return record
    return None


def _occupied_stems(directories: Iterable[Path], input_files: set[Path]) -> set[str]:
    occupied = set()
    for directory in directories:
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if path.resolve() in input_files:
                continue
            occupied.add(path.stem.lower())
    return occupied


def discover_project_mipmap_dirs(project_root: Path) -> list[Path]:
    """扫描项目资源目录，避免自定义 res 路径之间出现全局资源名冲突。"""
    roots = [project_root / "app/src/main/res", project_root / "app/src/main"]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_dir() and (path.name == "mipmap" or path.name.startswith(MIPMAP_PREFIX)):
                found.append(path.resolve())
    return list(dict.fromkeys(found))


def _short_hash(identity: str, length: int = 6) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:length]


def build_plan(
    compose_path: Path,
    mipmap_path: Path,
    manifest_path: Path | None = None,
) -> list[RenamePlan]:
    """只生成计划，不修改文件；默认覆盖同一 mipmap 族的全部密度目录。"""
    compose_path = Path(compose_path).resolve()
    project_root = find_project_root(compose_path)
    directories = resolve_mipmap_dirs(Path(mipmap_path))
    source_files = iter_image_files(directories)
    if not source_files:
        raise ValueError(f"mipmap 路径中没有可处理的图片：{mipmap_path}")

    manifest = load_manifest(manifest_path) if manifest_path else {"resources": []}
    namespace = normalize_namespace(compose_path)
    input_set = {path.resolve() for path in source_files}
    all_resource_dirs = list(
        dict.fromkeys(discover_project_mipmap_dirs(project_root) + directories)
    )
    occupied = _occupied_stems(all_resource_dirs, input_set)

    records = []
    for source in source_files:
        source_hash = sha256_file(source)
        family = relative_path(family_root(source), project_root)
        current_path = relative_path(source, project_root)
        cached = _find_cached_record(
            manifest.get("resources", []), current_path, source_hash, family
        )
        if cached:
            previous_original = cached.get("originalName")
            is_previous_output = source.name == cached.get("outputName")
            original_name = previous_original if is_previous_output else source.name
            identity = cached.get("identity") or f"{family}:{original_name}"
            previous_output = cached.get("outputName")
            previous_original_name = None if is_previous_output else previous_original
        else:
            original_name = source.name
            identity = f"{family}:{original_name}"
            previous_output = None
            previous_original_name = None

        stem = "icon_" + namespace + "_" + normalize_asset_stem(Path(original_name).stem)
        records.append(
            {
                "source": source,
                "family": family,
                "family_absolute": str(family_root(source).resolve()),
                "identity": identity,
                "original_name": original_name,
                "stem": stem,
                "extension": source.suffix.lower(),
                "file_hash": source_hash,
                "previous_output": previous_output,
                "previous_original": previous_original_name,
            }
        )

    grouped: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        grouped.setdefault((record["family_absolute"], record["stem"]), []).append(record)

    used: set[str] = set(occupied)
    output_by_identity: dict[tuple[str, str], str] = {}
    plans = []
    for (family_absolute, stem), group in sorted(grouped.items()):
        identities = sorted({record["identity"] for record in group})
        family = group[0]["family"]
        needs_suffix = len(identities) > 1 or stem in occupied
        for identity in identities:
            record = next(item for item in group if item["identity"] == identity)
            extension = record["extension"]
            if not needs_suffix:
                output_name = stem + extension
                if stem in used:
                    needs_suffix = True
                else:
                    used.add(stem)
            if needs_suffix:
                length = 6
                while True:
                    suffix = _short_hash(identity, length)
                    output_name = stem + suffix + extension
                    key = Path(output_name).stem
                    previous_same = output_by_identity.get((family_absolute, identity))
                    if (key not in used or previous_same == output_name) and output_name not in {
                        item.output_name for item in plans
                    }:
                        used.add(key)
                        break
                    length += 2
                    if length > 32:
                        raise ValueError(f"无法为资源生成唯一名称：{record['source']}")
            output_by_identity[(family_absolute, identity)] = output_name
            for item in group:
                if item["identity"] != identity:
                    continue
                plans.append(
                    RenamePlan(
                        source=item["source"],
                        target=item["source"].with_name(output_name),
                        original_name=item["original_name"],
                        output_name=output_name,
                        identity=identity,
                        resource_family=family,
                        compose_file=relative_path(compose_path, project_root),
                        file_hash=item["file_hash"],
                        previous_output_name=item["previous_output"],
                        previous_original_name=item["previous_original"],
                    )
                )
    return sorted(plans, key=lambda item: str(item.source))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_plan(
    plans: list[RenamePlan],
    manifest_path: Path,
    mapping_path: Path,
    project_root: Path,
) -> None:
    """执行无覆盖重命名，并更新两个本地缓存文件。"""
    sources = {plan.source.resolve() for plan in plans}
    original_name_counts = {}
    for plan in plans:
        original_name_counts[plan.original_name] = original_name_counts.get(plan.original_name, 0) + 1

    for plan in plans:
        if plan.source.resolve() == plan.target.resolve():
            continue
        if plan.target.exists() and plan.target.resolve() not in sources:
            raise FileExistsError(f"目标文件已存在，拒绝覆盖：{plan.target}")

    temporary_paths = []
    for index, plan in enumerate(plans):
        if plan.source.resolve() == plan.target.resolve():
            continue
        temporary = plan.source.with_name(
            f".code-image-temp-{index}-{_short_hash(plan.identity, 10)}{plan.source.suffix.lower()}"
        )
        if temporary.exists():
            raise FileExistsError(f"临时文件已存在，请清理后重试：{temporary}")
        os.replace(plan.source, temporary)
        temporary_paths.append((temporary, plan.target))
    for temporary, target in temporary_paths:
        os.replace(temporary, target)

    manifest = load_manifest(manifest_path)
    old_records = {record.get("identity"): record for record in manifest.get("resources", [])}
    mapping = {}
    if mapping_path.exists():
        existing = json.loads(mapping_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            mapping.update(existing)

    for plan in plans:
        old_record = old_records.get(plan.identity, {})
        if plan.previous_original_name and mapping.get(plan.previous_original_name) == plan.previous_output_name:
            mapping.pop(plan.previous_original_name, None)
        if plan.previous_output_name:
            for key, value in list(mapping.items()):
                if value == plan.previous_output_name and key != plan.original_name:
                    mapping.pop(key, None)
        mapping_key = plan.original_name
        if original_name_counts[plan.original_name] > 1:
            mapping_key = f"{plan.resource_family}/{plan.original_name}"
        mapping[mapping_key] = plan.output_name
        mapping[relative_path(plan.source, project_root)] = plan.output_name
        old_records[plan.identity] = {
            "identity": plan.identity,
            "originalName": plan.original_name,
            "outputName": plan.output_name,
            "currentPath": relative_path(plan.target, project_root),
            "outputPath": relative_path(plan.target, project_root),
            "resourceFamily": plan.resource_family,
            "composeFile": plan.compose_file,
            "hash": plan.file_hash,
            "previousOutputName": plan.previous_output_name,
            "previousOriginalName": old_record.get("originalName")
            if old_record.get("originalName") != plan.original_name
            else None,
        }

    manifest["version"] = 1
    manifest["resources"] = sorted(old_records.values(), key=lambda record: record.get("identity", ""))
    _write_json(manifest_path, manifest)
    _write_json(mapping_path, mapping)


def update_compose_references(compose_path: Path, plans: list[RenamePlan]) -> None:
    """只更新用户指定 Compose 文件中已经存在的 R.mipmap 引用。"""
    path = Path(compose_path)
    content = path.read_text(encoding="utf-8")
    for plan in plans:
        old_names = set()
        if plan.previous_output_name:
            old_names.add(Path(plan.previous_output_name).stem)
        old_names.add(_ascii_token(Path(plan.original_name).stem))
        new_name = Path(plan.output_name).stem
        for old_name in sorted(name for name in old_names if name and name != new_name):
            content = re.sub(
                rf"(R\.mipmap\.){re.escape(old_name)}\b",
                rf"\g<1>{new_name}",
                content,
            )
    path.write_text(content, encoding="utf-8")


def _print_plan(plans: list[RenamePlan]) -> None:
    for plan in plans:
        marker = "保持" if plan.source == plan.target else "重命名"
        print(f"{marker}: {plan.source.name} -> {plan.output_name}")
        print(f"  Compose: {plan.compose_file} | Hash: {plan.file_hash[:12]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="规范蓝湖图片资源名并维护 code-compose 映射")
    parser.add_argument("--compose", required=True, help="当前资源对应的 Compose 文件路径")
    parser.add_argument(
        "--mipmap-path",
        default="res/mipmap",
        help="mipmap 路径；支持 res/mipmap 或 res.mipmap，默认 res/mipmap",
    )
    parser.add_argument("--project-root", help="项目根目录，默认从 Compose 文件推断")
    parser.add_argument("--manifest", help="Hash 与历史关系清单路径")
    parser.add_argument("--mapping", help="code-compose 映射路径")
    parser.add_argument("--apply", action="store_true", help="实际重命名；默认只输出预览")
    parser.add_argument(
        "--update-compose",
        action="store_true",
        help="Apply 时同步更新指定 Compose 文件中的 R.mipmap 引用",
    )
    args = parser.parse_args()

    compose = Path(args.compose).resolve()
    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root(compose)
    mipmap_path = resolve_mipmap_path(project_root, args.mipmap_path)
    manifest_path = Path(args.manifest) if args.manifest else project_root / ".codex/code-image-manifest.json"
    mapping_path = Path(args.mapping) if args.mapping else project_root / ".codex/lanhu-resources.json"
    if not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path
    if not mapping_path.is_absolute():
        mapping_path = project_root / mapping_path
    plans = build_plan(compose, mipmap_path, manifest_path)
    _print_plan(plans)
    if args.apply:
        apply_plan(plans, manifest_path, mapping_path, project_root)
        if args.update_compose:
            update_compose_references(compose, plans)
            print(f"已更新 Compose 引用：{compose}")
        print(f"已更新缓存：{manifest_path}")
        print(f"已更新映射：{mapping_path}")
    else:
        print("当前为 Dry Run，确认名称后追加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
