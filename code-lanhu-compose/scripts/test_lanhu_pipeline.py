#!/usr/bin/env python3
"""lanhu_pipeline.py 的纯本地契约测试。"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("lanhu_pipeline.py")
SPEC = importlib.util.spec_from_file_location("lanhu_pipeline", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT_PATH}")
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class LanhuPipelineContractTest(unittest.TestCase):
    def test_inspect_writes_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="css/style.css" rel="stylesheet"><img src="images/a.png">')
                zipped.writestr("css/style.css", ".box { width: 10px; }")
                zipped.writestr("images/a.png", b"png")

            result = PIPELINE.inspect_archive(archive, root / "project")

            self.assertEqual(result["sourceName"], "design.zip")
            self.assertEqual(len(result["sourceSha256"]), 64)
            manifest_path = Path(result["artifactPath"]) / "source.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["sourceSha256"], result["sourceSha256"])
            self.assertEqual(manifest["html"]["path"], "index.html")

    def test_inspect_rejects_multiple_entry_html_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "ambiguous.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("a.html", "<html></html>")
                zipped.writestr("b.html", "<html></html>")

            with self.assertRaises(PIPELINE.PipelineError) as error:
                PIPELINE.inspect_archive(archive, Path(temp_dir) / "project")

            self.assertIn("多个 HTML", str(error.exception))

    def test_transition_requires_previous_phase(self) -> None:
        state = PIPELINE.new_state("abc", "Page.kt")
        with self.assertRaises(PIPELINE.PipelineError):
            PIPELINE.transition(state, "compiled")

        PIPELINE.transition(state, "inspected")
        PIPELINE.transition(state, "validated")
        self.assertEqual(state["phase"], "validated")

    def test_decision_rejects_arbitrary_shell(self) -> None:
        with self.assertRaises(PIPELINE.PipelineError):
            PIPELINE.validate_decision({"action": "run_shell", "command": "rm -rf /"})

        decision = PIPELINE.validate_decision(
            {
                "action": "ask_user",
                "question": "是否采用 16dp 间距？",
                "evidence": ["computed-style: gap=16px"],
            }
        )
        self.assertEqual(decision["action"], "ask_user")

    def test_expected_avd_is_explicit(self) -> None:
        self.assertTrue(PIPELINE.validate_device_name("K80", "K80"))
        with self.assertRaises(PIPELINE.PipelineError) as error:
            PIPELINE.validate_device_name("Pixel_8_API_35", "K80")
        self.assertIn("K80", str(error.exception))


if __name__ == "__main__":
    unittest.main()
