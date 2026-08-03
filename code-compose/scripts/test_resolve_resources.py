#!/usr/bin/env python3
"""code-compose 图片资源解析器的最小行为测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from resolve_resources import resolve_resource


class ResolveResourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.resource_dir = self.project / "app/src/main/res/layouts/report/mipmap-xhdpi"
        self.resource_dir.mkdir(parents=True)
        self.codex_dir = self.project / ".codex"
        self.codex_dir.mkdir()
        self.mapping = self.codex_dir / "lanhu-resources.json"
        self.manifest = self.codex_dir / "code-image-manifest.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_mapping(self, data):
        self.mapping.write_text(json.dumps(data), encoding="utf-8")

    def test_local_original_file_has_priority_over_mapping(self):
        original = self.resource_dir / "Group 62.png"
        original.write_bytes(b"original")
        self.write_mapping({"Group 62.png": "icon_wrong.png"})

        result = resolve_resource(self.project, "assets/Group 62.png")

        self.assertEqual(result["source"], "local")
        self.assertEqual(result["resource_stem"], "Group 62")

    def test_mapping_resolves_original_name_to_current_code_image_name(self):
        current = self.resource_dir / "icon_report_home_v2_group_62.png"
        current.write_bytes(b"image")
        self.write_mapping({"Group 62.png": current.name})

        result = resolve_resource(self.project, "Group 62.png")

        self.assertEqual(result["source"], "lanhu-resources")
        self.assertEqual(result["resource_stem"], "icon_report_home_v2_group_62")
        self.assertTrue(result["path"].endswith("icon_report_home_v2_group_62.png"))

    def test_manifest_is_used_when_simple_mapping_is_missing(self):
        current = self.resource_dir / "icon_report_home_v2_group_63.png"
        current.write_bytes(b"image")
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "resources": [
                        {
                            "originalName": "Group 63.png",
                            "outputName": current.name,
                            "currentPath": str(current.relative_to(self.project)),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = resolve_resource(self.project, "Group 63.png")

        self.assertEqual(result["source"], "manifest")
        self.assertEqual(result["resource_stem"], "icon_report_home_v2_group_63")

    def test_missing_resource_does_not_guess_a_cleaned_name(self):
        self.write_mapping({"Group 64.png": "icon_report_home_v2_group_64.png"})

        with self.assertRaises(FileNotFoundError):
            resolve_resource(self.project, "Group 64.png")


if __name__ == "__main__":
    unittest.main()
