#!/usr/bin/env python3
"""code-image 独立图片对比脚本的行为测试。"""

from __future__ import annotations

import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).with_name("compare_images.py")


class CompareImagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.design = self.root / "design.png"
        self.app = self.root / "app.png"
        self.output = self.root / "report"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_image(self, path: Path, color: tuple[int, int, int], size: tuple[int, int] = (20, 20)) -> None:
        Image.new("RGB", size, color).save(path)

    def run_compare(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--design", str(self.design), "--app", str(self.app), "--output-dir", str(self.output), *extra],
            capture_output=True,
            text=True,
        )

    def test_identical_images_report_zero_difference_and_write_artifacts(self) -> None:
        self.write_image(self.design, (255, 255, 255))
        self.write_image(self.app, (255, 255, 255))

        result = self.run_compare()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.output / "diff.json").read_text(encoding="utf-8"))
        self.assertEqual(report["changedPixels"], 0)
        self.assertEqual(report["regions"], [])
        self.assertAlmostEqual(report["similarity"], 1.0)
        for name in ("diff.json", "diff-mask.png", "diff-heatmap.png", "diff-overlay.png"):
            self.assertTrue((self.output / name).is_file(), name)
        for key, name in (("mask", "diff-mask.png"), ("heatmap", "diff-heatmap.png"), ("overlay", "diff-overlay.png")):
            expected = hashlib.md5((self.output / name).read_bytes()).hexdigest()
            self.assertEqual(report["artifactMd5"][key], expected)

    def test_difference_is_grouped_into_a_region(self) -> None:
        self.write_image(self.design, (255, 255, 255))
        image = Image.new("RGB", (20, 20), (255, 255, 255))
        for x in range(4, 8):
            for y in range(5, 9):
                image.putpixel((x, y), (0, 0, 0))
        image.save(self.app)

        result = self.run_compare("--threshold", "8", "--min-region-area", "2")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.output / "diff.json").read_text(encoding="utf-8"))
        self.assertEqual(report["changedPixels"], 16)
        self.assertEqual(len(report["regions"]), 1)
        self.assertEqual(report["regions"][0]["bounds"], [4, 5, 4, 4])

    def test_aspect_ratio_mismatch_is_rejected(self) -> None:
        self.write_image(self.design, (255, 255, 255), (20, 20))
        self.write_image(self.app, (255, 255, 255), (30, 20))

        result = self.run_compare()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("宽高比", result.stderr)

    def test_output_artifact_cannot_overwrite_an_input_image(self) -> None:
        self.output.mkdir()
        self.design = self.output / "diff-mask.png"
        self.write_image(self.design, (255, 255, 255))
        original_hash = hashlib.md5(self.design.read_bytes()).hexdigest()
        self.write_image(self.app, (255, 255, 255))

        result = self.run_compare()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("覆盖输入", result.stderr)
        self.assertEqual(hashlib.md5(self.design.read_bytes()).hexdigest(), original_hash)


if __name__ == "__main__":
    unittest.main()
