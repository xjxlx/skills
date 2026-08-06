#!/usr/bin/env python3
"""code-image 的最小行为测试。"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from normalize_images import (
    apply_plan,
    build_plan,
    load_manifest,
    normalize_namespace,
    namespace_prefixes,
    resolve_mipmap_dirs,
    resolve_mipmap_path,
    update_compose_references,
)


class NormalizeImagesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.compose = (
            self.project
            / "app/src/main/java/com/example/report/ReportHomeV2Layout.kt"
        )
        self.compose.parent.mkdir(parents=True)
        self.compose.write_text("@Composable fun ReportHomeV2Layout() = Unit\n")
        self.report_root = self.project / "app/src/main/res/layouts/v2/report"
        self.mipmap_base = self.report_root / "mipmap"
        self.manifest = self.project / ".codex/code-image-manifest.json"
        self.mapping = self.project / ".codex/lanhu-resources.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_resource(self, qualifier: str, name: str, content: bytes = b"image"):
        directory = self.report_root / qualifier
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(content)
        return path

    def test_collision_names_are_distinct_and_stable_regardless_of_input_order(self):
        first = self.write_resource("mipmap-xhdpi", "形状.png", b"first")
        second = self.write_resource("mipmap-xhdpi", "形状(1).png", b"second")

        normal = build_plan(self.compose, self.report_root / "mipmap-xhdpi")
        reversed_plan = build_plan(self.compose, self.report_root / "mipmap-xhdpi")

        normal_names = {item.source: item.output_name for item in normal}
        reversed_names = {item.source: item.output_name for item in reversed_plan}
        self.assertEqual(normal_names, reversed_names)
        self.assertEqual(len({item.output_name for item in normal}), 2)
        self.assertTrue(all(item.output_name.startswith("icon_report_home_v2_") for item in normal))

    def test_same_asset_across_density_directories_keeps_one_resource_name(self):
        xhdpi = self.write_resource("mipmap-xhdpi", "Group 62.png", b"xhdpi")
        xxhdpi = self.write_resource("mipmap-xxhdpi", "Group 62.png", b"xxhdpi")

        plan = build_plan(self.compose, self.report_root / "mipmap")

        self.assertEqual({item.output_name for item in plan}, {"icon_report_home_v2_group_62.png"})

    def test_existing_resource_name_is_never_overwritten(self):
        existing_dir = self.project / "app/src/main/res/mipmap-xxhdpi"
        existing_dir.mkdir(parents=True, exist_ok=True)
        existing = existing_dir / "icon_report_home_v2_bg.png"
        existing.write_bytes(b"existing")
        source = self.write_resource("mipmap-xhdpi", "bg.png", b"new")

        plan = build_plan(self.compose, self.report_root / "mipmap")

        self.assertNotEqual(plan[0].target, existing)
        self.assertNotEqual(plan[0].output_name, existing.name)

    def test_hash_matches_a_renamed_source_and_updates_the_cache(self):
        source = self.write_resource("mipmap-xhdpi", "old.png", b"same asset")
        first_plan = build_plan(
            self.compose,
            self.report_root / "mipmap-xhdpi",
            manifest_path=self.manifest,
        )
        apply_plan(first_plan, self.manifest, self.mapping, self.project)

        renamed_source = source.with_name("new-source.png")
        first_plan[0].target.rename(renamed_source)
        second_plan = build_plan(
            self.compose,
            self.report_root / "mipmap-xhdpi",
            manifest_path=self.manifest,
        )

        self.assertEqual(len(second_plan), 1)
        self.assertEqual(second_plan[0].previous_output_name, "icon_report_home_v2_old.png")
        self.assertEqual(second_plan[0].output_name, "icon_report_home_v2_new_source.png")

        apply_plan(second_plan, self.manifest, self.mapping, self.project)
        manifest = load_manifest(self.manifest)
        self.assertEqual(manifest["resources"][0]["originalName"], "new-source.png")
        self.assertEqual(manifest["resources"][0]["outputName"], "icon_report_home_v2_new_source.png")

    def test_base_mipmap_path_includes_density_siblings(self):
        self.write_resource("mipmap-xhdpi", "one.png")
        self.write_resource("mipmap-xxhdpi", "one.png")

        directories = resolve_mipmap_dirs(self.report_root / "mipmap")

        self.assertEqual(
            {directory.name for directory in directories},
            {"mipmap-xhdpi", "mipmap-xxhdpi"},
        )

    def test_resolve_mipmap_path_finds_density_siblings_without_base_dir(self):
        self.write_resource("mipmap-xhdpi", "one.png")
        self.write_resource("mipmap-xxhdpi", "one.png")

        resolved = resolve_mipmap_path(self.project, "res.layouts.v2.report.mipmap")

        self.assertEqual(resolved, (self.report_root / "mipmap").resolve())
        self.assertEqual(
            {directory.name for directory in resolve_mipmap_dirs(resolved)},
            {"mipmap-xhdpi", "mipmap-xxhdpi"},
        )

    def test_namespace_prefixes_cover_version_suffix_variants(self):
        self.assertEqual(
            namespace_prefixes("report_home_v2"),
            ["icon_report_home_v2_", "icon_report_home_"],
        )
        self.assertEqual(namespace_prefixes("lesson_yflx"), ["icon_lesson_yflx_"])

    def test_namespace_removes_layout_or_page_suffix(self):
        self.assertEqual(normalize_namespace(Path("ReportHomeV2Layout.kt")), "report_home_v2")
        self.assertEqual(normalize_namespace(Path("Test3Page.kt")), "test3")

    def test_input_manifest_limits_plan_to_imported_images(self):
        imported = self.write_resource("mipmap-nodpi", ".lanhu-imported.png", b"new")
        retained = self.write_resource("mipmap-nodpi", "legacy.png", b"legacy")
        input_manifest = self.project / ".code-lanhu-compose/images/design-a1b2c3d4.json"
        input_manifest.parent.mkdir(parents=True)
        input_manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "images": [
                        {
                            "sourcePath": "design/img/Group 62.png",
                            "originalName": "Group 62.png",
                            "sha256": hashlib.sha256(b"new").hexdigest(),
                            "targetPath": str(imported.relative_to(self.project)),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        plan = build_plan(
            self.compose,
            self.report_root / "mipmap-nodpi",
            input_manifest_path=input_manifest,
        )

        planned_sources = {item.source.resolve() for item in plan}
        self.assertEqual(planned_sources, {imported.resolve()})
        self.assertNotIn(retained.resolve(), planned_sources)
        self.assertEqual(plan[0].original_name, "Group 62.png")
        self.assertEqual(plan[0].output_name, "icon_report_home_v2_group_62.png")

    def test_input_manifest_rejects_image_outside_requested_mipmap(self):
        imported = self.write_resource("mipmap-nodpi", ".lanhu-imported.png", b"new")
        outside = self.project / "app/src/main/res/drawable-nodpi/not-an-import.png"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"outside")
        input_manifest = self.project / ".code-lanhu-compose/images/design-a1b2c3d4.json"
        input_manifest.parent.mkdir(parents=True)
        input_manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "images": [
                        {
                            "sourcePath": "design/img/Group 62.png",
                            "originalName": "Group 62.png",
                            "sha256": hashlib.sha256(b"outside").hexdigest(),
                            "targetPath": str(outside.relative_to(self.project)),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "不在指定 mipmap"):
            build_plan(
                self.compose,
                imported.parent,
                input_manifest_path=input_manifest,
            )

    def test_already_normalized_names_are_kept_not_double_prefixed(self):
        self.write_resource("mipmap-xhdpi", "icon_report_home_v2_bg.png", b"bg")
        self.write_resource("mipmap-xxhdpi", "icon_report_home_v2_bg.png", b"bg")

        plan = build_plan(self.compose, self.report_root / "mipmap")

        self.assertEqual(len(plan), 2)
        for item in plan:
            self.assertEqual(item.source.name, item.output_name)
            self.assertEqual(item.original_name, "icon_report_home_v2_bg.png")

    def test_apply_keeps_already_normalized_names_and_syncs_manifest(self):
        source = self.write_resource(
            "mipmap-xhdpi", "icon_report_home_v2_bg.png", b"new content"
        )
        plan = build_plan(self.compose, self.report_root / "mipmap-xhdpi")

        apply_plan(plan, self.manifest, self.mapping, self.project)
        manifest = load_manifest(self.manifest)

        self.assertTrue(source.exists())
        self.assertEqual(manifest["resources"][0]["outputName"], "icon_report_home_v2_bg.png")
        self.assertEqual(manifest["resources"][0]["hash"], hashlib.sha256(b"new content").hexdigest())

    def test_normalized_name_ignores_stale_hash_match_with_different_output_name(self):
        self.write_resource("mipmap-xhdpi", "icon_report_home_v2_bg.png", b"bg")
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "resources": [
                        {
                            "identity": "app/src/main/res/layouts/v2/report:icon_v2_bg.png",
                            "originalName": "icon_v2_bg.png",
                            "outputName": "icon_report_home_v2_icon_v2_bg.png",
                            "currentPath": "app/src/main/res/layouts/v2/report/mipmap-xhdpi/icon_report_home_v2_icon_v2_bg.png",
                            "outputPath": "app/src/main/res/layouts/v2/report/mipmap-xhdpi/icon_report_home_v2_icon_v2_bg.png",
                            "resourceFamily": "app/src/main/res/layouts/v2/report",
                            "composeFile": "app/src/main/java/com/example/report/ReportHomeV2Layout.kt",
                            "hash": hashlib.sha256(b"bg").hexdigest(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        plan = build_plan(
            self.compose,
            self.report_root / "mipmap-xhdpi",
            manifest_path=self.manifest,
        )

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].output_name, "icon_report_home_v2_bg.png")
        self.assertEqual(
            plan[0].identity,
            "app/src/main/res/layouts/v2/report:icon_report_home_v2_bg.png",
        )

    def test_sibling_density_matches_cache_by_output_name_and_family(self):
        self.write_resource("mipmap-xhdpi", "icon_report_home_v2_image_6.png", b"xhdpi")
        self.write_resource("mipmap-xxhdpi", "icon_report_home_v2_image_6.png", b"xxhdpi")
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "resources": [
                        {
                            "identity": "app/src/main/res/layouts/v2/report:编组 6.png",
                            "originalName": "编组 6.png",
                            "outputName": "icon_report_home_v2_image_6.png",
                            "currentPath": "app/src/main/res/layouts/v2/report/mipmap-xxxhdpi/icon_report_home_v2_image_6.png",
                            "outputPath": "app/src/main/res/layouts/v2/report/mipmap-xxxhdpi/icon_report_home_v2_image_6.png",
                            "resourceFamily": "app/src/main/res/layouts/v2/report",
                            "composeFile": "app/src/main/java/com/example/report/ReportHomeV2Layout.kt",
                            "hash": "0" * 64,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        plan = build_plan(
            self.compose,
            self.report_root / "mipmap",
            manifest_path=self.manifest,
        )

        self.assertEqual(len(plan), 2)
        self.assertEqual({item.output_name for item in plan}, {"icon_report_home_v2_image_6.png"})
        self.assertEqual(
            {item.identity for item in plan},
            {"app/src/main/res/layouts/v2/report:编组 6.png"},
        )

    def test_apply_can_update_only_the_selected_compose_references(self):
        source = self.write_resource("mipmap-xhdpi", "old.png")
        self.compose.write_text("val icon = R.mipmap.old\n", encoding="utf-8")
        plan = build_plan(self.compose, source.parent, manifest_path=self.manifest)

        apply_plan(plan, self.manifest, self.mapping, self.project)
        update_compose_references(self.compose, plan)

        self.assertIn("R.mipmap.icon_report_home_v2_old", self.compose.read_text())


if __name__ == "__main__":
    unittest.main()
