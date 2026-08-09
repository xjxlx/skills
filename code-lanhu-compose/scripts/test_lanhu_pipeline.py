#!/usr/bin/env python3
"""lanhu_pipeline.py 的纯本地契约测试。"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen


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

    def test_discover_compile_task_uses_target_module_debug_kotlin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
            compose = root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("", encoding="utf-8")
            gradle_output = "\n".join(
                [
                    "app:compileReleaseKotlin - Compiles the release kotlin.",
                    "app:compileDebugKotlin - Compiles the debug kotlin.",
                    "app:compileDebugAndroidTestKotlin - Compiles the debug android test kotlin.",
                    "common:compileDebugKotlin - Compiles the debug kotlin.",
                ]
            )
            completed = SimpleNamespace(returncode=0, stdout=gradle_output, stderr="")
            with patch.object(PIPELINE.subprocess, "run", return_value=completed):
                self.assertEqual(
                    PIPELINE.discover_compile_task(root, compose),
                    ":app:compileDebugKotlin",
                )

    def test_discover_compile_task_stops_on_ambiguous_debug_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
            compose = root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("", encoding="utf-8")
            completed = SimpleNamespace(
                returncode=0,
                stdout="app:compileFooDebugKotlin - Foo\napp:compileBarDebugKotlin - Bar\n",
                stderr="",
            )
            with patch.object(PIPELINE.subprocess, "run", return_value=completed):
                with self.assertRaises(PIPELINE.PipelineError) as error:
                    PIPELINE.discover_compile_task(root, compose)
            self.assertIn("多个 Debug Kotlin", str(error.exception))

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

    def test_inspect_reuses_matching_manifest_without_resetting_pipeline_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")

            first = PIPELINE.inspect_archive(archive, project_root)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            PIPELINE.transition(state, "validated")
            PIPELINE._write_state(artifact, state)

            with patch.object(PIPELINE, "detect_repeated_blocks", side_effect=AssertionError("不应重复解析 ZIP")):
                second = PIPELINE.inspect_archive(archive, project_root)

            self.assertTrue(second["cacheHit"])
            self.assertEqual(second["phase"], "validated")
            self.assertEqual(second["artifactPath"], first["artifactPath"])

    def test_inspect_writes_repeated_block_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "index.html",
                    '<link href="style.css" rel="stylesheet"><div class="list"><div class="block_4"></div><div class="block_5"></div></div>',
                )
                zipped.writestr(
                    "style.css",
                    ".block_5 { width: 21.13vw; height: 10.57vw; background: url(img/a.png) 0 0 no-repeat; "
                    "background-size: 21.18vw 10.62vw; }\n"
                    ".block_4 { width: 21vw; height: 10.57vw; background: url(img/b.png) 0 0 no-repeat; "
                    "background-size: 21.06vw 10.62vw; }",
                )

            result = PIPELINE.inspect_archive(archive, root / "project")

            candidates_path = Path(result["artifactPath"]) / "repeated-block-candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            self.assertEqual(candidates["candidateCount"], 1)
            self.assertEqual(candidates["candidates"][0]["nodeNames"], ["block_4", "block_5"])
            self.assertEqual(candidates["candidates"][0]["listAxis"], "requires-computed-layout")

    def test_inspect_rejects_multiple_entry_html_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "ambiguous.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("a.html", "<html></html>")
                zipped.writestr("b.html", "<html></html>")

            with self.assertRaises(PIPELINE.PipelineError) as error:
                PIPELINE.inspect_archive(archive, Path(temp_dir) / "project")

            self.assertIn("多个 HTML", str(error.exception))

    def test_design_server_serves_entry_and_stops_after_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "lanhu/index.html",
                    '<html><head><link href="style.css" rel="stylesheet"></head><body>design-server-ok</body></html>',
                )
                zipped.writestr("lanhu/style.css", ".page { width: 100px; }")

            PIPELINE.inspect_archive(archive, project_root)
            started = PIPELINE.start_design_server(archive, project_root, port=0)
            state_path = Path(started["statePath"])
            try:
                self.assertTrue(started["url"].startswith("http://127.0.0.1:"))
                self.assertTrue(state_path.is_file())
                with urlopen(started["url"], timeout=3) as response:
                    self.assertIn(b"design-server-ok", response.read())
            finally:
                stopped = PIPELINE.stop_design_server(archive, project_root)

            self.assertEqual(stopped["status"], "stopped")
            self.assertFalse(state_path.exists())
            self.assertFalse(PIPELINE.is_pid_alive(started["pid"]))

    def test_design_server_reuses_matching_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "lanhu/index.html",
                    '<html><head><link href="style.css" rel="stylesheet"></head><body>cached-source</body></html>',
                )
                zipped.writestr("lanhu/style.css", ".page { width: 100px; }")

            PIPELINE.inspect_archive(archive, project_root)
            first = PIPELINE.start_design_server(archive, project_root)
            PIPELINE.stop_design_server(archive, project_root)
            with patch.object(PIPELINE, "_safe_extract_archive", side_effect=AssertionError("不应重复解压 ZIP")):
                second = PIPELINE.start_design_server(archive, project_root)
            try:
                self.assertTrue(second["sourceReused"])
                with urlopen(second["url"], timeout=3) as response:
                    self.assertIn(b"cached-source", response.read())
            finally:
                PIPELINE.stop_design_server(archive, project_root)

    def test_采集设计会写入中文设计解析文件(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "lanhu/index.html",
                    "<html><head><link href=\"style.css\" rel=\"stylesheet\"></head>"
                    "<body><main class=\"page\"><span class=\"title\">设计标题</span></main></body></html>",
                )
                zipped.writestr(
                    "lanhu/style.css",
                    ".page { width: 320px; height: 180px; padding: 12px; background: #ffffff; }"
                    ".title { color: rgb(1, 2, 3); font-size: 20px; }",
                )

            inspected = PIPELINE.inspect_archive(archive, project_root)
            PIPELINE.start_design_server(archive, project_root)
            try:
                first_result = PIPELINE.capture_rendered_design(archive, project_root)
            finally:
                PIPELINE.stop_design_server(archive, project_root)
            result = PIPELINE.capture_rendered_design(archive, project_root)
            cached_start = PIPELINE.start_design_server(archive, project_root)

            design_path = Path(result["designPath"])
            design = json.loads(design_path.read_text(encoding="utf-8"))
            self.assertEqual(design_path.name, "设计解析.json")
            screenshot_path = Path(result["screenshotPath"])
            self.assertEqual(screenshot_path, Path(inspected["artifactPath"]) / "runs" / "设计截图.png")
            self.assertEqual(screenshot_path, Path(first_result["screenshotPath"]))
            self.assertTrue(screenshot_path.is_file())
            self.assertTrue(result["cacheHit"])
            self.assertTrue(cached_start["cacheHit"])
            self.assertEqual(design["sourceSha256"], inspected["sourceSha256"])
            self.assertEqual(design["设计根节点"]["选择器"], ".page")
            self.assertEqual(design["设计画布"]["宽度像素"], 344)
            self.assertEqual(design["设计画布"]["高度像素"], 204)

    def test_design_screenshot_registration_always_reclaims_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "lanhu/index.html",
                    '<html><head><link href="style.css" rel="stylesheet"></head><body>design-server-ok</body></html>',
                )
                zipped.writestr("lanhu/style.css", ".page { width: 100px; }")

            inspected = PIPELINE.inspect_archive(archive, project_root)
            started = PIPELINE.start_design_server(archive, project_root)
            PIPELINE.atomic_json(
                Path(inspected["artifactPath"]) / "设计解析.json",
                {"sourceSha256": inspected["sourceSha256"]},
            )
            image = Path(inspected["artifactPath"]) / "runs" / "设计截图.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")

            result = PIPELINE.complete_design_screenshot(archive, project_root, image)

            self.assertEqual(result["status"], "recorded")
            self.assertFalse(Path(started["statePath"]).exists())
            self.assertFalse(PIPELINE.is_pid_alive(started["pid"]))

    def test_k80_screenshots_share_runs_directory_and_increment_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")

            inspected = PIPELINE.inspect_archive(archive, project_root)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed"):
                PIPELINE.transition(state, phase)
            PIPELINE._write_state(artifact, state)
            adb_result = SimpleNamespace(returncode=0, stdout="K80\n", stderr=b"")
            with patch.object(PIPELINE.subprocess, "run", return_value=adb_result):
                first = PIPELINE.screenshot_k80(archive, project_root, "emulator-5554")
                second = PIPELINE.screenshot_k80(archive, project_root, "emulator-5554")

            runs_root = Path(inspected["artifactPath"]) / "runs"
            self.assertEqual(Path(first["image"]), runs_root / "应用截图.png")
            self.assertEqual(Path(second["image"]), runs_root / "应用截图_1.png")
            self.assertEqual(
                sorted(path.name for path in runs_root.iterdir()),
                ["应用截图.png", "应用截图_1.png"],
            )

    def test_transition_requires_previous_phase(self) -> None:
        state = PIPELINE.new_state("abc", "Page.kt")
        with self.assertRaises(PIPELINE.PipelineError):
            PIPELINE.transition(state, "compiled")

        PIPELINE.transition(state, "inspected")
        PIPELINE.transition(state, "validated")
        self.assertEqual(state["phase"], "validated")

    def test_compose_source_rejects_negative_padding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            compose_path = Path(temp_dir) / "TestPage.kt"
            compose_path.write_text(
                "Box(modifier = Modifier.padding(top = scale.dp(57f), start = scale.dp(-8f)))",
                encoding="utf-8",
            )

            with self.assertRaises(PIPELINE.PipelineError) as error:
                PIPELINE.validate_compose_source(compose_path)

            self.assertIn("padding", str(error.exception))
            self.assertIn("非负", str(error.exception))
            self.assertIn("start", str(error.exception))
            self.assertIn("offset", str(error.exception))

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
