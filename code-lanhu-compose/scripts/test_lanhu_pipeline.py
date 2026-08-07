#!/usr/bin/env python3
"""lanhu_pipeline.py 的纯本地契约测试。"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("lanhu_pipeline.py")
SPEC = importlib.util.spec_from_file_location("lanhu_pipeline", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT_PATH}")
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class LanhuPipelineContractTest(unittest.TestCase):
    def test_gradle_command_prefers_project_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

            self.assertEqual(PIPELINE.gradle_command(project_root), ["./gradlew"])

    def test_gradle_command_falls_back_to_system_gradle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(PIPELINE.shutil, "which", return_value="/usr/local/bin/gradle"):
                self.assertEqual(PIPELINE.gradle_command(Path(temp_dir)), ["gradle"])

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

    def test_repair_round_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")
            PIPELINE.inspect_archive(archive, root / "project")
            artifact, _, state = PIPELINE.load_source(archive, root / "project")
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            PIPELINE.atomic_json(artifact / "diff.json", {"pixelError": 1})
            PIPELINE._write_state(artifact, state)
            for _ in range(3):
                PIPELINE.mark_diff(archive, root / "project", artifact / "diff.json", "repair")
                _, _, state = PIPELINE.load_source(archive, root / "project")
                PIPELINE.transition(state, "compiled")
                PIPELINE.transition(state, "installed")
                PIPELINE.transition(state, "screenshot")
                PIPELINE._write_state(artifact, state)
            with self.assertRaises(PIPELINE.PipelineError):
                PIPELINE.mark_diff(archive, root / "project", artifact / "diff.json", "repair")


if __name__ == "__main__":
    unittest.main()
