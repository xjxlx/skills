#!/usr/bin/env python3
"""import_zip_images.py 的本地缓存契约测试。"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


SCRIPT_PATH = Path(__file__).with_name("import_zip_images.py")
SPEC = importlib.util.spec_from_file_location("import_zip_images", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT_PATH}")
IMPORT_IMAGES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT_IMAGES)


class ImportZipImagesContractTest(unittest.TestCase):
    def test_code_image_batch_builds_all_plans_and_applies_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            compose = project / "app/src/main/java/Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n", encoding="utf-8")
            first = root / "first.png"
            second = root / "second.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            plans = iter([
                SimpleNamespace(target=project / "app/src/main/res/mipmap-xxhdpi/first.png"),
                SimpleNamespace(target=project / "app/src/main/res/mipmap-xxhdpi/second.png"),
            ])
            module = SimpleNamespace(
                build_plan=MagicMock(side_effect=lambda *args, **kwargs: next(plans)),
                apply_plans=MagicMock(),
            )

            with patch.object(IMPORT_IMAGES, "load_code_image_module", return_value=module):
                IMPORT_IMAGES.run_code_image_batch(
                    [(first, "hero"), (second, "logo")],
                    compose,
                    project,
                    project / ".code-image/resources.json",
                    apply=True,
                )

            self.assertEqual(module.build_plan.call_count, 2)
            module.apply_plans.assert_called_once()

    def test_extract_zip_reuses_complete_source_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("images/a.png", b"original-image")

            source_hash = IMPORT_IMAGES.md5_file(archive)
            project = Path(temp_dir) / "project"
            extraction_root, images = IMPORT_IMAGES.extract_zip(archive, source_hash, project)
            image_path = images[0][1]
            image_path.write_bytes(b"cached-content")

            with patch.object(IMPORT_IMAGES, "safe_extraction_target", side_effect=AssertionError("不应重复解压")):
                second_root, second_images = IMPORT_IMAGES.extract_zip(archive, source_hash, project)

            self.assertEqual(second_root, extraction_root)
            self.assertEqual(second_images[0][1].read_bytes(), b"cached-content")

    def test_extract_zip_rejects_preexisting_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("images/a.png", b"owned")
            source_hash = IMPORT_IMAGES.md5_file(archive)
            project = root / "project"
            destination = IMPORT_IMAGES.artifact_directory(archive, source_hash, project) / "source-cache"
            outside = root / "outside"
            outside.mkdir()
            destination.mkdir(parents=True)
            (destination / "images").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                IMPORT_IMAGES.extract_zip(archive, source_hash, project)

            self.assertFalse((outside / "a.png").exists())

    def test_extract_zip_rejects_normalized_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("images/a.png", b"first")
                zipped.writestr("images\\a.png", b"second")
            source_hash = IMPORT_IMAGES.md5_file(archive)

            with self.assertRaisesRegex(ValueError, "重复"):
                IMPORT_IMAGES.extract_zip(archive, source_hash, root / "project")

    def test_import_allows_design_without_bitmap_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project = root / "project"
            compose = project / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", "<main>纯文本</main>")

            with patch.object(IMPORT_IMAGES.Path, "home", return_value=root):
                result = IMPORT_IMAGES.import_zip_images(archive, compose, project, apply=True)

            self.assertEqual(result["images"], [])
            manifest = json.loads(IMPORT_IMAGES.manifest_path_for(
                archive,
                IMPORT_IMAGES.md5_file(archive),
                project,
            ).read_text(encoding="utf-8"))
            self.assertEqual(manifest["images"], [])

    def test_cached_code_image_record_requires_existing_project_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n", encoding="utf-8")
            manifest = root / "resources.json"
            manifest.write_text(json.dumps({"resources": [{
                "originalHash": "abc",
                "outputPath": "app/src/main/res/mipmap-xhdpi/missing.png",
                "outputName": "missing.png",
            }]}), encoding="utf-8")

            records = IMPORT_IMAGES.load_code_image_records_by_hash(manifest, root, compose)

            self.assertEqual(records, {})

    def test_cached_resource_from_another_module_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            feature_compose = root / "feature" / "src" / "main" / "java" / "Page.kt"
            feature_compose.parent.mkdir(parents=True)
            feature_compose.write_text("package com.example.feature\n", encoding="utf-8")
            app_resource = root / "app" / "src" / "main" / "res" / "mipmap-xxhdpi" / "icon.png"
            app_resource.parent.mkdir(parents=True)
            app_resource.write_bytes(b"image")
            manifest = root / "resources.json"
            manifest.write_text(json.dumps({"resources": [{
                "originalHash": "abc",
                "outputPath": app_resource.relative_to(root).as_posix(),
                "outputName": "icon.png",
            }]}), encoding="utf-8")

            records = IMPORT_IMAGES.load_code_image_records_by_hash(manifest, root, feature_compose)

            self.assertEqual(records, {})


if __name__ == "__main__":
    unittest.main()
