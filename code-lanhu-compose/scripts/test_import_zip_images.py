#!/usr/bin/env python3
"""蓝湖 ZIP 图片导入清单的最小行为测试。"""

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("import_zip_images.py")
NORMALIZE_SCRIPT = Path(__file__).resolve().parents[2] / "code-image/scripts/normalize_images.py"


class ImportZipImagesTest(unittest.TestCase):
    def test_import_writes_hashed_manifest_and_stages_only_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "design.zip"
            target = root / "app/src/main/res/mipmap-nodpi"
            manifest = root / ".code-lanhu-compose/images/design-a1b2c3d4.json"
            compose = root / "app/src/main/java/com/example/report/TestPage.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("@Composable fun TestPage() = Unit\n", encoding="utf-8")
            target.mkdir(parents=True)
            legacy = target / "legacy.png"
            legacy.write_bytes(b"legacy")
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("design/img/Group 62.png", b"image-data")
                zip_file.writestr("design/readme.txt", "not an image")

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--zip",
                    str(archive),
                    "--mipmap-path",
                    str(target),
                    "--manifest",
                    str(manifest),
                    "--project-root",
                    str(root),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["sourceName"], "design.zip")
            self.assertEqual(len(data["images"]), 1)
            image = data["images"][0]
            self.assertEqual(image["originalName"], "Group 62.png")
            self.assertEqual(image["sha256"], hashlib.sha256(b"image-data").hexdigest())
            staged_path = root / image["targetPath"]
            self.assertTrue(staged_path.is_file())
            self.assertEqual(staged_path.read_bytes(), b"image-data")
            self.assertTrue(staged_path.name.startswith(".lanhu-import-"))

            normalized = subprocess.run(
                [
                    "python3",
                    str(NORMALIZE_SCRIPT),
                    "--compose",
                    str(compose),
                    "--mipmap-path",
                    str(target),
                    "--project-root",
                    str(root),
                    "--input-manifest",
                    str(manifest),
                    "--apply",
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(normalized.returncode, 0, normalized.stderr)
            self.assertTrue((target / "icon_test_group_62.png").is_file())
            self.assertTrue(legacy.is_file())


if __name__ == "__main__":
    unittest.main()
