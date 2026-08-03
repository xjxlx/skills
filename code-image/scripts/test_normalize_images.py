#!/usr/bin/env python3
"""code-image 的最小行为测试。"""

import tempfile
import unittest
from pathlib import Path

from normalize_images import (
    apply_plan,
    build_plan,
    load_manifest,
    resolve_mipmap_dirs,
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
        self.assertTrue(all(item.output_name.startswith("reporthomev2") for item in normal))

    def test_same_asset_across_density_directories_keeps_one_resource_name(self):
        xhdpi = self.write_resource("mipmap-xhdpi", "Group 62.png", b"xhdpi")
        xxhdpi = self.write_resource("mipmap-xxhdpi", "Group 62.png", b"xxhdpi")

        plan = build_plan(self.compose, self.report_root / "mipmap")

        self.assertEqual({item.output_name for item in plan}, {"reporthomev2layoutgroup62.png"})

    def test_existing_resource_name_is_never_overwritten(self):
        existing = self.write_resource("mipmap-xxhdpi", "reporthomev2bg.png", b"existing")
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
        self.assertEqual(second_plan[0].previous_output_name, "reporthomev2layoutold.png")
        self.assertEqual(second_plan[0].output_name, "reporthomev2layoutnewsource.png")

        apply_plan(second_plan, self.manifest, self.mapping, self.project)
        manifest = load_manifest(self.manifest)
        self.assertEqual(manifest["resources"][0]["originalName"], "new-source.png")
        self.assertEqual(manifest["resources"][0]["outputName"], "reporthomev2layoutnewsource.png")

    def test_base_mipmap_path_includes_density_siblings(self):
        self.write_resource("mipmap-xhdpi", "one.png")
        self.write_resource("mipmap-xxhdpi", "one.png")

        directories = resolve_mipmap_dirs(self.report_root / "mipmap")

        self.assertEqual(
            {directory.name for directory in directories},
            {"mipmap-xhdpi", "mipmap-xxhdpi"},
        )

    def test_apply_can_update_only_the_selected_compose_references(self):
        source = self.write_resource("mipmap-xhdpi", "old.png")
        self.compose.write_text("val icon = R.mipmap.old\n", encoding="utf-8")
        plan = build_plan(self.compose, source.parent, manifest_path=self.manifest)

        apply_plan(plan, self.manifest, self.mapping, self.project)
        update_compose_references(self.compose, plan)

        self.assertIn("R.mipmap.reporthomev2layoutold", self.compose.read_text())


if __name__ == "__main__":
    unittest.main()
