#!/usr/bin/env python3
"""导入单张图片或 ZIP mipmap 资源，并规范 Android 资源名。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError
try:
    from text_unidecode import unidecode
except ImportError:
    unidecode = None


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
EXTRACTION_MARKER = ".extraction.json"
MAX_ARCHIVE_ENTRIES = 5000
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
SEMANTIC_TRANSLATIONS = {
    "今日目标": "today_target",
    "形状结合": "shape_combination",
    "导学": "guide",
    "矩形": "rectangle",
    "编组": "group",
    "蒙版": "mask",
    "路径": "path",
    "锁": "lock",
}
HAN_CHARACTER_PATTERN = re.compile(r"[\u3400-\u9fff]")
COPY_MARKER_PATTERN = re.compile(r"(?i)(?:备份|副本|\bbackup\b|\bcopy\b)")
RESOURCE_MANIFEST_NAME = "image.json"
CATALOG_VERSION = 4
MD5_PATTERN = re.compile(r"[0-9a-fA-F]{32}")


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path
    original_path: str
    original_name: str
    output_name: str
    identity: str
    file_hash: str
    previous_target: Path | None
    reuse_existing: bool


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
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


def translate_to_english(value: str) -> str:
    translated = value
    for source, target in sorted(SEMANTIC_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(source, f" {target} ")
    if HAN_CHARACTER_PATTERN.search(translated):
        if unidecode is None:
            raise ValueError("无法将中文图片名转换为英文；请安装 text-unidecode")
        translated = unidecode(translated)
    return translated


def normalize_namespace(compose_path: Path) -> str:
    stem = re.sub(r"(?i)(?:layout|page)$", "", compose_path.stem)
    token = snake_token(stem)
    if not token:
        token = "screen_" + hashlib.md5(compose_path.stem.encode()).hexdigest()[:6]
    return "screen_" + token if token[0].isdigit() else token


def normalize_asset_stem(
    original_stem: str,
    remove_copy_suffix: bool = True,
    remove_numeric_tokens: bool = True,
) -> str:
    cleaned = COPY_MARKER_PATTERN.sub(" ", original_stem)
    if remove_copy_suffix:
        cleaned = re.sub(r"(?:\(\s*\d+\s*\)|[_-]\d+)$", "", cleaned)
    if remove_numeric_tokens:
        cleaned = re.sub(r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])", " ", cleaned)
    token = snake_token(translate_to_english(cleaned))
    return token or "asset"


def expected_output_name(
    original_name: str,
    extension: str,
    compose_path: Path | None,
    asset_name: str | None,
    archive_stem: str | None,
) -> str:
    name_source = asset_name if asset_name else Path(original_name).stem
    if archive_stem:
        prefix = f"icon_{normalize_asset_stem(archive_stem, remove_numeric_tokens=False)}_"
    else:
        namespace = normalize_namespace(compose_path) if compose_path else None
        prefix = f"icon_{namespace}_" if namespace else "icon_"
    asset_stem = normalize_asset_stem(
        name_source,
        remove_copy_suffix=asset_name is None,
        remove_numeric_tokens=asset_name is None,
    )
    return prefix + asset_stem + extension


def relative_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _record_path(record: dict) -> str | None:
    value = record.get("path") or record.get("outputPath")
    return value if isinstance(value, str) and value else None


def _record_name(record: dict, path: str | None = None) -> str | None:
    value = record.get("name") or record.get("outputName")
    if isinstance(value, str) and value:
        return value
    return Path(path).name if path else None


def resource_key(value: str) -> str:
    """返回包含模块、资源目录和文件名但不包含扩展名的稳定键。"""
    normalized = unicodedata.normalize("NFC", value.replace("\\", "/"))
    path = PurePosixPath(normalized)
    return path.with_suffix("").as_posix() if path.suffix else path.as_posix()


def _valid_md5(value: object) -> str | None:
    if not isinstance(value, str) or not MD5_PATTERN.fullmatch(value):
        return None
    return value.lower()


def _record_hashes(record: dict) -> list[str]:
    """兼容旧版单值 md5/originalHash 和新版 md5s 历史数组。"""
    hashes: list[str] = []
    for field in ("md5s", "md5", "currentMd5", "originalHash"):
        value = record.get(field)
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            normalized = _valid_md5(candidate)
            if normalized and normalized not in hashes:
                hashes.append(normalized)
    return hashes


def _record_current_hash(record: dict) -> str | None:
    current = _valid_md5(record.get("currentMd5"))
    if current:
        return current
    hashes = _record_hashes(record)
    return hashes[0] if hashes else None


def _record_hash(record: dict) -> str | None:
    """返回当前或首个历史 Hash，供旧调用方兼容使用。"""
    return _record_current_hash(record)


def _record_resource_key(record: dict, path: str | None = None) -> str | None:
    value = record.get("resourceKey")
    if isinstance(value, str) and value:
        return resource_key(value)
    path_value = path or _record_path(record)
    return resource_key(path_value) if path_value else None


def _merge_hashes(*values: object) -> list[str]:
    merged: list[str] = []
    for value in values:
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            normalized = _valid_md5(candidate)
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _record_source(record: dict) -> str | None:
    value = record.get("source") or record.get("originalPath")
    return value if isinstance(value, str) and "!/" in value else None


def _record_output_path(record: dict, project_root: Path) -> Path | None:
    output_path = _record_path(record)
    if output_path is None:
        return None
    path = Path(output_path)
    return path if path.is_absolute() else project_root / path


def _catalog_file_paths(project_root: Path) -> list[Path]:
    """只扫描 Android 模块的 src/main/res，避免把输入目录和构建产物记入目录。"""
    excluded = {".git", ".gradle", ".idea", "build", "node_modules", ".code-image"}
    roots = []
    for candidate in project_root.rglob("res"):
        if (
            candidate.is_dir()
            and candidate.parent.name == "main"
            and candidate.parent.parent.name == "src"
            and not any(part in excluded for part in candidate.relative_to(project_root).parts)
        ):
            roots.append(candidate)
    files = []
    for root in sorted(roots):
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                files.append(path)
    return files


def _normalize_previous_record(record: dict, project_root: Path) -> dict | None:
    """把旧版或新版记录规范化，并保留可用于历史匹配的 Hash。"""
    path_value = _record_path(record)
    if not path_value:
        return None
    output_path = _record_output_path(record, project_root)
    hashes = _record_hashes(record)
    exists = (
        output_path is not None
        and output_path.is_file()
        and output_path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if exists:
        path = relative_path(output_path, project_root)
        hashes = _merge_hashes(hashes, md5_file(output_path))
        name = output_path.name
    else:
        path = path_value
        name = _record_name(record, path) or Path(path).name
    if not hashes:
        return None

    result = {
        "resourceKey": _record_resource_key(record, path) or resource_key(path),
        "identifier": _record_resource_key(record, path) or resource_key(path),
        "path": path,
        "name": name,
        "md5s": hashes,
    }
    current_hash = _valid_md5(record.get("currentMd5"))
    if exists:
        result["currentMd5"] = hashes[-1]
    elif current_hash:
        result["currentMd5"] = current_hash
        result["status"] = "missing"
    else:
        result["status"] = "missing"
    source = _record_source(record)
    if source:
        result["source"] = source
    return result


def scan_project_catalog(project_root: Path, previous: dict | None = None, sources: dict[str, str] | None = None) -> dict:
    """扫描项目图片，并按不含扩展名的资源键累计历史 Hash。"""
    previous_by_key: dict[str, list[dict]] = {}
    for record in (previous or {}).get("resources", []):
        if not isinstance(record, dict):
            continue
        normalized = _normalize_previous_record(record, project_root)
        if normalized:
            previous_by_key.setdefault(normalized["resourceKey"], []).append(normalized)

    records: list[dict] = []
    seen_keys: set[str] = set()
    current_paths: set[str] = set()
    for path in _catalog_file_paths(project_root):
        relative = relative_path(path, project_root)
        current_paths.add(relative)
        file_hash = md5_file(path)
        key = resource_key(relative)
        previous_candidates = previous_by_key.get(key, [])
        previous_record = previous_candidates[0] if previous_candidates else None
        hashes = _merge_hashes(
            _record_hashes(previous_record) if previous_record else None,
            file_hash,
        )
        record = {
            "resourceKey": key,
            "identifier": key,
            "path": relative,
            "name": path.name,
            "md5s": hashes,
            "currentMd5": file_hash,
        }
        source = (sources or {}).get(relative) or (previous_record or {}).get("source")
        if source:
            record["source"] = source
        records.append(record)
        seen_keys.add(key)

    for key, previous_candidates in previous_by_key.items():
        if key in seen_keys:
            continue
        for previous_record in previous_candidates:
            if previous_record["path"] in current_paths:
                continue
            previous_record = dict(previous_record)
            previous_record["status"] = "missing"
            records.append(previous_record)

    records.sort(key=lambda record: record["identifier"])
    return {"version": CATALOG_VERSION, "resources": records}


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


def validate_image_file(path: Path) -> None:
    """拒绝只有图片扩展名、实际内容却不可解码的输入。"""
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(f"图片内容无效或无法解码：{path}") from error
    if width < 1 or height < 1:
        raise ValueError(f"图片尺寸无效：{path} ({width}x{height})")


def resources_path_for_project(project_root: Path) -> Path:
    """所有导入统一使用项目根目录下唯一的资源清单。"""
    return project_root / ".code-image" / RESOURCE_MANIFEST_NAME


def requested_resources_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser().resolve()
    expected = resources_path_for_project(project_root).resolve()
    if path != expected:
        raise ValueError(
            f"--resources-file 只能指向项目 .code-image/{RESOURCE_MANIFEST_NAME}；"
            "资源清单不再按来源拆分"
        )
    return expected


def _record_matches_target(record: dict, target_dir: Path, project_root: Path) -> bool:
    output_path = _record_output_path(record, project_root)
    return output_path is not None and output_path.parent.resolve() == target_dir.resolve()


def _find_record(
    records: list[dict],
    current_path: str,
    file_hash: str,
    target_dir: Path,
    project_root: Path,
) -> dict | None:
    for record in records:
        if not _record_matches_target(record, target_dir, project_root):
            continue
        if file_hash not in _record_hashes(record):
            continue
        record_path = _record_path(record)
        if current_path == record_path:
            return record
        if current_path == record.get("originalPath"):
            return record
        if current_path == _record_source(record):
            return record
    return None


def _plan_key(original_path: str, file_hash: str, target_dir: Path) -> str:
    """生成不写入清单的内部资源键。"""
    return f"{original_path}:{file_hash}:{target_dir.resolve()}"


def _find_record_by_hash(
    records: list[dict],
    file_hash: str,
    target_dir: Path,
    project_root: Path,
) -> dict | None:
    """当前 image.json 内的同密度重复切图复用首个已记录资源。"""
    for record in records:
        output_path = _record_output_path(record, project_root)
        if (
            file_hash in _record_hashes(record)
            and output_path is not None
            and output_path.parent.resolve() == target_dir.resolve()
        ):
            return record
    return None


def _is_normalized(name: str) -> bool:
    stem = Path(name).stem
    return stem.startswith("icon_") and re.fullmatch(r"[a-z][a-z0-9_]*", stem) is not None


def resource_root_for_compose(project_root: Path, compose_path: Path | None) -> Path:
    if compose_path is None:
        return (project_root / "app/src/main/res").resolve()
    root = project_root.resolve()
    compose = compose_path.resolve()
    try:
        relative = compose.relative_to(root)
        source_index = relative.parts.index("src")
    except (ValueError, IndexError) as error:
        raise ValueError(f"无法从 Compose 路径确定目标模块资源目录：{compose}") from error
    if source_index == 0:
        raise ValueError(f"Compose 文件必须位于项目模块的 src 目录中：{compose}")
    return root.joinpath(*relative.parts[:source_index], "src", "main", "res").resolve()


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
    archive_stem: str | None = None,
    original_path_override: str | None = None,
    resource_manifest: dict | None = None,
) -> RenamePlan:
    source = Path(source_path).resolve()
    if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"不是支持的图片文件：{source}")
    validate_image_file(source)
    target_dir = Path(target_dir).resolve()
    project_root = Path(project_root).resolve()
    resources_path = requested_resources_path(str(resources_path), project_root)
    current_path = original_path_override or relative_path(source, project_root)
    file_hash = md5_file(source)
    manifest = resource_manifest or load_resources(resources_path)
    record = _find_record(manifest["resources"], current_path, file_hash, target_dir, project_root)
    if record is None:
        record = _find_record_by_hash(manifest["resources"], file_hash, target_dir, project_root)
    original_path = original_path_override or (record.get("originalPath") if record else None) or current_path
    original_name = _record_name(record) if record else source.name
    previous_target = _record_output_path(record, project_root) if record else None
    reuse_existing = bool(
        record
        and previous_target
        and previous_target.is_file()
        and file_hash in _record_hashes(record)
    )
    record_name = _record_name(record) if record else None
    if record and record_name and Path(record_name).name == record_name:
        output_name = record_name
    elif not record and _is_normalized(source.name) and archive_stem is None:
        output_name = source.name
    else:
        output_name = expected_output_name(
            original_name=original_name,
            extension=source.suffix.lower(),
            compose_path=compose_path,
            asset_name=asset_name,
            archive_stem=archive_stem,
        )

    replaceable = {previous_target.resolve()} if previous_target else set()
    target = next_output_path(
        target_dir,
        output_name,
        source,
        set() if record else reserved or set(),
        replaceable,
    )
    identity = _plan_key(original_path, file_hash, target_dir)
    return RenamePlan(
        source=source,
        target=target,
        original_path=original_path,
        original_name=original_name,
        output_name=target.name,
        identity=identity,
        file_hash=file_hash,
        previous_target=previous_target,
        reuse_existing=reuse_existing,
    )


def write_resources(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        if path.read_text(encoding="utf-8") == content:
            return
    except OSError:
        pass
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_copy(source: Path, target: Path) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with source.open("rb") as input_stream:
                shutil.copyfileobj(input_stream, temporary)
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def remove_legacy_manifests(project_root: Path) -> None:
    """清理旧版按来源生成的清单，保留唯一的 image.json。"""
    directory = project_root / ".code-image"
    if not directory.is_dir():
        return
    for candidate in directory.iterdir():
        if (
            candidate.is_file()
            and candidate.name != RESOURCE_MANIFEST_NAME
            and (candidate.name == "resources.json" or candidate.name.endswith(".resources.json"))
        ):
            candidate.unlink()


def apply_plans(plans: list[RenamePlan], resources_path: Path, project_root: Path) -> None:
    resources_path = requested_resources_path(str(resources_path), project_root)
    previous = load_resources(resources_path)
    for plan in plans:
        plan.target.parent.mkdir(parents=True, exist_ok=True)
        if not plan.reuse_existing and plan.source.resolve() != plan.target.resolve():
            target_hash = md5_file(plan.target) if plan.target.is_file() else None
            if target_hash == plan.file_hash:
                pass
            elif plan.target.exists() and plan.previous_target != plan.target:
                raise FileExistsError(f"目标文件已存在，拒绝覆盖：{plan.target}")
            else:
                atomic_copy(plan.source, plan.target)
        if (
            not plan.reuse_existing
            and plan.previous_target
            and plan.previous_target.resolve() != plan.target.resolve()
        ):
            if plan.previous_target.is_file():
                plan.previous_target.unlink()
    sources = {
        relative_path(plan.target, project_root): plan.original_path
        for plan in plans
        if "!/" in plan.original_path
    }
    manifest = scan_project_catalog(project_root, previous, sources)
    write_resources(resources_path, manifest)
    remove_legacy_manifests(project_root)


def normalized_zip_path(value: str) -> PurePosixPath:
    normalized = unicodedata.normalize("NFC", value.replace("\\", "/"))
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError(f"ZIP 包含绝对路径：{value}")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(f"ZIP 包含越界路径：{value}")
        parts.append(part)
    if not parts:
        raise ValueError(f"ZIP 包含空路径：{value}")
    return PurePosixPath(*parts)


def _safe_zip_entries(archive: ZipFile) -> list[tuple[ZipInfo, PurePosixPath]]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValueError(f"ZIP 条目过多：{len(infos)} > {MAX_ARCHIVE_ENTRIES}")
    entries: list[tuple[ZipInfo, PurePosixPath]] = []
    seen: set[str] = set()
    total_size = 0
    for entry in infos:
        path = normalized_zip_path(entry.filename)
        mode = (entry.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"ZIP 包含不安全路径或符号链接：{entry.filename}")
        key = path.as_posix().casefold()
        if key in seen:
            raise ValueError(f"ZIP 包含重复规范化路径：{entry.filename}")
        seen.add(key)
        if not entry.is_dir():
            if entry.file_size > MAX_SINGLE_FILE_BYTES:
                raise ValueError(f"ZIP 单文件过大：{entry.filename}")
            total_size += entry.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError(f"ZIP 解压总大小过大：{total_size}")
            ratio = entry.file_size / max(entry.compress_size, 1)
            if entry.file_size >= 1024 * 1024 and ratio > MAX_COMPRESSION_RATIO:
                raise ValueError(f"ZIP 条目压缩比异常：{entry.filename} ({ratio:.1f})")
        entries.append((entry, path))
    return entries


def archive_mipmap_directory(entry_name: str) -> str | None:
    path = PurePosixPath(entry_name)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    for part in reversed(path.parts[:-1]):
        if part == "mipmap" or part.startswith("mipmap-"):
            return part
    return None


def extract_zip_to_temp(zip_path: Path) -> tuple[Path, tempfile.TemporaryDirectory]:
    """在系统临时目录解压 ZIP，避免把原始文件留在项目中。"""
    source_hash = md5_file(zip_path)
    with ZipFile(zip_path) as archive:
        entries = _safe_zip_entries(archive)
        if not any(
            not entry.is_dir() and archive_mipmap_directory(path.as_posix())
            for entry, path in entries
        ):
            raise ValueError("ZIP 不含 mipmap 图片，不能按 ZIP 处理；请传入单个图片使用 --image")
        workspace = tempfile.TemporaryDirectory(prefix=f"code-image-{safe_token(zip_path.stem)}-")
        destination = Path(workspace.name)
        try:
            files = []
            for entry, relative in entries:
                if entry.is_dir():
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as input_stream, target.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream)
                files.append({"path": relative.as_posix(), "size": entry.file_size, "md5": md5_file(target)})
            write_resources(
                destination / EXTRACTION_MARKER,
                {"version": 1, "sourceMd5": source_hash, "files": sorted(files, key=lambda item: item["path"])},
            )
        except Exception:
            workspace.cleanup()
            raise
    return destination, workspace


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
        print(f"  Hash: {plan.file_hash[:12]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="导入并规范 Android 图片资源名")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--image", action="append", help="单个图片文件路径；每次只能提供一次")
    source_group.add_argument("--zip", action="append", help="包含 mipmap 图片目录的 ZIP；每次只能提供一次")
    source_group.add_argument("--scan", action="store_true", help="扫描项目所有 Android 资源图片并更新 image.json")
    parser.add_argument("--compose", help="可选的 Compose 布局文件，用于生成页面命名空间")
    parser.add_argument("--asset-name", help="可选的语义资源名，仅支持单图导入")
    parser.add_argument("--project-root", default=".", help="Android 项目根目录，默认当前目录")
    parser.add_argument(
        "--resources-file",
        help="兼容参数；只能指向项目 .code-image/image.json",
    )
    parser.add_argument("--apply", action="store_true", help="实际复制/改名；默认只输出预览")
    args = parser.parse_args()
    if args.image and len(args.image) != 1:
        parser.error("每次只允许一个 --image")
    if args.zip and len(args.zip) != 1:
        parser.error("每次只允许一个 --zip")
    if args.asset_name and args.zip:
        parser.error("--asset-name 仅支持与 --image 一起使用")
    if args.asset_name and args.scan:
        parser.error("--asset-name 仅支持与 --image 一起使用")

    project_root = Path(args.project_root).resolve()
    compose = Path(args.compose).resolve() if args.compose else None
    if compose and not compose.is_file():
        raise ValueError(f"Compose 文件不存在：{compose}")
    source_path = Path(args.image[0] if args.image else args.zip[0]).resolve() if not args.scan else None
    resources_path = (
        requested_resources_path(args.resources_file, project_root)
        if args.resources_file
        else resources_path_for_project(project_root)
    )
    res_root = resource_root_for_compose(project_root, compose)
    resource_manifest = scan_project_catalog(project_root, load_resources(resources_path))
    zip_workspace = None

    try:
        if args.scan:
            print(f"扫描到 {len(resource_manifest['resources'])} 张项目资源图片")
            if args.apply:
                write_resources(resources_path, resource_manifest)
                remove_legacy_manifests(project_root)
                print(f"已更新资源记录：{resources_path}")
            else:
                print("当前为 Dry Run，确认后追加 --apply 执行。")
            return 0
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
                    resource_manifest=resource_manifest,
                )
            ]
        else:
            extraction_root, zip_workspace = extract_zip_to_temp(source_path)
            reserved: set[Path] = set()
            imported_hashes: set[tuple[Path, str]] = set()
            plans = []
            for source, directory_name in zip_image_sources(extraction_root):
                target_dir = (res_root / directory_name).resolve()
                source_hash = md5_file(source)
                if (target_dir, source_hash) in imported_hashes:
                    continue
                entry_path = source.relative_to(extraction_root).as_posix()
                plan = build_plan(
                    source,
                    res_root / directory_name,
                    project_root,
                    compose,
                    resources_path,
                    reserved,
                    archive_stem=source_path.stem,
                    original_path_override=f"{source_path.name}!/{entry_path}",
                    resource_manifest=resource_manifest,
                )
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
    finally:
        if zip_workspace is not None:
            zip_workspace.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
