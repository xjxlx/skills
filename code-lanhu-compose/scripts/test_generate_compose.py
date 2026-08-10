#!/usr/bin/env python3
"""DOM IR 到 Compose 代码生成契约测试。"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("generate_compose.py")
SPEC = importlib.util.spec_from_file_location("generate_compose", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT}")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class ComposeGeneratorTest(unittest.TestCase):
    def test_generates_layout_from_stored_dom_and_computed_style(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            output = root / "TestPage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "attributes": {"id": "page"}, "classTokens": [], "directText": "", "childrenIds": ["n2", "n3"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "h1", "attributes": {}, "classTokens": [], "directText": "标题", "childrenIds": []},
                    {"nodeId": "n3", "parentId": "n1", "tag": "p", "attributes": {}, "classTokens": [], "directText": "说明", "childrenIds": []},
                ],
                "resources": [],
            }, ensure_ascii=False), encoding="utf-8")
            design_path.write_text(json.dumps({
                "sourceMd5": "a" * 32,
                "domPath": str(dom_path),
                "nodes": [
                    {"nodeId": "n1", "tag": "main", "visible": True, "style": {"display": "flex", "flexDirection": "column", "color": "rgb(0, 0, 0)"}},
                    {"nodeId": "n2", "tag": "h1", "visible": True, "style": {"display": "block", "fontSize": "20px", "fontWeight": "700"}},
                    {"nodeId": "n3", "tag": "p", "visible": True, "style": {"display": "block", "fontSize": "14px"}},
                ],
            }, ensure_ascii=False), encoding="utf-8")

            result = GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated")
            source = output.read_text(encoding="utf-8")

            self.assertEqual(result["nodeCount"], 4)
            self.assertIn("Column(", source)
            self.assertIn('Text(text = "标题")', source)
            self.assertIn('Text(text = "说明")', source)
            self.assertNotIn("flex-col", source)
            self.assertNotIn("猜测", source)

    def test_does_not_generate_from_missing_stored_dom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            design_path = root / "设计解析.json"
            design_path.write_text(json.dumps({"nodes": []}), encoding="utf-8")

            with self.assertRaises(GENERATOR.GenerationError):
                GENERATOR.generate_compose(root / "missing-dom.json", design_path, root / "Page.kt", "com.example.generated")

    def test_resolves_image_from_stored_resource_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            images_path = root / "images.json"
            output = root / "Page.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "img", "attributes": {"src": "images/a.png", "alt": "logo"}, "classTokens": [], "directText": "", "childrenIds": []},
                ],
                "resources": [{"kind": "image", "source": "images/a.png", "resolvedPath": "images/a.png", "nodeId": "n2"}],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({"nodes": [
                {"nodeId": "n1", "visible": True, "style": {"display": "block"}},
                {"nodeId": "n2", "visible": True, "style": {"display": "block"}},
            ]}), encoding="utf-8")
            images_path.write_text(json.dumps({"images": [{
                "sourcePath": "images/a.png", "outputName": "icon_a", "outputPath": "app/src/main/res/mipmap-hdpi/icon_a.png"
            }]}), encoding="utf-8")

            GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated", images_path)
            source = output.read_text(encoding="utf-8")

            self.assertIn("painterResource(id = R.mipmap.icon_a)", source)
            self.assertIn("contentDescription = \"logo\"", source)
            self.assertNotIn("[image:n2]", source)


if __name__ == "__main__":
    unittest.main()
