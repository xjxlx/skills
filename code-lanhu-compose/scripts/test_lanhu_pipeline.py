#!/usr/bin/env python3
"""lanhu_pipeline.py 的纯本地契约测试。"""

from __future__ import annotations

import importlib.util
import base64
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
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
    @staticmethod
    def _write_cached_design(artifact: Path, source: dict, screenshot: Path) -> None:
        PIPELINE.atomic_json(
            artifact / "设计解析.json",
            {
                "版本": PIPELINE.DESIGN_DOCUMENT_VERSION,
                "sourceMd5": source["sourceMd5"],
                "设计根节点": {"选择器": "body"},
                "节点": [],
                "文本片段": [],
                "设计截图Md5": PIPELINE.md5_file(screenshot),
            },
        )

    def test_user_input_pause_is_persisted_next_to_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", "<main>缺少 CSS 引用</main>")

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = PIPELINE.main(
                    ["inspect", "--zip", str(archive), "--project-root", str(project_root)]
                )

            self.assertEqual(exit_code, 2)
            payload = json.loads(stderr.getvalue())
            request = Path(payload["requestPath"])
            self.assertTrue(request.is_file())
            recorded = json.loads(request.read_text(encoding="utf-8"))
            self.assertEqual(recorded["sourceMd5"], PIPELINE.md5_file(archive))
            self.assertEqual(recorded["command"], "inspect")
            self.assertIn("CSS", recorded["question"])

    def test_reuses_zip_md5_within_one_cli_process_when_file_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "design.zip"
            archive.write_bytes(b"stable-zip-content")
            with patch.object(PIPELINE.hashlib, "md5", wraps=PIPELINE.hashlib.md5) as digest:
                first = PIPELINE.md5_file(archive)
                second = PIPELINE.md5_file(archive)

            self.assertEqual(first, second)
            self.assertEqual(digest.call_count, 1)

    def test_compare_screenshots_calls_code_image_and_records_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")

            inspected = PIPELINE.inspect_archive(archive, project_root)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            runs = artifact / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            design = runs / "设计截图.png"
            app = runs / "应用截图.png"
            image_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            design.write_bytes(image_bytes)
            app.write_bytes(image_bytes)
            self._write_cached_design(artifact, source, design)
            state["lastScreenshot"] = str(app)
            state["lastScreenshotMd5"] = PIPELINE.md5_file(app)
            PIPELINE._write_state(artifact, state)

            result = PIPELINE.compare_screenshots(archive, project_root, app)

            report = Path(result["report"])
            self.assertTrue(report.is_file())
            report_data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(report_data["sourceMd5"], source["sourceMd5"])
            self.assertEqual(report_data["appScreenshot"], str(app))
            self.assertEqual(result["phase"], "screenshot")
            _, _, saved_state = PIPELINE.load_source(archive, project_root)
            self.assertEqual(saved_state["comparison"]["report"], str(report))

    def test_mark_diff_without_report_runs_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")

            PIPELINE.inspect_archive(archive, project_root)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            runs = artifact / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            image_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            design = runs / "设计截图.png"
            design.write_bytes(image_bytes)
            self._write_cached_design(artifact, source, design)
            app = runs / "应用截图.png"
            app.write_bytes(image_bytes)
            state["lastScreenshot"] = str(app)
            state["lastScreenshotMd5"] = PIPELINE.md5_file(app)
            PIPELINE._write_state(artifact, state)

            result = PIPELINE.mark_diff(archive, project_root, None, "pass")

            self.assertEqual(result["phase"], "diffed")
            self.assertTrue(Path(result["report"]).is_file())
            _, _, saved_state = PIPELINE.load_source(archive, project_root)
            self.assertEqual(saved_state["comparison"]["report"], result["report"])

    def test_mark_diff_rejects_screenshot_content_changed_after_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")
            PIPELINE.inspect_archive(archive, project_root)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            image_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            runs = artifact / "runs"
            runs.mkdir(parents=True)
            design = runs / "设计截图.png"
            design.write_bytes(image_bytes)
            self._write_cached_design(artifact, source, design)
            app = runs / "应用截图.png"
            app.write_bytes(image_bytes)
            state["lastScreenshot"] = str(app)
            state["lastScreenshotMd5"] = PIPELINE.md5_file(app)
            PIPELINE._write_state(artifact, state)
            report = Path(PIPELINE.compare_screenshots(archive, project_root, app)["report"])
            app.write_bytes(b"tampered")

            with self.assertRaisesRegex(PIPELINE.PipelineError, "内容.*发生变化"):
                PIPELINE.mark_diff(archive, project_root, report, "pass")

    def test_mark_diff_rejects_unregistered_or_incomplete_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")
            PIPELINE.inspect_archive(archive, project_root)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            forged = artifact / "forged.json"
            forged.write_text("{}", encoding="utf-8")
            PIPELINE._write_state(artifact, state)

            with self.assertRaises(PIPELINE.PipelineError):
                PIPELINE.mark_diff(archive, project_root, forged, "pass")

    def test_gradle_command_prefers_project_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

            self.assertEqual(PIPELINE.gradle_command(project_root), ["./gradlew"])

    def test_gradle_command_falls_back_to_system_gradle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(PIPELINE.shutil, "which", return_value="/usr/local/bin/gradle"):
                self.assertEqual(PIPELINE.gradle_command(Path(temp_dir)), ["gradle"])

    def test_infers_resource_package_from_target_module_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            compose = project_root / "app" / "src" / "main" / "java" / "com" / "example" / "ui" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example.ui\n", encoding="utf-8")
            (project_root / "app" / "build.gradle.kts").write_text(
                'android { namespace = "com.example" }\n',
                encoding="utf-8",
            )

            self.assertEqual(PIPELINE.infer_resource_package(project_root, compose), "com.example")

    def test_infers_backticked_kotlin_keyword_package_and_resource_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example.`when`\nimport com.assets.`when`.R\n", encoding="utf-8")

            self.assertEqual(PIPELINE.infer_package_name(compose), "com.example.when")
            self.assertEqual(PIPELINE.infer_resource_package(root, compose), "com.assets.when")

    def test_derive_package_task_from_compile_task(self) -> None:
        self.assertEqual(
            PIPELINE.derive_package_task(":app:compileDebugKotlin"),
            ":app:assembleDebug",
        )
        self.assertEqual(
            PIPELINE.derive_package_task(":feature:compileFooDebugKotlin"),
            ":feature:assembleFooDebug",
        )
        with self.assertRaises(PIPELINE.PipelineError):
            PIPELINE.derive_package_task(":app:assembleDebug")

    def test_package_debug_rejects_apk_outside_target_module_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".page { width: 10px; }")
            PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            state["preflightTask"] = ":app:compileDebugKotlin"
            PIPELINE._write_state(artifact, state)
            unrelated = project_root / "unrelated.apk"
            unrelated.write_bytes(b"not-app-output")

            with patch.object(PIPELINE, "_run_fixed") as run:
                with self.assertRaisesRegex(PIPELINE.PipelineError, "APK 输出目录"):
                    PIPELINE.package_debug(archive, project_root, unrelated)
            run.assert_not_called()

    def test_variant_apk_outputs_only_accepts_matching_metadata_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "apk"
            debug = root / "foo" / "debug"
            release = root / "foo" / "release"
            debug.mkdir(parents=True)
            release.mkdir(parents=True)
            (debug / "app-foo-debug.apk").write_bytes(b"debug")
            (release / "app-foo-release.apk").write_bytes(b"release")
            PIPELINE.atomic_json(debug / "output-metadata.json", {
                "variantName": "fooDebug",
                "elements": [{"outputFile": "app-foo-debug.apk"}],
            })
            PIPELINE.atomic_json(release / "output-metadata.json", {
                "variantName": "fooRelease",
                "elements": [{"outputFile": "app-foo-release.apk"}],
            })

            outputs = PIPELINE.variant_apk_outputs(root, "fooDebug")

            self.assertEqual(outputs, {(debug / "app-foo-debug.apk").resolve()})
            self.assertEqual(PIPELINE.variant_name_from_compile_task(":app:compileFooDebugKotlin"), "fooDebug")

    def test_install_k80_rejects_apk_modified_after_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".page { width: 10px; }")
            PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            apk = project_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b"packaged")
            state["preflightTask"] = ":app:compileDebugKotlin"
            state["packagedApk"] = str(apk.resolve())
            state["packagedComposeMd5"] = PIPELINE.md5_file(compose)
            state["packagedApkMd5"] = PIPELINE.md5_file(apk)
            PIPELINE._write_state(artifact, state)
            apk.write_bytes(b"replaced-after-packaging")

            with patch.object(PIPELINE.subprocess, "run") as run:
                with self.assertRaisesRegex(PIPELINE.PipelineError, "内容已变化"):
                    PIPELINE.install_k80(archive, project_root, "emulator-5554", "K80", apk)

            run.assert_not_called()

    def test_install_k80_rejects_apk_older_than_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("@Composable fun Page() {}\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><div></div>')
                zipped.writestr("style.css", ".page { width: 10px; }")

            PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            state["composeFile"] = str(compose.resolve())
            state["preflightTask"] = ":app:compileDebugKotlin"
            PIPELINE._write_state(artifact, state)

            apk = project_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b"stale")
            os.utime(apk, (1, 1))

            with patch.object(PIPELINE.subprocess, "run") as run:
                with self.assertRaises(PIPELINE.PipelineError) as error:
                    PIPELINE.install_k80(archive, project_root, "emulator-5554", "K80", apk)

            run.assert_not_called()
            self.assertIn("过期", str(error.exception))

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

    def test_user_selected_compile_task_must_match_an_actual_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("", encoding="utf-8")
            completed = SimpleNamespace(
                returncode=0,
                stdout="app:compileFooDebugKotlin - Foo\napp:compileBarDebugKotlin - Bar\n",
                stderr="",
            )
            with patch.object(PIPELINE.subprocess, "run", return_value=completed):
                selected = PIPELINE.discover_compile_task(root, compose, ":app:compileFooDebugKotlin")
                with self.assertRaisesRegex(PIPELINE.PipelineError, "候选"):
                    PIPELINE.discover_compile_task(root, compose, ":app:compileMissingDebugKotlin")

            self.assertEqual(selected, ":app:compileFooDebugKotlin")

    def test_select_compile_task_persists_choice_for_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".page { width: 10px; }")
            PIPELINE.inspect_archive(archive, project_root, compose)
            PIPELINE.validate_project(archive, project_root, compose)

            task = ":app:compileFooDebugKotlin"
            artifact, _, _ = PIPELINE.load_source(archive, project_root)
            (artifact / "needs-user-input.json").write_text("{}", encoding="utf-8")
            with patch.object(PIPELINE, "discover_compile_task", return_value=task) as discover:
                result = PIPELINE.select_compile_task(archive, project_root, task)

            self.assertEqual(result["task"], task)
            discover.assert_called_once_with(project_root.resolve(), compose.resolve(), task)
            _, _, state = PIPELINE.load_source(archive, project_root)
            self.assertEqual(state["selectedCompileTask"], task)
            self.assertFalse((artifact / "needs-user-input.json").exists())

    def test_unicode_zip_name_uses_same_artifact_identity_for_pipeline_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "设计 稿.zip"
            archive.write_bytes(b"zip")
            source_md5 = PIPELINE.md5_file(archive)

            pipeline_artifact = PIPELINE.artifact_dir(archive, root / "project", source_md5)
            image_artifact = PIPELINE.image_artifact_directory(archive, source_md5, root / "project")

            self.assertEqual(pipeline_artifact, image_artifact)

    def test_run_fixed_generates_compose_from_dom_before_compile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("@Composable fun Page() {}\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".page { width: 10px; }")

            inspected = PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported"):
                PIPELINE.transition(state, phase)
            state["composeFile"] = str(compose.resolve())
            PIPELINE._write_state(artifact, state)

            with patch.object(PIPELINE, "ensure_design_evidence") as ensure_design, patch.object(
                PIPELINE, "generate_compose_from_dom", return_value={"outputPath": str(compose)}
            ) as generate, patch.object(PIPELINE, "compile_project") as compile_project:
                compiled = PIPELINE.run_fixed_pipeline(archive, project_root, compose)
                self.assertEqual(compiled["status"], "compose_generated_and_compile_started")
                ensure_design.assert_called_once()
                generate.assert_called_once_with(archive.resolve(), project_root.resolve(), compose.resolve())
                compile_project.assert_called_once_with(archive.resolve(), project_root.resolve())
            _, _, updated = PIPELINE.load_source(archive, project_root)
            self.assertEqual(updated["phase"], "assets_imported")

    def test_run_fixed_validates_target_before_starting_browser_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            outside_compose = root / "Page.kt"
            outside_compose.write_text("package com.example\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("style.css", "main { width: 100px; }")

            with patch.object(PIPELINE, "ensure_design_evidence") as ensure_design:
                with self.assertRaisesRegex(PIPELINE.PipelineError, "项目根目录内"):
                    PIPELINE.run_fixed_pipeline(archive, project_root, outside_compose)

            ensure_design.assert_not_called()

    def test_run_fixed_skips_compile_when_generated_hash_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n@Composable fun Page() {}\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("style.css", "main { width: 100px; }")

            PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            state["composeFile"] = str(compose.resolve())
            state["preflightTask"] = ":app:compileDebugKotlin"
            PIPELINE.atomic_json(
                artifact / "设计解析.json",
                {"版本": PIPELINE.DESIGN_DOCUMENT_VERSION, "sourceMd5": source["sourceMd5"], "节点": []},
            )
            PIPELINE.atomic_json(
                artifact / "images.json",
                {"version": 2, "sourceMd5": source["sourceMd5"], "images": []},
            )
            generation_input = PIPELINE.generation_input_fingerprint(artifact, project_root, compose)
            compile_input = PIPELINE.compile_input_snapshot(
                artifact,
                project_root,
                compose,
                state["preflightTask"],
            )
            state["composeGeneration"] = {
                "composeMd5": PIPELINE.md5_file(compose),
                "inputFingerprint": generation_input,
            }
            state["lastCompiledComposeMd5"] = PIPELINE.md5_file(compose)
            state["compileInputFingerprint"] = compile_input["fingerprint"]
            PIPELINE._write_state(artifact, state)

            with patch.object(PIPELINE, "ensure_design_evidence", return_value={"status": "cached"}), patch.object(
                PIPELINE, "compile_project"
            ) as compile_project:
                result = PIPELINE.run_fixed_pipeline(archive, project_root, compose)

            self.assertEqual(result["status"], "unchanged")
            compile_project.assert_not_called()

    def test_manual_compose_adaptation_compiles_once_then_hits_hot_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            compose.parent.mkdir(parents=True)
            compose.write_text("package com.example\n@Composable fun Page() {}\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("style.css", "main { width: 100px; }")

            PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            state["composeFile"] = str(compose.resolve())
            state["preflightTask"] = ":app:compileDebugKotlin"
            PIPELINE.atomic_json(artifact / "设计解析.json", {"版本": 4, "sourceMd5": source["sourceMd5"], "节点": []})
            PIPELINE.atomic_json(artifact / "images.json", {"version": 2, "sourceMd5": source["sourceMd5"], "images": []})
            generated_md5 = PIPELINE.md5_file(compose)
            state["composeGeneration"] = {
                "composeMd5": generated_md5,
                "inputFingerprint": PIPELINE.generation_input_fingerprint(artifact, project_root, compose),
            }
            initial = PIPELINE.compile_input_snapshot(artifact, project_root, compose, state["preflightTask"])
            state["lastCompiledComposeMd5"] = generated_md5
            state["compileInputFingerprint"] = initial["fingerprint"]
            PIPELINE._write_state(artifact, state)
            compose.write_text("package com.example\n@Composable fun Page() { /* manual */ }\n", encoding="utf-8")

            def record_compile(*_args):
                current_artifact, _, current_state = PIPELINE.load_source(archive, project_root)
                snapshot = PIPELINE.compile_input_snapshot(
                    current_artifact, project_root, compose, current_state["preflightTask"]
                )
                current_state["phase"] = "compiled"
                current_state["lastCompiledComposeMd5"] = snapshot["composeMd5"]
                current_state["compileInputFingerprint"] = snapshot["fingerprint"]
                PIPELINE._write_state(current_artifact, current_state)

            with patch.object(PIPELINE, "ensure_design_evidence", return_value={"status": "cached"}), patch.object(
                PIPELINE, "compile_project", side_effect=record_compile
            ) as compile_project:
                first = PIPELINE.run_fixed_pipeline(archive, project_root, compose)
                second = PIPELINE.run_fixed_pipeline(archive, project_root, compose)

            self.assertEqual(first["status"], "recompiled_after_compile_input_change")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(compile_project.call_count, 1)

    def test_deleted_registered_drawable_invalidates_hot_cache_and_reimports_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            compose = project_root / "app" / "src" / "main" / "java" / "Page.kt"
            drawable = project_root / "app" / "src" / "main" / "res" / "drawable" / "card.png"
            compose.parent.mkdir(parents=True)
            drawable.parent.mkdir(parents=True)
            compose.write_text("package com.example\n@Composable fun Page() {}\n", encoding="utf-8")
            drawable.write_bytes(b"png")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("style.css", "main { width: 100px; }")

            PIPELINE.inspect_archive(archive, project_root, compose)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            state["composeFile"] = str(compose.resolve())
            state["preflightTask"] = ":app:compileDebugKotlin"
            PIPELINE.atomic_json(artifact / "设计解析.json", {"版本": 4, "sourceMd5": source["sourceMd5"], "节点": []})
            PIPELINE.atomic_json(
                artifact / "images.json",
                {"version": 2, "sourceMd5": source["sourceMd5"], "images": [{"outputPath": str(drawable)}]},
            )
            state["composeGeneration"] = {
                "composeMd5": PIPELINE.md5_file(compose),
                "inputFingerprint": PIPELINE.generation_input_fingerprint(artifact, project_root, compose),
            }
            initial = PIPELINE.compile_input_snapshot(artifact, project_root, compose, state["preflightTask"])
            state["lastCompiledComposeMd5"] = initial["composeMd5"]
            state["compileInputFingerprint"] = initial["fingerprint"]
            PIPELINE._write_state(artifact, state)
            drawable.unlink()

            def restore_assets(*_args, **_kwargs):
                drawable.write_bytes(b"png")
                current_artifact, _, current_state = PIPELINE.load_source(archive, project_root)
                PIPELINE.transition(current_state, "assets_imported")
                PIPELINE._write_state(current_artifact, current_state)

            with patch.object(PIPELINE, "ensure_design_evidence", return_value={"status": "cached"}), patch.object(
                PIPELINE, "import_assets", side_effect=restore_assets
            ) as import_assets, patch.object(PIPELINE, "compile_project") as compile_project:
                result = PIPELINE.run_fixed_pipeline(archive, project_root, compose)

            self.assertEqual(result["status"], "recompiled_after_resource_restore")
            import_assets.assert_called_once()
            compile_project.assert_called_once()
            self.assertTrue(drawable.is_file())

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
            self.assertEqual(len(result["sourceMd5"]), 32)
            manifest_path = Path(result["artifactPath"]) / "source.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["sourceMd5"], result["sourceMd5"])
            self.assertEqual(manifest["html"]["path"], "index.html")
            dom_path = Path(result["artifactPath"]) / "dom.json"
            dom = json.loads(dom_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["dom"]["path"], "dom.json")
            self.assertEqual(dom["htmlPath"], "index.html")
            self.assertGreater(manifest["dom"]["nodeCount"], 0)

    def test_inspect_rejects_extreme_compression_before_design_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "bomb.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("style.css", "a" * 1_000_000)

            with self.assertRaisesRegex(PIPELINE.PipelineError, "压缩比"):
                PIPELINE.inspect_archive(archive, root / "project")

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

            second = PIPELINE.inspect_archive(archive, project_root)

            self.assertTrue(second["cacheHit"])
            self.assertEqual(second["phase"], "validated")
            self.assertEqual(second["artifactPath"], first["artifactPath"])

    def test_inspect_rejects_full_md5_collision_in_same_short_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".page { width: 10px; }")
            current_sha = "abcdef" + "1" * 26
            foreign_sha = "abcdef" + "2" * 26
            artifact = PIPELINE.artifact_dir(archive, project_root, current_sha)
            PIPELINE.atomic_json(artifact / "source.json", {"sourceMd5": foreign_sha})

            with patch.object(PIPELINE, "md5_file", return_value=current_sha):
                with self.assertRaisesRegex(PIPELINE.PipelineError, "MD5 前缀碰撞"):
                    PIPELINE.inspect_archive(archive, project_root)

    def test_same_zip_with_new_compose_target_resets_target_bound_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            first_compose = project_root / "app" / "src" / "main" / "java" / "First.kt"
            second_compose = project_root / "feature" / "src" / "main" / "java" / "Second.kt"
            first_compose.parent.mkdir(parents=True)
            second_compose.parent.mkdir(parents=True)
            first_compose.write_text("package com.example\n", encoding="utf-8")
            second_compose.write_text("package com.example.feature\n", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")

            PIPELINE.inspect_archive(archive, project_root, first_compose)
            artifact, _, state = PIPELINE.load_source(archive, project_root)
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled"):
                PIPELINE.transition(state, phase)
            state["preflightTask"] = ":app:compileDebugKotlin"
            state["composeGeneration"] = {"composeMd5": "old-target"}
            PIPELINE._write_state(artifact, state)

            result = PIPELINE.inspect_archive(archive, project_root, second_compose)

            self.assertTrue(result["cacheHit"])
            self.assertEqual(result["phase"], "inspected")
            _, _, rebound = PIPELINE.load_source(archive, project_root)
            self.assertEqual(rebound["composeFile"], str(second_compose.resolve()))
            self.assertNotIn("preflightTask", rebound)
            self.assertNotIn("composeGeneration", rebound)
            self.assertEqual(rebound["history"][-1]["detail"]["targetChangedFrom"], str(first_compose.resolve()))

    def test_inspect_does_not_run_class_hierarchy_candidate_scan(self) -> None:
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
            self.assertFalse(candidates_path.exists())
            self.assertNotIn("repeatedBlockCandidates", result)

    def test_inspect_rejects_multiple_entry_html_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "ambiguous.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("a.html", "<html></html>")
                zipped.writestr("b.html", "<html></html>")

            with self.assertRaises(PIPELINE.UserInputRequired) as error:
                PIPELINE.inspect_archive(archive, Path(temp_dir) / "project")

            self.assertIn("多个 HTML", str(error.exception))

    def test_multiple_html_pause_can_resume_after_validated_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "multi.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("demo.html", '<link href="demo.css" rel="stylesheet">')
                zipped.writestr("page/index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("demo.css", "body { width: 10px; }")
                zipped.writestr("page/style.css", "main { width: 100px; }")

            with self.assertRaises(PIPELINE.UserInputRequired) as error:
                PIPELINE.inspect_archive(archive, project_root)
            selected = PIPELINE.select_entry_html(archive, project_root, "page/index.html")
            result = PIPELINE.inspect_archive(archive, project_root)

            self.assertEqual(selected["html"], "page/index.html")
            self.assertEqual(result["html"]["path"], "page/index.html")
            self.assertIn("demo.html", str(error.exception))
            self.assertIn("page/index.html", str(error.exception))

    def test_zip_path_normalization_preserves_leading_dot_filename(self) -> None:
        self.assertEqual(PIPELINE.safe_zip_name("./.hidden/style.css"), ".hidden/style.css")
        self.assertEqual(PIPELINE.safe_zip_name("...asset.png"), "...asset.png")

    def test_viewport_arguments_are_forwarded_to_run_fixed(self) -> None:
        with patch.object(PIPELINE, "run_fixed_pipeline", return_value={"status": "ok"}) as run_fixed:
            exit_code = PIPELINE.main([
                "run-fixed",
                "--zip", "/tmp/design.zip",
                "--project-root", "/tmp/project",
                "--compose", "/tmp/project/app/src/main/java/Page.kt",
                "--viewport-width", "390",
                "--viewport-height", "844",
                "--dpr", "3",
            ])

        self.assertEqual(exit_code, 0)
        run_fixed.assert_called_once_with(
            Path("/tmp/design.zip"),
            Path("/tmp/project"),
            Path("/tmp/project/app/src/main/java/Page.kt"),
            390,
            844,
            3.0,
        )

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
                    "<body><script>window.designHeadLoaded = true;</script>"
                    "<main class=\"page\"><span class=\"title\">设计标题</span>"
                    "<div class=\"hidden-parent\"><span id=\"hidden-child\">不可见</span></div>"
                    "<div id=\"absolute-cover\"></div>底层文字"
                    "</main><script>window.designTailLoaded = true;</script></body></html>",
                )
                zipped.writestr(
                    "lanhu/style.css",
                    ".page { width: 320px; height: 180px; padding: 12px; background: #ffffff; }"
                    ".title { color: rgb(1, 2, 3); font-size: 20px; }"
                    ".hidden-parent { opacity: 0; }"
                    "#absolute-cover { position: absolute; inset: 0; background: white; }",
                )

            from playwright import sync_api as playwright_api

            real_sync_playwright = playwright_api.sync_playwright
            browser_launches: list[int] = []

            class CountingPlaywrightContext:
                def __init__(self) -> None:
                    self.delegate = real_sync_playwright()

                def __enter__(self):
                    runtime = self.delegate.__enter__()
                    chromium = runtime.chromium

                    class CountingChromium:
                        def launch(self, *args, **kwargs):
                            browser_launches.append(1)
                            return chromium.launch(*args, **kwargs)

                    return SimpleNamespace(chromium=CountingChromium())

                def __exit__(self, *args):
                    return self.delegate.__exit__(*args)

            inspected = PIPELINE.inspect_archive(archive, project_root)
            PIPELINE.start_design_server(archive, project_root)
            try:
                with patch.object(playwright_api, "sync_playwright", side_effect=CountingPlaywrightContext):
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
            self.assertEqual(design["sourceMd5"], inspected["sourceMd5"])
            self.assertTrue(design["设计根节点"]["选择器"].startswith('[data-code-lanhu-node-id="'))
            self.assertIn("domPath", design)
            self.assertEqual(design["设计画布"]["宽度像素"], 344)
            self.assertEqual(design["设计画布"]["高度像素"], 204)
            self.assertEqual(browser_launches, [1], "布局采集与设计截图必须复用同一个浏览器页面")
            hidden_child = next(node for node in design["节点"] if node["id"] == "hidden-child")
            self.assertFalse(hidden_child["visible"], "祖先透明时子节点不能被误标为可见")
            paint_orders = [item["paintOrder"] for item in [*design["节点"], *design["文本片段"]]]
            self.assertTrue(all(isinstance(value, int) for value in paint_orders))
            cover = next(node for node in design["节点"] if node["id"] == "absolute-cover")
            bottom_text = next(run for run in design["文本片段"] if "设计标题" in run["text"])
            self.assertGreater(cover["paintOrder"], bottom_text["paintOrder"], "必须采用 Chrome 实际绘制顺序")

    def test_design_capture_network_policy_allows_only_loopback_and_embedded_urls(self) -> None:
        server = "http://127.0.0.1:8080/index.html"
        self.assertTrue(PIPELINE.is_allowed_design_request("http://127.0.0.1:8080/image.png", server))
        self.assertTrue(PIPELINE.is_allowed_design_request("data:image/png;base64,AA==", server))
        self.assertFalse(PIPELINE.is_allowed_design_request("http://127.0.0.1:9090/private", server))
        self.assertFalse(PIPELINE.is_allowed_design_request("https://example.com/tracker.js", server))

    def test_instrumented_design_html_declares_utf8(self) -> None:
        source = "<html><head><title>设计</title></head><body></body></html>"
        result = PIPELINE.ensure_utf8_html(source)

        self.assertIn('<head><meta charset="utf-8">', result)

    def test_instruments_html_with_stable_dom_node_ids(self) -> None:
        html = "<html><body><table><tr><td>单元格</td></tr></table></body></html>"
        dom = {
            "nodes": [
                {"nodeId": "n0", "tag": "document"},
                {"nodeId": "n1", "tag": "html"},
                {"nodeId": "n2", "tag": "body"},
                {"nodeId": "n3", "tag": "table"},
                {"nodeId": "n4", "tag": "tr"},
                {"nodeId": "n5", "tag": "td"},
            ]
        }

        instrumented = PIPELINE.instrument_html_node_ids(html, dom)

        self.assertIn('<table data-code-lanhu-node-id="n3">', instrumented)
        self.assertIn('<tr data-code-lanhu-node-id="n4">', instrumented)
        self.assertIn('<td data-code-lanhu-node-id="n5">', instrumented)

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
                {"sourceMd5": inspected["sourceMd5"]},
            )
            image = Path(inspected["artifactPath"]) / "runs" / "设计截图.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ))

            result = PIPELINE.complete_design_screenshot(archive, project_root, image)

            self.assertEqual(result["status"], "recorded")
            self.assertFalse(Path(started["statePath"]).exists())
            self.assertFalse(PIPELINE.is_pid_alive(started["pid"]))

    def test_ensure_design_evidence_does_not_reuse_stale_document_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet"><main>Page</main>')
                zipped.writestr("style.css", "main { width: 100px; height: 50px; }")

            inspected = PIPELINE.inspect_archive(archive, project_root)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            screenshot = artifact / "runs" / "设计截图.png"
            screenshot.parent.mkdir(parents=True)
            screenshot.write_bytes(b"stale-image")
            PIPELINE.atomic_json(
                artifact / "设计解析.json",
                {
                    "版本": PIPELINE.DESIGN_DOCUMENT_VERSION - 1,
                    "sourceMd5": source["sourceMd5"],
                    "设计根节点": {"选择器": "body > :first-child"},
                },
            )
            state["designScreenshot"] = {"image": str(screenshot)}
            PIPELINE._write_state(artifact, state)

            with patch.object(PIPELINE, "start_design_server", side_effect=PIPELINE.PipelineError("需要重新采集")) as start:
                with self.assertRaisesRegex(PIPELINE.PipelineError, "重新采集"):
                    PIPELINE.ensure_design_evidence(archive, project_root)

            start.assert_called_once_with(archive, project_root)
            self.assertEqual(Path(inspected["artifactPath"]), artifact)

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
            image_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )

            def fake_adb(command, **kwargs):
                if "getprop" in command:
                    return SimpleNamespace(returncode=0, stdout="K80\n", stderr="")
                kwargs["stdout"].write(image_bytes)
                return SimpleNamespace(returncode=0, stdout=None, stderr=b"")

            with patch.object(PIPELINE.subprocess, "run", side_effect=fake_adb):
                first = PIPELINE.screenshot_k80(archive, project_root, "emulator-5554")
                second = PIPELINE.screenshot_k80(archive, project_root, "emulator-5554")

            runs_root = Path(inspected["artifactPath"]) / "runs"
            self.assertEqual(Path(first["image"]), runs_root / "应用截图.png")
            self.assertEqual(Path(second["image"]), runs_root / "应用截图_1.png")
            self.assertEqual(
                sorted(path.name for path in runs_root.iterdir()),
                ["应用截图.png", "应用截图_1.png"],
            )

    def test_k80_screenshot_rejects_invalid_png_without_advancing_state(self) -> None:
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

            def fake_adb(command, **kwargs):
                if "getprop" in command:
                    return SimpleNamespace(returncode=0, stdout="K80\n", stderr="")
                kwargs["stdout"].write(b"not-a-png")
                return SimpleNamespace(returncode=0, stdout=None, stderr=b"")

            with patch.object(PIPELINE.subprocess, "run", side_effect=fake_adb):
                with self.assertRaisesRegex(PIPELINE.PipelineError, "PNG"):
                    PIPELINE.screenshot_k80(archive, project_root, "emulator-5554")

            self.assertFalse((Path(inspected["artifactPath"]) / "runs" / "应用截图.png").exists())
            _, _, saved = PIPELINE.load_source(archive, project_root)
            self.assertEqual(saved["phase"], "installed")
            self.assertNotIn("lastScreenshot", saved)

    def test_transition_requires_previous_phase(self) -> None:
        state = PIPELINE.new_state("abc", "Page.kt")
        with self.assertRaises(PIPELINE.PipelineError):
            PIPELINE.transition(state, "compiled")

        PIPELINE.transition(state, "inspected")
        PIPELINE.transition(state, "validated")
        self.assertEqual(state["phase"], "validated")

    def test_attempt_limit_is_persisted_before_external_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir)
            state = PIPELINE.new_state("a" * 32, "Page.kt")
            for expected in (1, 2, 3):
                self.assertEqual(PIPELINE.reserve_attempt(artifact, state, "compile"), expected)
                persisted = json.loads((artifact / "pipeline.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["attempts"]["compile"], expected)
            with self.assertRaisesRegex(PIPELINE.PipelineError, "最多 3 次"):
                PIPELINE.reserve_attempt(artifact, state, "compile")

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
            artifact, source, state = PIPELINE.load_source(archive, root / "project")
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            runs = artifact / "runs"
            runs.mkdir(parents=True)
            design = runs / "设计截图.png"
            app = runs / "应用截图.png"
            design.write_bytes(b"png")
            app.write_bytes(b"png")
            design_md5 = PIPELINE.md5_file(design)
            app_md5 = PIPELINE.md5_file(app)
            report = artifact / "diff.json"
            PIPELINE.atomic_json(report, {
                "sourceMd5": source["sourceMd5"],
                "designScreenshot": str(design),
                "appScreenshot": str(app),
                "designScreenshotMd5": design_md5,
                "appScreenshotMd5": app_md5,
                "metrics": {"changedRatio": 1},
            })
            state["comparison"] = {
                "report": str(report),
                "reportMd5": PIPELINE.md5_file(report),
                "designScreenshot": str(design),
                "appScreenshot": str(app),
                "designScreenshotMd5": design_md5,
                "appScreenshotMd5": app_md5,
                "metrics": {"changedRatio": 1},
            }
            PIPELINE._write_state(artifact, state)
            for _ in range(3):
                PIPELINE.mark_diff(archive, root / "project", report, "repair")
                _, _, state = PIPELINE.load_source(archive, root / "project")
                PIPELINE.transition(state, "compiled")
                PIPELINE.transition(state, "installed")
                PIPELINE.transition(state, "screenshot")
                PIPELINE._write_state(artifact, state)
            with self.assertRaises(PIPELINE.PipelineError):
                PIPELINE.mark_diff(archive, root / "project", report, "repair")

    def test_restart_generation_cycle_reopens_stopped_pipeline_without_reparsing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")

            PIPELINE.inspect_archive(archive, project_root)
            artifact, source, state = PIPELINE.load_source(archive, project_root)
            PIPELINE.atomic_json(artifact / "设计解析.json", {"sourceMd5": source["sourceMd5"]})
            PIPELINE.atomic_json(artifact / "images.json", {"sourceMd5": source["sourceMd5"], "images": []})
            for phase in ("validated", "preflight", "assets_imported", "generated", "compiled", "installed", "screenshot"):
                PIPELINE.transition(state, phase)
            state["attempts"].update({"compile": 3, "repair": 2, "package": 3})
            PIPELINE.transition(state, "diffed", {"outcome": "stop"})
            state["lastDiffOutcome"] = "stop"
            original_history_size = len(state["history"])
            PIPELINE._write_state(artifact, state)

            result = PIPELINE.restart_generation_cycle(archive, project_root, "用户要求改为独立实现")

            self.assertEqual(result["phase"], "generated")
            _, _, reopened = PIPELINE.load_source(archive, project_root)
            self.assertEqual(reopened["phase"], "generated")
            self.assertEqual(reopened["attempts"]["repair"], 0)
            self.assertEqual(reopened["attempts"]["compile"], 3)
            self.assertEqual(reopened["attempts"]["package"], 3)
            self.assertNotIn("lastDiffOutcome", reopened)
            self.assertEqual(reopened["generationCycle"], 2)
            self.assertEqual(len(reopened["history"]), original_history_size + 1)
            self.assertEqual(reopened["history"][-1]["phase"], "generation_restarted")

    def test_restart_generation_cycle_rejects_non_stopped_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "design.zip"
            project_root = root / "project"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<link href="style.css" rel="stylesheet">')
                zipped.writestr("style.css", ".box { width: 10px; }")
            PIPELINE.inspect_archive(archive, project_root)

            with self.assertRaises(PIPELINE.PipelineError):
                PIPELINE.restart_generation_cycle(archive, project_root, "不应允许")


if __name__ == "__main__":
    unittest.main()
