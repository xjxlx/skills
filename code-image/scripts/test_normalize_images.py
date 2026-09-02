#!/usr/bin/env python3
"""code-image 单图和 ZIP 导入行为测试。"""

import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image


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
        self.feature_compose = self.project / "feature/src/main/java/com/example/FeaturePage.kt"
        self.feature_compose.parent.mkdir(parents=True)
        self.feature_compose.write_text("@Composable fun FeaturePage() = Unit\n", encoding="utf-8")

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

    def run_scan(self, *extra: str):
        environment = dict(os.environ)
        environment["HOME"] = str(self.home)
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--scan",
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
        manifests = sorted((self.project / ".code-image").glob("*.json"))
        self.assertEqual([path.name for path in manifests], ["image.json"])
        path = self.project / ".code-image/image.json"
        return json.loads(path.read_text(encoding="utf-8"))["resources"]

    @staticmethod
    def image_bytes(color: tuple[int, int, int] = (12, 34, 56)) -> bytes:
        output = io.BytesIO()
        Image.new("RGB", (4, 4), color).save(output, format="PNG")
        return output.getvalue()

    def write_image(self, path: Path, color: tuple[int, int, int] = (12, 34, 56)) -> None:
        path.write_bytes(self.image_bytes(color))

    def test_single_image_copies_to_mipmap_xxhdpi_and_writes_minimal_record(self):
        image = self.input_dir / "Group 62.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_group.png"
        self.assertTrue(output.is_file())
        self.assertTrue(image.is_file())
        record = self.resources()[0]
        output_path = "app/src/main/res/mipmap-xxhdpi/icon_group.png"
        file_hash = hashlib.md5(output.read_bytes()).hexdigest()
        self.assertEqual(record["path"], output_path)
        self.assertEqual(record["name"], "icon_group.png")
        self.assertEqual(record["md5"], file_hash)
        self.assertEqual(record["identifier"], f"{output_path}-{file_hash}")
        self.assertEqual(
            set(record),
            {"md5", "identifier", "path", "name"},
        )

    def test_optional_compose_adds_page_namespace_and_writes_minimal_record(self):
        image = self.input_dir / "Group 62.png"
        self.write_image(image)

        result = self.run_skill("--image", image, "--compose", str(self.compose))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_report_home_group.png").is_file()
        )
        self.assertEqual(
            set(self.resources()[0]),
            {"md5", "identifier", "path", "name"},
        )

    def test_explicit_asset_name_replaces_hash_style_export_name(self):
        image = self.input_dir / "SketchPng0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        self.write_image(image)

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
        self.assertEqual(self.resources()[0]["name"], "icon_report_home_back_button.png")

    def test_reimport_reuses_existing_resource_mapping(self):
        image = self.input_dir / "SketchPng0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        self.write_image(image)

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
        manifest_path = self.project / ".code-image/image.json"
        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["resources"][0]["name"], old_output.name)

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

    def test_each_apply_appends_to_cumulative_catalog_and_keeps_only_image_json(self):
        first = self.input_dir / "first.png"
        second = self.input_dir / "second.png"
        self.write_image(first)
        self.write_image(second, (1, 2, 3))

        first_result = self.run_skill(
            "--image",
            first,
            "--compose",
            str(self.compose),
        )
        second_result = self.run_skill(
            "--image",
            second,
            "--compose",
            str(self.compose),
        )

        target_dir = self.project / "app/src/main/res/mipmap-xxhdpi"
        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        self.assertTrue((target_dir / "icon_report_home_first.png").is_file())
        self.assertTrue((target_dir / "icon_report_home_second.png").is_file())
        resources = self.resources()
        self.assertEqual(len(resources), 2)
        self.assertEqual(
            {record["name"] for record in resources},
            {"icon_report_home_first.png", "icon_report_home_second.png"},
        )
        self.assertTrue(all(set(record) == {"md5", "identifier", "path", "name"} for record in resources))

    def test_apply_scans_preexisting_project_images_into_global_catalog(self):
        existing = self.project / "feature/src/main/res/drawable/icon_existing.png"
        existing.parent.mkdir(parents=True)
        self.write_image(existing, (9, 8, 7))
        image = self.input_dir / "Latest.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        resources = self.resources()
        existing_hash = hashlib.md5(existing.read_bytes()).hexdigest()
        existing_record = next(
            record for record in resources if record["path"] == "feature/src/main/res/drawable/icon_existing.png"
        )
        self.assertEqual(existing_record["md5"], existing_hash)
        self.assertEqual(existing_record["name"], "icon_existing.png")
        self.assertEqual(existing_record["identifier"], f"{existing_record['path']}-{existing_hash}")
        self.assertEqual(len(resources), 2)

    def test_scan_mode_builds_catalog_without_importing_an_input_file(self):
        existing = self.project / "app/src/main/res/drawable/icon_existing.webp"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"existing-project-image")

        result = self.run_scan()

        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.resources()[0]
        self.assertEqual(record["path"], "app/src/main/res/drawable/icon_existing.webp")
        self.assertEqual(record["name"], existing.name)
        self.assertEqual(record["md5"], hashlib.md5(existing.read_bytes()).hexdigest())

    def test_scan_keeps_multiple_project_paths_with_the_same_md5(self):
        first = self.project / "app/src/main/res/drawable/icon_first.png"
        second = self.project / "feature/src/main/res/mipmap-xxhdpi/icon_second.png"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        payload = self.image_bytes((6, 7, 8))
        first.write_bytes(payload)
        second.write_bytes(payload)

        result = self.run_scan()

        self.assertEqual(result.returncode, 0, result.stderr)
        resources = self.resources()
        self.assertEqual(len(resources), 2)
        self.assertEqual({record["md5"] for record in resources}, {hashlib.md5(payload).hexdigest()})
        self.assertEqual({record["path"] for record in resources}, {
            "app/src/main/res/drawable/icon_first.png",
            "feature/src/main/res/mipmap-xxhdpi/icon_second.png",
        })

    def test_deleted_project_image_is_removed_from_catalog_on_next_apply(self):
        first = self.input_dir / "first.png"
        second = self.input_dir / "second.png"
        self.write_image(first, (1, 2, 3))
        self.write_image(second, (4, 5, 6))
        self.assertEqual(self.run_skill("--image", first).returncode, 0)
        self.assertEqual(self.run_skill("--image", second).returncode, 0)
        output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_second.png"
        self.assertTrue(output.is_file())
        output.unlink()

        result = self.run_skill("--image", first)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(output.relative_to(self.project).as_posix(), {record["path"] for record in self.resources()})

    def test_invalid_legacy_manifests_are_removed_after_successful_apply(self):
        code_image = self.project / ".code-image"
        code_image.mkdir()
        (code_image / "first-abcdef.resources.json").write_text("{}", encoding="utf-8")
        (code_image / "resources.json").write_text("{}", encoding="utf-8")
        image = self.input_dir / "Latest.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(path.name for path in code_image.glob("*.json")), ["image.json"])

    def test_project_images_are_scanned_even_when_legacy_manifest_is_cleaned(self):
        code_image = self.project / ".code-image"
        code_image.mkdir()
        legacy_output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_legacy_asset.png"
        legacy_output.parent.mkdir(parents=True)
        self.write_image(legacy_output, (1, 2, 3))
        legacy_hash = hashlib.md5(legacy_output.read_bytes()).hexdigest()
        (code_image / "old-abcdef.resources.json").write_text(
            json.dumps({
                "resources": [{
                    "identity": "legacy",
                    "originalPath": "old.zip!/mipmap-xxhdpi/old.png",
                    "originalName": "old.png",
                    "originalHash": legacy_hash,
                    "outputPath": str(legacy_output.relative_to(self.project)),
                    "outputName": legacy_output.name,
                    "composeFile": None,
                    "namingVersion": 3,
                }],
            }),
            encoding="utf-8",
        )
        image = self.input_dir / "Latest.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        records = self.resources()
        self.assertEqual(len(records), 2)
        self.assertIn(legacy_hash, {record["md5"] for record in records})
        self.assertFalse((code_image / "old-abcdef.resources.json").exists())

    def test_resources_file_cannot_create_a_second_manifest(self):
        image = self.input_dir / "Latest.png"
        self.write_image(image)
        custom_manifest = self.project / ".code-image/custom.resources.json"

        result = self.run_skill("--image", image, "--resources-file", str(custom_manifest))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("image.json", result.stderr)
        self.assertFalse(custom_manifest.exists())
        self.assertFalse((self.project / ".code-image/image.json").exists())

    def test_explicit_asset_name_preserves_semantic_trailing_number(self):
        image = self.input_dir / "SketchPng0c6fdffe6b77d5b64d693c16b86d3bfb.png"
        self.write_image(image)

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
        existing = target_dir / "icon_group.png"
        existing.write_bytes(b"existing")
        image = self.input_dir / "Group 62.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target_dir / "icon_group_1.png").is_file())
        self.assertEqual(existing.read_bytes(), b"existing")

    def test_zip_uses_archive_name_prefix_and_copies_each_mipmap_directory(self):
        archive = self.input_dir / "L6.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("design/app/src/main/res/mipmap-xhdpi/Group 62.png", self.image_bytes((1, 2, 3)))
            zip_file.writestr("design/app/src/main/res/mipmap-xxhdpi/Group 62.png", self.image_bytes((4, 5, 6)))
            zip_file.writestr("design/readme.txt", "ignored")

        result = self.run_skill("--zip", archive)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.project / ".code-image/extracted").exists())
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xhdpi/icon_l6_group.png").is_file()
        )
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_l6_group.png").is_file()
        )
        self.assertEqual(len(self.resources()), 2)
        self.assertEqual(
            {record["source"] for record in self.resources()},
            {
                "L6.zip!/design/app/src/main/res/mipmap-xhdpi/Group 62.png",
                "L6.zip!/design/app/src/main/res/mipmap-xxhdpi/Group 62.png",
            },
        )
        self.assertFalse(
            any(path.name == "Group 62.png" for path in self.project.rglob("Group 62.png"))
        )
        source_hash = hashlib.md5(archive.read_bytes()).hexdigest()
        self.assertTrue((self.project / ".code-image/image.json").is_file())

        repeated = self.run_skill("--zip", archive)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.resources()), 2)
        self.assertFalse(
            (self.project / "app/src/main/res/mipmap-xhdpi/icon_l6_group_1.png").exists()
        )

    def test_zip_name_conflict_uses_incrementing_suffix_in_same_density(self):
        archive = self.input_dir / "L6.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("mipmap-xxhdpi/Group 62.png", self.image_bytes((1, 2, 3)))
            zip_file.writestr("mipmap-xxhdpi/Group  62.png", self.image_bytes((4, 5, 6)))

        result = self.run_skill("--zip", archive)

        self.assertEqual(result.returncode, 0, result.stderr)
        target_dir = self.project / "app/src/main/res/mipmap-xxhdpi"
        self.assertTrue((target_dir / "icon_l6_group.png").is_file())
        self.assertTrue((target_dir / "icon_l6_group_1.png").is_file())

    def test_chinese_name_uses_semantic_english_without_hash_or_image_prefix(self):
        image = self.input_dir / "今日目标.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_today_target.png").is_file()
        )

    def test_unknown_chinese_name_uses_pinyin_without_hash_or_image_prefix(self):
        image = self.input_dir / "测试图标.png"
        self.write_image(image)

        result = self.run_skill("--image", image)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_ce_shi_tu_biao.png").is_file()
        )

    def test_legacy_record_fields_are_removed_without_renaming_existing_resource(self):
        archive = self.input_dir / "L6.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("mipmap-xxhdpi/矩形.png", self.image_bytes())

        first = self.run_skill("--zip", archive)
        self.assertEqual(first.returncode, 0, first.stderr)

        manifest_path = self.project / ".code-image/image.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = manifest["resources"][0]
        current_output = self.project / record["path"]
        legacy_output = current_output.with_name("icon_l6_rectangle_old.png")
        current_output.rename(legacy_output)
        record["path"] = str(legacy_output.relative_to(self.project))
        record["name"] = legacy_output.name
        record["identifier"] = f"{record['path']}-{record['md5']}"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        migrated = self.run_skill("--zip", archive)

        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        self.assertTrue(legacy_output.is_file())
        self.assertFalse(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_l6_rectangle.png").exists()
        )
        migrated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(migrated_manifest["resources"][0]),
            {"md5", "identifier", "path", "name", "source"},
        )

    def test_zip_appends_source_to_final_project_catalog_record(self):
        archive = self.input_dir / "L6.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("design/mipmap-xxhdpi/返回.png", self.image_bytes((3, 4, 5)))

        result = self.run_skill("--zip", archive)

        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.resources()[0]
        self.assertEqual(record["source"], "L6.zip!/design/mipmap-xxhdpi/返回.png")
        self.assertEqual(record["path"], "app/src/main/res/mipmap-xxhdpi/icon_l6_fan_hui.png")
        self.assertEqual(record["name"], "icon_l6_fan_hui.png")
        self.assertEqual(record["identifier"], f"{record['path']}-{record['md5']}")

    def test_zip_without_mipmap_images_is_rejected_before_extraction(self):
        archive = self.input_dir / "not-mipmap.zip"
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("design/images/Group 62.png", b"image")

        result = self.run_skill("--zip", archive)

        source_hash = hashlib.md5(archive.read_bytes()).hexdigest()
        extracted = self.project / ".code-image/extracted" / f"not-mipmap-{source_hash}"
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--image", result.stderr)
        self.assertFalse(extracted.exists())

    def test_multiple_images_or_mixed_image_and_zip_are_rejected(self):
        first = self.input_dir / "first.png"
        second = self.input_dir / "second.png"
        archive = self.input_dir / "design.zip"
        self.write_image(first, (1, 1, 1))
        self.write_image(second, (2, 2, 2))
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

    def test_feature_compose_imports_into_its_own_module(self):
        image = self.input_dir / "Feature icon.png"
        self.write_image(image)

        result = self.run_skill("--image", image, "--compose", str(self.feature_compose))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (self.project / "feature/src/main/res/mipmap-xxhdpi/icon_feature_feature_icon.png").is_file()
        )
        self.assertFalse(
            (self.project / "app/src/main/res/mipmap-xxhdpi/icon_feature_feature_icon.png").exists()
        )

    def test_valid_cache_hit_does_not_rewrite_output(self):
        image = self.input_dir / "Stable.png"
        self.write_image(image)
        first = self.run_skill("--image", image)
        output = self.project / "app/src/main/res/mipmap-xxhdpi/icon_stable.png"
        fixed_time = 1_600_000_000_000_000_000
        os.utime(output, ns=(fixed_time, fixed_time))

        second = self.run_skill("--image", image)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(output.stat().st_mtime_ns, fixed_time)

    def test_invalid_image_content_is_rejected_before_manifest_write(self):
        image = self.input_dir / "broken.png"
        image.write_bytes(b"not-a-real-image")

        result = self.run_skill("--image", image)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("图片", result.stderr)
        self.assertFalse((self.project / ".code-image").exists())

    def test_zip_rejects_normalized_duplicate_and_extreme_compression(self):
        duplicate = self.input_dir / "duplicate.zip"
        with zipfile.ZipFile(duplicate, "w") as zip_file:
            payload = self.image_bytes()
            zip_file.writestr("mipmap-xhdpi/a.png", payload)
            zip_file.writestr("mipmap-xhdpi\\a.png", payload)

        duplicate_result = self.run_skill("--zip", duplicate)

        self.assertNotEqual(duplicate_result.returncode, 0)
        self.assertIn("重复", duplicate_result.stderr)

        compressed = self.input_dir / "compressed.zip"
        with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("mipmap-xhdpi/a.png", self.image_bytes())
            zip_file.writestr("payload.txt", b"0" * (2 * 1024 * 1024))

        compressed_result = self.run_skill("--zip", compressed)

        self.assertNotEqual(compressed_result.returncode, 0)
        self.assertIn("压缩比", compressed_result.stderr)


if __name__ == "__main__":
    unittest.main()
