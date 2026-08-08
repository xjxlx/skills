#!/usr/bin/env python3
"""重复卡片候选识别的回归测试。"""

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("detect_repeated_blocks.py")
SPEC = importlib.util.spec_from_file_location("detect_repeated_blocks", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT}")
DETECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DETECTOR)


class RepeatedBlockDetectorTest(unittest.TestCase):
    def test_groups_near_equal_background_cards_and_rejects_outlier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<div class="list"><div class="block_4"></div><div class="block_5"></div><div class="block_6"></div></div>')
                zipped.writestr(
                    "style.css",
                    ".block_5 { width: 21.13vw; height: 10.57vw; background: url(img/a.png) -0.07vw 0 no-repeat; "
                    "background-size: 21.18vw 10.62vw; }\n"
                    ".block_4 { width: 21vw; height: 10.57vw; background: url(img/b.png) -0.07vw 0 no-repeat; "
                    "background-size: 21.06vw 10.62vw; }\n"
                    ".block_6 { width: 24vw; height: 10.57vw; background: url(img/c.png) 0 0 no-repeat; "
                    "background-size: 24vw 10.62vw; }",
                )

            result = DETECTOR.detect_repeated_blocks(archive, ["style.css"], "index.html")

            self.assertEqual(result["candidateCount"], 1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["nodeNames"], ["block_4", "block_5"])
            self.assertEqual(candidate["metricRanges"]["width"], {"min": 21.0, "max": 21.13, "unit": "vw"})
            self.assertEqual(candidate["sharedParent"], {"tag": "div", "classTokens": ["list"]})
            self.assertEqual(candidate["listAxis"], "requires-computed-layout")

    def test_does_not_mix_different_dimension_units(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<div><div class="block_px"></div><div class="block_vw"></div></div>')
                zipped.writestr(
                    "style.css",
                    ".block_px { width: 20px; height: 10px; background: url(img/a.png); background-size: 20px 10px; }\n"
                    ".block_vw { width: 20vw; height: 10vw; background: url(img/b.png); background-size: 20vw 10vw; }",
                )

            result = DETECTOR.detect_repeated_blocks(archive, ["style.css"], "index.html")

            self.assertEqual(result["candidateCount"], 0)

    def test_rejects_similar_cards_without_a_shared_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<main><div><div class="block_4"></div></div><aside><div class="block_5"></div></aside></main>')
                zipped.writestr(
                    "style.css",
                    ".block_4 { width: 20px; height: 10px; background: url(img/a.png); background-size: 20px 10px; }\n"
                    ".block_5 { width: 20px; height: 10px; background: url(img/b.png); background-size: 20px 10px; }",
                )

            result = DETECTOR.detect_repeated_blocks(archive, ["style.css"], "index.html")

            self.assertEqual(result["candidateCount"], 0)


if __name__ == "__main__":
    unittest.main()
