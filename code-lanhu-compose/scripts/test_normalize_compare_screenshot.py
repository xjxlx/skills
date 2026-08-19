#!/usr/bin/env python3
"""normalize_compare_screenshot.py 的契约测试。"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).with_name("normalize_compare_screenshot.py")
SPEC = importlib.util.spec_from_file_location("normalize_compare_screenshot", SCRIPT)
assert SPEC and SPEC.loader
NORMALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NORMALIZER)


class NormalizeScreenshotTests(unittest.TestCase):
    @staticmethod
    def _image(path: Path, size: tuple[int, int], color: str) -> None:
        Image.new("RGBA", size, color).save(path)

    def test_output_must_not_overwrite_an_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            design = root / "design.png"
            app = root / "app.png"
            self._image(design, (100, 100), "red")
            self._image(app, (200, 100), "blue")
            before = app.read_bytes()

            with self.assertRaisesRegex(ValueError, "输出文件不能覆盖"):
                NORMALIZER.normalize(design, app, app, "fill", None)

            self.assertEqual(app.read_bytes(), before)

    def test_fit_rejects_aspect_ratio_distortion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            design = root / "design.png"
            app = root / "app.png"
            output = root / "normalized.png"
            self._image(design, (100, 100), "red")
            self._image(app, (200, 100), "blue")

            with self.assertRaisesRegex(ValueError, "宽高比"):
                NORMALIZER.normalize(design, app, output, "fit", (0, 0, 100, 50))

            self.assertFalse(output.exists())

    def test_fit_preserves_matching_canvas_and_writes_expected_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            design = root / "design.png"
            app = root / "app.png"
            output = root / "normalized.png"
            self._image(design, (100, 50), "red")
            self._image(app, (300, 200), "blue")

            result = NORMALIZER.normalize(design, app, output, "fit", (20, 30, 200, 100))

            with Image.open(output) as normalized:
                self.assertEqual(normalized.size, (100, 50))
            self.assertEqual(result["scaleX"], result["scaleY"])
            self.assertEqual(result["aspectRatioError"], 0.0)
            provenance = NORMALIZER.provenance_path(output)
            self.assertTrue(provenance.is_file())
            self.assertEqual(result["outputMd5"], NORMALIZER.md5_file(output))


if __name__ == "__main__":
    unittest.main()
