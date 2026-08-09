#!/usr/bin/env python3
"""code-image 单图和 ZIP 导入行为测试。"""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("normalize_images.py")


class NormalizeImagesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.input_dir = self.project / "input"
        self.input_dir.mkdir()
        self.home = self.project / "home"
        self.home.mkdir()
        self.compose = self.project / "app/src/main/java/com/example/ReportHomePage.kt"
        self.compose.parent.mkdir(parents=True)
        self.compose.write_text("@Composable fun ReportHomePage() = Unit\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_skill(self, source_flag: str, source: Path, *extra: str):
        environment = dict(os.environ)
        environment["HOME"] = str(self.home)
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                source_flag,
                str(source),
                "--project-root",
                str(self.project),
                *extra,
                "--apply",
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

    def resources(self) -> list[dict]:
        manifests = sorted((self.project / ".code-image").glob("*.resources.json"))
        self.assertEqual(len(manifests), 1)
        path = manifests[0]
        return json.loads(path.read_text(encoding="utf-8"))["resources"]

    def test_single_image_copies_to_mipmap_xxhdpi_and_writes_minimal_record(self):
        image = self.input_dir / "Group 62.png"
        image.write_bytes(b"new")

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_group_62.png"
        self.assertTrue(output.is_file())
        self.assertTrue(image.is_file())
        record = self.resources()[0]
        self.assertEqual(record["originalPath"], "input/Group 62.png")
        self.assertEqual(record["outputPath"], "app/src/main/res/mipmap-xxhdpi/icon_group_62.png")
        self.assertNotIn("resourceFamily", record)
        self.assertNotIn("updatedAt", record)
        self.assertFalse((self.project / ".code-image/resources.json").exists())
        source_hash = hashlib.md5(image.read_bytes()).hexdigest()
        self.assertTrue(
            (self.project / ".code-image" / f"Group_62-{source_hash[:6]}.resources.json").is_file()
        )

    def test_optional_compose_adds_page_namespace_for_single_image(self):
        image = self.input_dir / "Group 62.png"
        image.write_bytes(b"new")

        result = self.run_skill("--image", image, "--compose", str(self.compose))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_report_home_group_62.png").is_file()
        )
        self.assertEqual(self.resources()[0]["composeFile"], "app/src/main/java/com/example/ReportHomePage.kt")

    def test_explicit_asset_name_replaces_hash_style_export_name(self):
        image = self.input_dir / "SketchPng0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        image.write_bytes(b"new")

        result = self.run_skill(
            "--image",
            image,
            "--compose",
            str(self.compose),
            "--asset-name",
            "back_button",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_report_home_back_button.png").is_file()
        )
        self.assertEqual(self.resources()[0]["outputName"], "icon_report_home_back_button.png")

    def test_reimport_reuses_existing_resource_mapping(self):
        image = self.input_dir / "SketchPng0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        image.write_bytes(b"new")

        first = self.run_skill("--image", image, "--compose", str(self.compose))
        migrated = self.run_skill(
            "--image",
            image,
            "--compose",
            str(self.compose),
            "--asset-name",
            "back_button",
        )

        old_output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_report_home_sketch_png0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        new_output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_report_home_back_button.png"
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        self.assertTrue(old_output.is_file())
        self.assertFalse(new_output.exists())
        manifests = sorted((self.project / ".code-image").glob("*.resources.json"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(json.loads(manifests[0].read_text(encoding="utf-8"))["resources"][0]["outputName"], old_output.name)

        repeated = self.run_skill(
            "--image",
            image,
            "--compose",
            str(self.compose),
            "--asset-name",
            "back_button",
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue(old_output.is_file())
        self.assertFalse(new_output.exists())

    def test_shared_source_manifest_reuses_same_content_from_another_zip_entry(self):
        first = self.input_dir / "first.png"
        second = self.input_dir / "second.png"
        first.write_bytes(b"same-content")
        second.write_bytes(b"same-content")
        resources_path = self.project / ".code-image/design-abcdef.resources.json"

        first_result = self.run_skill(
            "--image",
            first,
            "--compose",
            str(self.compose),
            "--resources-file",
            str(resources_path),
        )
        second_result = self.run_skill(
            "--image",
            second,
            "--compose",
            str(self.compose),
            "--resources-file",
            str(resources_path),
        )

        target_dir = self.project / "app/src/main/res/mipmap-xxhdpi"
        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        self.assertTrue((target_dir / "icon_report_home_first.png").is_file())
        self.assertFalse((target_dir / "icon_report_home_second.png").exists())
        resources = json.loads(resources_path.read_text(encoding="utf-8"))["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["outputName"], "icon_report_home_first.png")

    def test_explicit_asset_name_preserves_semantic_trailing_number(self):
        image = self.input_dir / "SketchPng0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        image.write_bytes(b"new")

        result = self.run_skill(
            "--image",
            image,
            "--compose",
            str(self.compose),
            "--asset-name",
            "group_4",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_report_home_group_4.png").is_file()
        )

    def test_name_conflict_uses_incrementing_number_without_overwriting(self):
        target_dir = self.project / "app/src/main/res/mipmap-xxhdpi"
        target_dir.mkdir(parents=True)
        existing = target_dir / "icon_group_62.png"
        existing.write_bytes(b"existing")
        image = self.input_dir / "Group 62.png"
        image.write_bytes(b"new")

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target_dir / "icon_group_62_1.png").is_file())
        self.assertEqual(existing.read_bytes(), b"existing")

    def test_zip_extracts_to_downloads_and_copies_each_mipmap_directory(self):
        archive = self.input_dir / "design.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("design/app/src/main/res/mipmap-xhdpi/Group 62.png", b"xhdpi")
            zip_file.writestr("design/app/src/main/res/mipmap-xxhdpi/Group 62.png", b"xxhdpi")
            zip_file.writestr("design/readme.txt", "ignored")

        result = self.run_skill("--zip", archive)

        self.assertEqual(result.returncode, 0, result.stderr)
        source_hash = hashlib.md5(archive.read_bytes()).hexdigest()
        extracted = self.home / "Downloads" / f"design-{source_hash[:6]}"
        self.assertTrue((extracted / "design/app/src/main/res/mipmap-xhdpi/Group 62.png").is_file())
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xhdpi/icon_group_62.png").is_file()
        )
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_group_62.png").is_file()
        )
        self.assertEqual(len(self.resources()), 2)
        self.assertTrue(
            (self.project / ".code-image" / f"design-{source_hash[:6]}.resources.json").is_file()
        )

        repeated = self.run_skill("--zip", archive)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.resources()), 2)
        self.assertFalse(
            (self.project / "app/src/main/res/mipmap-xhdpi/icon_group_62_1.png").exists()
        )

    def test_zip_without_mipmap_images_is_rejected_before_extraction(self):
        archive = self.input_dir / "not-mipmap.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("design/images/Group 62.png", b"image")

        result = self.run_skill("--zip", archive)

        source_hash = hashlib.md5(archive.read_bytes()).hexdigest()
        extracted = self.home / "Downloads" / f"not-mipmap-{source_hash[:6]}"
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--image", result.stderr)
        self.assertFalse(extracted.exists())

    def test_multiple_images_or_mixed_image_and_zip_are_rejected(self):
        first = self.input_dir / "first.png"
        second = self.input_dir / "second.png"
        archive = self.input_dir / "design.zip"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        with zipfile.ZipFile(archive, "w"):
            pass
        environment = dict(os.environ)
        environment["HOME"] = str(self.home)

        repeated = subprocess.run(
            [
                "python3", str(SCRIPT), "--image", str(first), "--image", str(second),
                "--project-root", str(self.project), "--apply",
            ],
            capture_output=True,
            text=True,
            env=environment,
        )
        mixed = subprocess.run(
            [
                "python3", str(SCRIPT), "--image", str(first), "--zip", str(archive),
                "--project-root", str(self.project), "--apply",
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("只允许一个", repeated.stderr)
        self.assertNotEqual(mixed.returncode, 0)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())


if __name__ == "__main__":
    unittest.main()
