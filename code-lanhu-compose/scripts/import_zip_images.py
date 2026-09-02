#!/usr/bin/env python3
"""安全解压蓝湖 ZIP，并逐张调用 code-image 导入图片。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from types import ModuleType
from zipfile import ZipFile


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
CODE_IMAGE_SCRIPT = Path(__file__).resolve().parents[2] / "code-image/scripts/normalize_images.py"
_CODE_IMAGE_MODULE: ModuleType | None = None
LAYOUT_UTILITY_CLASSES = frozenset({"flex-row", "flex-col"})
SELECTOR_TOKEN_PATTERN = re.compile(r"([.#])([A-Za-z][A-Za-z0-9_-]*)")
EXTRACTION_MARKER_NAME = ".code-lanhu-compose-extraction.json"
MAX_ARCHIVE_ENTRIES = 5000
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return token or "design"


def artifact_directory(zip_path: Path, source_hash: str, project_root: Path) -> Path:
    return project_root / ".code-lanhu-compose" / f"{safe_file_token(zip_path.stem)}-{source_hash[:6]}"


def manifest_path_for(zip_path: Path, source_hash: str, project_root: Path) -> Path:
    return artifact_directory(zip_path, source_hash, project_root) / "images.json"


def project_relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def target_resource_root(compose_path: Path, project_root: Path) -> Path:
    """从目标 Compose 的真实路径确定所属模块 src/main/res，避免跨模块复用资源。"""
    root = project_root.resolve()
    compose = compose_path.resolve()
    try:
        relative = compose.relative_to(root)
        source_index = relative.parts.index("src")
    except (ValueError, IndexError) as error:
        raise ValueError(f"无法从 Compose 路径确定目标模块资源目录：{compose}") from error
    return root.joinpath(*relative.parts[:source_index], "src", "main", "res").resolve()


def record_targets_resource_root(record: dict, project_root: Path, resource_root: Path) -> bool:
    output_path = record.get("outputPath")
    if not isinstance(output_path, str):
        return False
    candidate = Path(output_path)
    candidate = candidate if candidate.is_absolute() else project_root.resolve() / candidate
    resolved = candidate.resolve()
    return (
        resource_root in resolved.parents
        and not candidate.is_symlink()
        and resolved.is_file()
    )


def normalized_zip_path(name: str) -> PurePosixPath:
    """按实际解压语义规范 ZIP 路径，避免别名覆盖同一文件。"""
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    path = PurePosixPath(normalized)
    if not path.parts or path == PurePosixPath("."):
        raise ValueError(f"ZIP 包含空路径：{name}")
    return path


def safe_entries(archive: ZipFile):
    entries = []
    seen: set[str] = set()
    total_size = 0
    for entry in archive.infolist():
        raw_path = PurePosixPath(unicodedata.normalize("NFC", entry.filename.replace("\\", "/")))
        if entry.is_dir() and raw_path == PurePosixPath("."):
            # ZIP 导出工具常会显式写入根目录条目（例如 `./`），它不代表可解压文件。
            continue
        path = normalized_zip_path(entry.filename)
        mode = (entry.external_attr >> 16) & 0o170000
        if path.is_absolute() or ".." in path.parts or mode == 0o120000:
            raise ValueError(f"ZIP 包含不安全路径或符号链接：{entry.filename}")
        collision_key = path.as_posix().casefold()
        if collision_key in seen:
            raise ValueError(f"ZIP 包含重复路径：{entry.filename}")
        seen.add(collision_key)
        total_size += entry.file_size
        if len(seen) > MAX_ARCHIVE_ENTRIES or total_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("ZIP 条目数或解压总大小超过安全上限")
        if entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
            raise ValueError(f"ZIP 条目压缩比超过安全上限：{entry.filename}")
        entries.append(entry)
    return entries


def safe_extraction_target(destination: Path, relative: PurePosixPath) -> Path:
    """拒绝缓存目录中的预存符号链接，确保写入仍位于目标根目录。"""
    if destination.is_symlink():
        raise ValueError(f"解压缓存目录不能是符号链接：{destination}")
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    current = destination
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"解压目标父目录不能是符号链接：{current}")
        current.mkdir(exist_ok=True)
    target = destination.joinpath(*relative.parts)
    if target.is_symlink():
        raise ValueError(f"解压目标不能是符号链接：{target}")
    resolved = target.resolve()
    if root not in resolved.parents:
        raise ValueError(f"ZIP 解压路径越界：{relative.as_posix()}")
    return target


def extraction_cache_is_complete(destination: Path, entries, source_hash: str) -> bool:
    marker = destination / EXTRACTION_MARKER_NAME
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if cached.get("sourceMd5") != source_hash:
        return False
    root = destination.resolve()
    for entry in entries:
        if entry.is_dir():
            continue
        candidate = root / normalized_zip_path(entry.filename)
        target = candidate.resolve()
        if root not in target.parents or candidate.is_symlink() or not target.is_file():
            return False
        if target.stat().st_size != entry.file_size:
            return False
    return True


def reject_extraction_identity_collision(destination: Path, source_hash: str) -> None:
    marker = destination / EXTRACTION_MARKER_NAME
    if not marker.is_file():
        return
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"解压缓存身份文件损坏，拒绝覆盖：{marker}") from error
    existing = cached.get("sourceMd5") if isinstance(cached, dict) else None
    if isinstance(existing, str) and existing != source_hash:
        raise ValueError(f"检测到 MD5 前缀碰撞，拒绝覆盖解压缓存：{existing} != {source_hash}")


def extract_zip(
    zip_path: Path,
    source_hash: str,
    project_root: Path,
    extraction_root: Path | None = None,
) -> tuple[Path, list[tuple[PurePosixPath, Path]]]:
    destination = (
        extraction_root.expanduser().resolve()
        if extraction_root is not None
        else artifact_directory(zip_path, source_hash, project_root.resolve()) / "source-cache"
    )
    with ZipFile(zip_path) as archive:
        entries = safe_entries(archive)
        reject_extraction_identity_collision(destination, source_hash)
        image_entries = [
            entry for entry in entries if not entry.is_dir() and normalized_zip_path(entry.filename).suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not extraction_cache_is_complete(destination, entries, source_hash):
            for entry in entries:
                if entry.is_dir():
                    continue
                target = safe_extraction_target(destination, normalized_zip_path(entry.filename))
                with archive.open(entry) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
            write_json(
                destination / EXTRACTION_MARKER_NAME,
                {"version": 1, "sourceMd5": source_hash},
            )
    return destination, [
        (normalized_zip_path(entry.filename), destination / normalized_zip_path(entry.filename))
        for entry in image_entries
    ]


def verify_manifest_identity(path: Path, source_hash: str) -> None:
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"已有图片清单不是有效 JSON，无法安全覆盖：{path}") from error
    if existing.get("sourceMd5") != source_hash:
        raise ValueError(f"图片清单已属于另一个 ZIP，拒绝覆盖：{path}")


def load_code_image_record(
    resources_path: Path,
    source_path: Path,
    file_hash: str,
    project_root: Path,
    compose_path: Path,
) -> dict:
    try:
        data = json.loads(resources_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 code-image 资源记录：{resources_path}") from error
    source_values = {
        str(source_path.resolve()),
        project_relative(source_path, project_root),
    }
    resource_root = target_resource_root(compose_path, project_root)
    for record in data.get("resources", []):
        if (
            record.get("originalPath") in source_values
            and record.get("originalHash") == file_hash
            and record_targets_resource_root(record, project_root, resource_root)
        ):
            return record
    for record in data.get("resources", []):
        if record.get("originalHash") == file_hash and record_targets_resource_root(record, project_root, resource_root):
            return record
    raise ValueError(f"code-image 未记录刚导入的图片：{source_path}")


def load_code_image_records_by_hash(resources_path: Path, project_root: Path, compose_path: Path) -> dict[str, dict]:
    if not resources_path.is_file():
        return {}
    try:
        data = json.loads(resources_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 code-image 资源记录：{resources_path}") from error
    root = project_root.resolve()
    resource_root = target_resource_root(compose_path, project_root)
    result: dict[str, dict] = {}
    for record in data.get("resources", []):
        original_hash = record.get("originalHash")
        output_path = record.get("outputPath")
        if not isinstance(original_hash, str) or not isinstance(output_path, str):
            continue
        if not record_targets_resource_root(record, root, resource_root):
            continue
        result[original_hash] = record
    return result


def resource_manifest_path(
    project_root: Path,
    _zip_path: Path,
    _source_hash: str,
) -> Path:
    """返回 code-image 的唯一项目级资源清单。"""
    return project_root / ".code-image" / "image.json"


def resolve_asset_reference(document_path: PurePosixPath, raw_reference: str) -> PurePosixPath | None:
    reference = raw_reference.strip().strip("'\"").split("?", 1)[0].split("#", 1)[0]
    if not reference or "://" in reference or reference.startswith("data:"):
        return None
    parts = []
    for part in (*document_path.parent.parts, *PurePosixPath(reference).parts):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts)


def attribute_value(attributes: str, name: str) -> str | None:
    match = re.search(rf"\b{name}\s*=\s*(['\"])(.*?)\1", attributes, flags=re.IGNORECASE | re.DOTALL)
    return match.group(2) if match else None


def class_tokens(value: str | None) -> list[str]:
    return value.split() if value else []


def semantic_class_name(value: str | None) -> str | None:
    """返回节点或资源的主类；蓝湖 flex 工具类不承担命名语义。"""
    return next((token for token in class_tokens(value) if token not in LAYOUT_UTILITY_CLASSES), None)


def selector_asset_name(selector: str) -> str | None:
    """从 CSS 目标选择器提取非布局工具的节点名或 ID。"""
    for marker, name in reversed(SELECTOR_TOKEN_PATTERN.findall(selector)):
        if marker == "." and name in LAYOUT_UTILITY_CLASSES:
            continue
        return name
    return None


def lanhu_asset_names(extraction_root: Path, image_entries: list[tuple[PurePosixPath, Path]]) -> dict[PurePosixPath, str]:
    names: dict[PurePosixPath, str] = {}
    image_paths = {entry for entry, _ in image_entries}
    documents = sorted(extraction_root.rglob("*.html"))
    for document in documents:
        relative_document = PurePosixPath(document.relative_to(extraction_root).as_posix())
        content = document.read_text(encoding="utf-8", errors="ignore")
        for attributes in re.findall(r"<img\b([^>]*)>", content, flags=re.IGNORECASE | re.DOTALL):
            source = attribute_value(attributes, "src")
            classes = attribute_value(attributes, "class")
            name = semantic_class_name(classes) or attribute_value(attributes, "id")
            resolved = resolve_asset_reference(relative_document, source) if source else None
            if resolved in image_paths and name and resolved not in names:
                names[resolved] = name
    for document in sorted(extraction_root.rglob("*.css")):
        relative_document = PurePosixPath(document.relative_to(extraction_root).as_posix())
        content = document.read_text(encoding="utf-8", errors="ignore")
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", content, flags=re.DOTALL):
            name = selector_asset_name(selector)
            if not name:
                continue
            for raw_reference in re.findall(r"url\(\s*([^)]*?)\s*\)", body, flags=re.IGNORECASE):
                resolved = resolve_asset_reference(relative_document, raw_reference)
                if resolved in image_paths and resolved not in names:
                    names[resolved] = name
    return names


def load_code_image_module() -> ModuleType:
    """进程内加载 code-image，避免每张图片重复启动解释器和解析清单。"""
    global _CODE_IMAGE_MODULE
    if _CODE_IMAGE_MODULE is not None:
        return _CODE_IMAGE_MODULE
    spec = importlib.util.spec_from_file_location("code_lanhu_compose_code_image", CODE_IMAGE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载 code-image：{CODE_IMAGE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    _CODE_IMAGE_MODULE = module
    return module


def run_code_image_batch(
    images: list[tuple[Path, str | None]],
    compose_path: Path,
    project_root: Path,
    resources_path: Path,
    apply: bool,
) -> None:
    if not images:
        return
    module = load_code_image_module()
    target_dir = target_resource_root(compose_path, project_root) / "mipmap-xxhdpi"
    reserved: set[Path] = set()
    plans = []
    try:
        for image_path, asset_name in images:
            plan = module.build_plan(
                image_path,
                target_dir,
                project_root,
                compose_path,
                resources_path,
                reserved,
                asset_name=asset_name,
            )
            plans.append(plan)
            reserved.add(plan.target.resolve())
        if apply:
            module.apply_plans(plans, resources_path, project_root)
    except (OSError, ValueError) as error:
        raise ValueError(f"code-image 批量处理失败：{error}") from error


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def import_zip_images(
    zip_path: Path,
    compose_path: Path,
    project_root: Path,
    apply: bool,
    extraction_root: Path | None = None,
) -> dict:
    zip_path = zip_path.resolve()
    compose_path = compose_path.resolve()
    project_root = project_root.resolve()
    source_hash = md5_file(zip_path)
    manifest_path = manifest_path_for(zip_path, source_hash, project_root)
    verify_manifest_identity(manifest_path, source_hash)
    extracted_root, images = extract_zip(zip_path, source_hash, project_root, extraction_root)
    asset_names = lanhu_asset_names(extracted_root, images)
    resources_path = resource_manifest_path(project_root, zip_path, source_hash)
    records_by_hash = load_code_image_records_by_hash(resources_path, project_root, compose_path) if apply else {}
    image_facts = []
    pending_by_hash: dict[str, tuple[Path, str | None]] = {}
    for zip_entry, image_path in images:
        content_hash = content_md5_file(image_path)
        asset_name = asset_names.get(zip_entry)
        image_facts.append((zip_entry, image_path, content_hash, asset_name))
        if content_hash not in records_by_hash and content_hash not in pending_by_hash:
            pending_by_hash[content_hash] = (image_path, asset_name)
    run_code_image_batch(
        list(pending_by_hash.values()),
        compose_path,
        project_root,
        resources_path,
        apply,
    )
    if apply and pending_by_hash:
        records_by_hash.update(load_code_image_records_by_hash(resources_path, project_root, compose_path))
    records = []
    for zip_entry, image_path, content_hash, asset_name in image_facts:
        record = records_by_hash.get(content_hash)
        if apply and record is None:
            raise ValueError(f"code-image 未记录批量导入的图片：{image_path}")
        records.append(
            {
                "sourcePath": zip_entry.as_posix(),
                "extractedPath": str(image_path.resolve()),
                "originalName": image_path.name,
                "assetName": asset_name,
                "md5": content_hash,
                "outputPath": record.get("outputPath") if record else None,
                "outputName": record.get("outputName") if record else None,
                "resourceManifest": project_relative(resources_path, project_root),
            }
        )

    data = {
        "version": 2,
        "sourceName": zip_path.name,
        "sourcePath": str(zip_path),
        "sourceMd5": source_hash,
        "extractionPath": str(extracted_root),
        "composeFile": project_relative(compose_path, project_root),
        "images": records,
    }
    if apply:
        write_json(manifest_path, data)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="逐张调用 code-image 导入蓝湖 ZIP 图片")
    parser.add_argument("--zip", required=True, help="蓝湖 ZIP 文件")
    parser.add_argument("--compose", required=True, help="目标 Compose 文件")
    parser.add_argument("--project-root", default=".", help="Android 项目根目录")
    parser.add_argument("--extraction-root", type=Path, help="复用 pipeline 已验证的私有解压缓存")
    parser.add_argument("--apply", action="store_true", help="实际复制、改名并写入图片清单")
    args = parser.parse_args()

    compose = Path(args.compose).resolve()
    if not compose.is_file():
        raise ValueError(f"Compose 文件不存在：{compose}")
    data = import_zip_images(Path(args.zip), compose, Path(args.project_root), args.apply, args.extraction_root)
    print(f"已处理 {len(data['images'])} 张图片：{data['extractionPath']}")
    if not args.apply:
        print("当前为 Dry Run，确认后追加 --apply 写入资源与清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
