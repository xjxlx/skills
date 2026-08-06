#!/usr/bin/env python3
"""code-image 单图片处理行为测试。"""

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("normalize_images.py")


class NormalizeImagesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.mipmap = self.project / "app/src/main/res/mipmap-nodpi"
        self.mipmap.mkdir(parents=True)
        self.compose = self.project / "app/src/main/java/com/example/ReportHomePage.kt"
        self.compose.parent.mkdir(parents=True)
        self.compose.write_text("@Composable fun ReportHomePage() = Unit\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_skill(self, image: Path, *extra: str):
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--image",
                str(image),
                "--project-root",
                str(self.project),
                *extra,
                "--apply",
            ],
            capture_output=True,
            text=True,
        )

    def resources(self) -> list[dict]:
        path = self.project / ".code-image/resources.json"
        return json.loads(path.read_text(encoding="utf-8"))["resources"]

    def test_single_image_without_compose_renames_only_that_image_and_writes_cache(self):
        image = self.mipmap / "Group 62.png"
        image.write_bytes(b"new")
        untouched = self.mipmap / "legacy.png"
        untouched.write_bytes(b"legacy")

        result = self.run_skill(image)

        self.assertEqual(result.returncode, 0, result.stderr)
        renamed = self.mipmap / "icon_group_62.png"
        self.assertTrue(renamed.is_file())
        self.assertTrue(untouched.is_file())
        self.assertFalse(image.exists())
        self.assertEqual([path.name for path in (self.project / ".code-image").iterdir()], ["resources.json"])
        record = self.resources()[0]
        self.assertEqual(record["originalName"], "Group 62.png")
        self.assertEqual(record["outputName"], "icon_group_62.png")
        self.assertIsNone(record["composeFile"])
        self.assertFalse((self.project / ".codex").exists())

    def test_optional_compose_adds_page_namespace(self):
        image = self.mipmap / "Group 62.png"
        image.write_bytes(b"new")

        result = self.run_skill(image, "--compose", str(self.compose))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.mipmap / "icon_report_home_group_62.png").is_file())
        record = self.resources()[0]
        self.assertEqual(record["composeFile"], "app/src/main/java/com/example/ReportHomePage.kt")

    def test_repeated_call_keeps_previous_output_and_updates_one_record(self):
        image = self.mipmap / "Group 62.png"
        image.write_bytes(b"new")
        first = self.run_skill(image, "--compose", str(self.compose))
        renamed = self.mipmap / "icon_report_home_group_62.png"

        second = self.run_skill(renamed)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertTrue(renamed.is_file())
        self.assertEqual(len(self.resources()), 1)
        self.assertEqual(self.resources()[0]["outputName"], renamed.name)
        self.assertEqual(
            self.resources()[0]["originalPath"],
            "app/src/main/res/mipmap-nodpi/Group 62.png",
        )

    def test_existing_target_is_not_overwritten(self):
        existing = self.mipmap / "icon_group_62.png"
        existing.write_bytes(b"existing")
        image = self.mipmap / "Group 62.png"
        image.write_bytes(b"new")

        result = self.run_skill(image)

        self.assertEqual(result.returncode, 0, result.stderr)
        renamed = next(path for path in self.mipmap.iterdir() if path.name != existing.name)
        self.assertRegex(renamed.name, r"^icon_group_62_[0-9a-f]{6}\.png$")
        self.assertEqual(existing.read_bytes(), b"existing")

    def test_multiple_image_arguments_are_rejected(self):
        first = self.mipmap / "first.png"
        second = self.mipmap / "second.png"
        first.write_bytes(b"first")
        second.write_bytes(b"second")

        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--image",
                str(first),
                "--image",
                str(second),
                "--project-root",
                str(self.project),
                "--apply",
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("只允许一个", result.stderr)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())

    def test_changed_image_at_a_reused_original_path_does_not_overwrite_old_output(self):
        first = self.mipmap / "Group 62.png"
        first.write_bytes(b"first")
        initial = self.run_skill(first)
        old_output = self.mipmap / "icon_group_62.png"
        replacement = self.mipmap / "Group 62.png"
        replacement.write_bytes(b"replacement")

        updated = self.run_skill(replacement)

        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertEqual(old_output.read_bytes(), b"first")
        self.assertTrue(any(path.name.startswith("icon_group_62_") for path in self.mipmap.iterdir()))
        self.assertEqual(len(self.resources()), 2)


if __name__ == "__main__":
    unittest.main()
