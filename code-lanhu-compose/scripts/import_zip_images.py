#!/usr/bin/env python3
"""安全解压蓝湖 ZIP，并逐张调用 code-image 导入图片。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
CODE_IMAGE_SCRIPT = Path(__file__).resolve().parents[2] / "code-image/scripts/normalize_images.py"
LAYOUT_UTILITY_CLASSES = frozenset({"flex-row", "flex-col"})
SELECTOR_TOKEN_PATTERN = re.compile(r"([.#])([A-Za-z][A-Za-z0-9_-]*)")
EXTRACTION_MARKER_NAME = ".code-lanhu-compose-extraction.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
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


def safe_entries(archive: ZipFile):
    entries = []
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        mode = (entry.external_attr >> 16) & 0o170000
        if path.is_absolute() or ".." in path.parts or mode == 0o120000:
            raise ValueError(f"ZIP 包含不安全路径或符号链接：{entry.filename}")
        entries.append(entry)
    return entries


def extraction_cache_is_complete(destination: Path, entries, source_hash: str) -> bool:
    marker = destination / EXTRACTION_MARKER_NAME
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if cached.get("sourceSha256") != source_hash:
        return False
    root = destination.resolve()
    for entry in entries:
        if entry.is_dir():
            continue
        candidate = root / PurePosixPath(entry.filename)
        target = candidate.resolve()
        if root not in target.parents or candidate.is_symlink() or not target.is_file():
            return False
        if target.stat().st_size != entry.file_size:
            return False
    return True


def extract_zip(zip_path: Path, source_hash: str) -> tuple[Path, list[tuple[PurePosixPath, Path]]]:
    destination = Path.home() / "Downloads" / f"{safe_file_token(zip_path.stem)}-{source_hash[:6]}"
    with ZipFile(zip_path) as archive:
        entries = safe_entries(archive)
        image_entries = [
            entry for entry in entries if not entry.is_dir() and PurePosixPath(entry.filename).suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not image_entries:
            raise ValueError("ZIP 中没有图片，无法逐图导入")
        if not extraction_cache_is_complete(destination, entries, source_hash):
            for entry in entries:
                if entry.is_dir():
                    continue
                target = destination / PurePosixPath(entry.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
            write_json(
                destination / EXTRACTION_MARKER_NAME,
                {"version": 1, "sourceSha256": source_hash},
            )
    return destination, [(PurePosixPath(entry.filename), destination / PurePosixPath(entry.filename)) for entry in image_entries]


def verify_manifest_identity(path: Path, source_hash: str) -> None:
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"已有图片清单不是有效 JSON，无法安全覆盖：{path}") from error
    if existing.get("sourceSha256") != source_hash:
        raise ValueError(f"图片清单已属于另一个 ZIP，拒绝覆盖：{path}")


def load_code_image_record(resources_path: Path, source_path: Path, file_hash: str, project_root: Path) -> dict:
    try:
        data = json.loads(resources_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 code-image 资源记录：{resources_path}") from error
    source_values = {
        str(source_path.resolve()),
        project_relative(source_path, project_root),
    }
    for record in data.get("resources", []):
        if record.get("originalPath") in source_values and record.get("originalHash") == file_hash:
            return record
    for record in data.get("resources", []):
        if record.get("originalHash") == file_hash:
            return record
    raise ValueError(f"code-image 未记录刚导入的图片：{source_path}")


def load_code_image_records_by_hash(resources_path: Path) -> dict[str, dict]:
    if not resources_path.is_file():
        return {}
    try:
        data = json.loads(resources_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 code-image 资源记录：{resources_path}") from error
    return {
        record["originalHash"]: record
        for record in data.get("resources", [])
        if isinstance(record.get("originalHash"), str)
    }


def resource_manifest_path(
    project_root: Path,
    zip_path: Path,
    source_hash: str,
) -> Path:
    return (
        project_root
        / ".code-image"
        / f"{safe_file_token(zip_path.stem)}-{source_hash[:6]}.resources.json"
    )


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


def run_code_image(
    image_path: Path,
    compose_path: Path,
    project_root: Path,
    resources_path: Path,
    apply: bool,
    asset_name: str | None,
) -> None:
    command = [
        "python3",
        str(CODE_IMAGE_SCRIPT),
        "--image",
        str(image_path),
        "--compose",
        str(compose_path),
        "--project-root",
        str(project_root),
        "--resources-file",
        str(resources_path),
    ]
    if asset_name:
        command.extend(["--asset-name", asset_name])
    if apply:
        command.append("--apply")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError(f"code-image 处理失败：{image_path}\n{result.stderr or result.stdout}")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def import_zip_images(zip_path: Path, compose_path: Path, project_root: Path, apply: bool) -> dict:
    zip_path = zip_path.resolve()
    compose_path = compose_path.resolve()
    project_root = project_root.resolve()
    source_hash = sha256_file(zip_path)
    manifest_path = manifest_path_for(zip_path, source_hash, project_root)
    verify_manifest_identity(manifest_path, source_hash)
    extraction_root, images = extract_zip(zip_path, source_hash)
    asset_names = lanhu_asset_names(extraction_root, images)
    resources_path = resource_manifest_path(project_root, zip_path, source_hash)
    records_by_hash = load_code_image_records_by_hash(resources_path) if apply else {}
    records = []
    for zip_entry, image_path in images:
        content_hash = sha256_file(image_path)
        asset_name = asset_names.get(zip_entry)
        record = records_by_hash.get(content_hash)
        if record is None:
            run_code_image(
                image_path,
                compose_path,
                project_root,
                resources_path,
                apply,
                asset_name,
            )
            record = load_code_image_record(resources_path, image_path, content_hash, project_root) if apply else None
            if record is not None:
                records_by_hash[content_hash] = record
        records.append(
            {
                "sourcePath": zip_entry.as_posix(),
                "extractedPath": str(image_path.resolve()),
                "originalName": image_path.name,
                "assetName": asset_name,
                "sha256": content_hash,
                "outputPath": record.get("outputPath") if record else None,
                "outputName": record.get("outputName") if record else None,
                "resourceManifest": project_relative(resources_path, project_root),
            }
        )

    data = {
        "version": 2,
        "sourceName": zip_path.name,
        "sourcePath": str(zip_path),
        "sourceSha256": source_hash,
        "extractionPath": str(extraction_root),
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
    parser.add_argument("--apply", action="store_true", help="实际复制、改名并写入图片清单")
    args = parser.parse_args()

    compose = Path(args.compose).resolve()
    if not compose.is_file():
        raise ValueError(f"Compose 文件不存在：{compose}")
    data = import_zip_images(Path(args.zip), compose, Path(args.project_root), args.apply)
    print(f"已处理 {len(data['images'])} 张图片：{data['extractionPath']}")
    if not args.apply:
        print("当前为 Dry Run，确认后追加 --apply 写入资源与清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
