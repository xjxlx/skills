#!/usr/bin/env python3
"""code-lanhu-compose 逐图调用 code-image 的集成测试。"""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("import_zip_images.py")


class ImportZipImagesTest(unittest.TestCase):
    def test_zip_images_are_extracted_then_imported_one_by_one_through_code_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "design.zip"
            compose = root / "app/src/main/java/com/example/report/TestPage.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("@Composable fun TestPage() = Unit\n", encoding="utf-8")
            target = root / "app/src/main/res/mipmap-xxhdpi"
            target.mkdir(parents=True)
            legacy = target / "legacy.png"
            legacy.write_bytes(b"legacy")
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("design/img/Group 62.png", b"image-data")
                zip_file.writestr("design/readme.txt", "not an image")

            environment = dict(os.environ)
            environment["HOME"] = str(root / "home")
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--zip",
                    str(archive),
                    "--compose",
                    str(compose),
                    "--project-root",
                    str(root),
                    "--apply",
                ],
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            source_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            extracted = root / "home/Downloads" / f"design-{source_hash[:6]}"
            self.assertTrue((extracted / "design/img/Group 62.png").is_file())
            output = target / "icon_test_group_62.png"
            self.assertTrue(output.is_file())
            self.assertEqual(output.read_bytes(), b"image-data")
            self.assertTrue(legacy.is_file())

            manifest = root / ".code-lanhu-compose" / f"design-{source_hash[:6]}" / "images.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["sourceSha256"], source_hash)
            self.assertEqual(data["images"][0]["outputPath"], str(output.relative_to(root)))
            resources = json.loads((root / ".code-image/resources.json").read_text(encoding="utf-8"))
            self.assertEqual(len(resources["resources"]), 1)
            self.assertEqual(resources["resources"][0]["outputName"], output.name)

    def test_zip_without_images_stops_without_writing_an_image_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "empty.zip"
            compose = root / "app/src/main/java/com/example/report/TestPage.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("@Composable fun TestPage() = Unit\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("design/readme.txt", "not an image")

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--zip",
                    str(archive),
                    "--compose",
                    str(compose),
                    "--project-root",
                    str(root),
                    "--apply",
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("没有图片", result.stderr)
            self.assertFalse((root / ".code-lanhu-compose").exists())

    def test_lanhu_node_names_replace_hash_style_export_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "design.zip"
            compose = root / "app/src/main/java/com/example/report/TestPage.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("@Composable fun TestPage() = Unit\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr(
                    "design/index.html",
                    '<img class="back_button" src="./img/SketchPng0c6fdffe.png" />',
                )
                zip_file.writestr(
                    "design/index.css",
                    ".summary_panel { background: url(./img/39dc4c3c_mergeImage.png); }",
                )
                zip_file.writestr("design/img/SketchPng0c6fdffe.png", b"back")
                zip_file.writestr("design/img/39dc4c3c_mergeImage.png", b"panel")

            environment = dict(os.environ)
            environment["HOME"] = str(root / "home")
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--zip",
                    str(archive),
                    "--compose",
                    str(compose),
                    "--project-root",
                    str(root),
                    "--apply",
                ],
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            target = root / "app/src/main/res/mipmap-xxhdpi"
            self.assertTrue((target / "icon_test_back_button.png").is_file())
            self.assertTrue((target / "icon_test_summary_panel.png").is_file())


if __name__ == "__main__":
    unittest.main()
