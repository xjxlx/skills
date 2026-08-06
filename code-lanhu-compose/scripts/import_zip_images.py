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


def extract_zip(zip_path: Path, source_hash: str) -> tuple[Path, list[tuple[PurePosixPath, Path]]]:
    destination = Path.home() / "Downloads" / f"{safe_file_token(zip_path.stem)}-{source_hash[:6]}"
    with ZipFile(zip_path) as archive:
        entries = safe_entries(archive)
        image_entries = [
            entry for entry in entries if not entry.is_dir() and PurePosixPath(entry.filename).suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not image_entries:
            raise ValueError("ZIP 中没有图片，无法逐图导入")
        for entry in entries:
            if entry.is_dir():
                continue
            target = destination / PurePosixPath(entry.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
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
    raise ValueError(f"code-image 未记录刚导入的图片：{source_path}")


def run_code_image(image_path: Path, compose_path: Path, project_root: Path, apply: bool) -> None:
    command = [
        "python3",
        str(CODE_IMAGE_SCRIPT),
        "--image",
        str(image_path),
        "--compose",
        str(compose_path),
        "--project-root",
        str(project_root),
    ]
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
    resources_path = project_root / ".code-image/resources.json"
    records = []
    for zip_entry, image_path in images:
        content_hash = sha256_file(image_path)
        run_code_image(image_path, compose_path, project_root, apply)
        record = load_code_image_record(resources_path, image_path, content_hash, project_root) if apply else None
        records.append(
            {
                "sourcePath": zip_entry.as_posix(),
                "extractedPath": str(image_path.resolve()),
                "originalName": image_path.name,
                "sha256": content_hash,
                "outputPath": record.get("outputPath") if record else None,
                "outputName": record.get("outputName") if record else None,
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
