#!/usr/bin/env python3
"""安全导入蓝湖 ZIP 图片，并为 code-image 生成精确处理清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_zip_entries(archive: ZipFile):
    entries = []
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        mode = (entry.external_attr >> 16) & 0o170000
        if path.is_absolute() or ".." in path.parts or mode == 0o120000:
            raise ValueError(f"ZIP 包含不安全路径或符号链接：{entry.filename}")
        if not entry.is_dir() and path.suffix.lower() in IMAGE_EXTENSIONS:
            entries.append(entry)
    return entries


def safe_file_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return token or "design"


def project_relative(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def default_manifest_path(zip_path: Path, source_hash: str, project_root: Path) -> Path:
    name = f"{safe_file_token(zip_path.stem)}-{source_hash[:8]}.json"
    return project_root / ".code-lanhu-compose/images" / name


def import_images(zip_path: Path, target_dir: Path, manifest_path: Path, project_root: Path) -> dict:
    zip_path = zip_path.resolve()
    target_dir = target_dir.resolve()
    project_root = project_root.resolve()
    if target_dir.name != "mipmap" and not target_dir.name.startswith("mipmap-"):
        raise ValueError(f"目标目录不是 mipmap 资源目录：{target_dir}")
    try:
        target_dir.relative_to(project_root)
    except ValueError as error:
        raise ValueError(f"目标 mipmap 位于项目外：{target_dir}") from error

    source_hash = sha256_file(zip_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    images = []
    with ZipFile(zip_path) as archive:
        for entry in safe_zip_entries(archive):
            payload = archive.read(entry)
            content_hash = sha256_bytes(payload)
            source_path = PurePosixPath(entry.filename).as_posix()
            original_name = PurePosixPath(entry.filename).name
            import_key = hashlib.sha256(f"{source_path}:{content_hash}".encode()).hexdigest()[:16]
            staged_name = f".lanhu-import-{import_key}-{original_name}"
            target = target_dir / staged_name
            if target.exists():
                if sha256_file(target) != content_hash:
                    raise ValueError(f"临时导入文件内容冲突：{target}")
            else:
                temporary = target.with_name(f".{target.name}.tmp")
                temporary.write_bytes(payload)
                os.replace(temporary, target)
            images.append(
                {
                    "sourcePath": source_path,
                    "originalName": original_name,
                    "sha256": content_hash,
                    "targetPath": project_relative(target, project_root),
                }
            )

    data = {
        "version": 1,
        "sourceName": zip_path.name,
        "sourcePath": str(zip_path),
        "sourceSha256": source_hash,
        "targetMipmapPath": project_relative(target_dir, project_root),
        "images": images,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="导入蓝湖 ZIP 图片并生成 code-image 清单")
    parser.add_argument("--zip", required=True, help="蓝湖 ZIP 文件")
    parser.add_argument("--mipmap-path", required=True, help="目标 mipmap 或 mipmap-<density> 目录")
    parser.add_argument("--project-root", default=".", help="Android 项目根目录")
    parser.add_argument("--manifest", help="导入清单路径，默认 .code-lanhu-compose/images/<zip>-<hash>.json")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    zip_path = Path(args.zip).resolve()
    target_dir = Path(args.mipmap_path)
    target_dir = target_dir if target_dir.is_absolute() else project_root / target_dir
    source_hash = sha256_file(zip_path)
    manifest_path = Path(args.manifest) if args.manifest else default_manifest_path(zip_path, source_hash, project_root)
    manifest_path = manifest_path if manifest_path.is_absolute() else project_root / manifest_path
    data = import_images(zip_path, target_dir, manifest_path, project_root)
    print(f"已导入 {len(data['images'])} 张图片：{manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
