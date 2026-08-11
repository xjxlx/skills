#!/usr/bin/env python3
"""DOM IR 到 Compose 代码生成契约测试。"""

import importlib.util
import json
import struct
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
    def test_maps_scale_down_and_object_position_without_enlarging_or_recentering(self) -> None:
        self.assertEqual(GENERATOR._content_scale("scale-down"), "ContentScale.Inside")
        self.assertEqual(GENERATOR._image_alignment("left top"), "Alignment.TopStart")
        self.assertEqual(GENERATOR._image_alignment("100% 50%"), "Alignment.CenterEnd")

    def test_flattened_chrome_paint_order_does_not_reapply_css_z_index(self) -> None:
        self.assertNotIn("zIndex", GENERATOR._modifier(None, {"zIndex": "999"}))

    def test_rejects_css_effects_that_bounds_cannot_reconstruct(self) -> None:
        with self.assertRaisesRegex(GENERATOR.GenerationError, "background-repeat"):
            GENERATOR._background_record(
                {"backgroundImage": "url(images/tile.png)", "backgroundRepeat": "repeat", "backgroundSize": "auto"},
                [],
            )
        with self.assertRaisesRegex(GENERATOR.GenerationError, "border-radius"):
            GENERATOR._shape({"borderRadius": "20px 0px"})
        with self.assertRaisesRegex(GENERATOR.GenerationError, "text-transform"):
            GENERATOR._render_text("hello", None, {"textTransform": "uppercase"}, "")
        with self.assertRaisesRegex(GENERATOR.GenerationError, "sRGB"):
            GENERATOR._text_color("oklch(60% 0.2 30)")
        with self.assertRaisesRegex(GENERATOR.GenerationError, "non solid|非 solid"):
            GENERATOR._border({"border": "4px dashed rgb(255, 0, 0)"})
        decorated = "\n".join(GENERATOR._render_text(
            "link", None, {"textDecorationLine": "underline line-through"}, ""
        ))
        self.assertIn("TextDecoration.combine", decorated)

    def test_allows_repeat_auto_when_bitmap_matches_background_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "tile.png"
            image.write_bytes(
                b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 100, 110) + b"\x00" * 8
            )

            record = {"sourcePath": "images/tile.png", "extractedPath": str(image)}
            result = GENERATOR._background_record(
                {
                    "backgroundImage": "url(images/tile.png)",
                    "backgroundRepeat": "repeat",
                    "backgroundSize": "auto",
                },
                [record],
                {"x": 0, "y": 0, "width": 100, "height": 110},
            )

            self.assertIs(result, record)

    def test_maps_numeric_background_size_and_position(self) -> None:
        self.assertEqual(
            GENERATOR._numeric_background({
                "backgroundSize": "246px 156px",
                "backgroundPosition": "-10px -8px",
            }),
            (246.0, 156.0, -10.0, -8.0),
        )

    def test_kotlin_identifiers_escape_keywords_and_non_ascii_stems(self) -> None:
        self.assertEqual(GENERATOR._safe_identifier("when"), "Page_when")
        self.assertEqual(GENERATOR._safe_identifier("页面"), "Page")
        self.assertEqual(GENERATOR._android_resource_name({"outputName": "when.png"}), "`when`")
        self.assertEqual(GENERATOR._kotlin_qualified_name("com.example.when"), "com.example.`when`")

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
            self.assertIn('text = "标题"', source)
            self.assertIn('text = "说明"', source)
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
                "sourcePath": "images/a.png", "outputName": "icon_a.png", "outputPath": "app/src/main/res/mipmap-hdpi/icon_a.png"
            }]}), encoding="utf-8")

            GENERATOR.generate_compose(
                dom_path,
                design_path,
                output,
                "com.example.generated",
                images_path,
                "com.example",
            )
            source = output.read_text(encoding="utf-8")

            self.assertIn("painterResource(id = R.mipmap.icon_a)", source)
            self.assertIn("contentDescription = \"logo\"", source)
            self.assertNotIn("[image:n2]", source)

    def test_applies_browser_bounds_and_computed_typography(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            output = root / "PrecisePage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "span", "attributes": {}, "classTokens": [], "directText": "精确标题", "childrenIds": []},
                ],
                "resources": [],
            }, ensure_ascii=False), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计画布": {"宽度像素": 320, "高度像素": 180},
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 320, "height": 180}},
                "节点": [
                    {
                        "nodeId": "n1",
                        "visible": True,
                        "bounds": {"x": 0, "y": 0, "width": 320, "height": 180},
                        "style": {"display": "block", "backgroundColor": "rgb(245, 246, 247)", "borderRadius": "16px"},
                    },
                    {
                        "nodeId": "n2",
                        "visible": True,
                        "bounds": {"x": 12, "y": 24, "width": 140, "height": 32},
                        "style": {
                            "display": "block",
                            "color": "rgb(1, 2, 3)",
                            "fontSize": "20px",
                            "fontWeight": "700",
                            "lineHeight": "24px",
                            "letterSpacing": "1px",
                            "textAlign": "center",
                        },
                    },
                ],
            }, ensure_ascii=False), encoding="utf-8")

            result = GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated")
            source = output.read_text(encoding="utf-8")

            self.assertIn("BoxWithConstraints", source)
            self.assertIn("private const val DESIGN_WIDTH = 320f", source)
            self.assertIn("designDp(12f, scaleX)", source)
            self.assertIn("designDp(24f, scaleY)", source)
            self.assertIn("fontSize = designSp(20f, fontScale)", source)
            self.assertIn("lineHeight = designSp(24f, fontScale)", source)
            self.assertIn("color = Color(0xFF010203)", source)
            self.assertIn("fontWeight = FontWeight(700)", source)
            self.assertIn("textAlign = TextAlign.Center", source)
            self.assertGreaterEqual(result["styledNodeCount"], 2)

    def test_maps_css_background_image_from_final_browser_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            images_path = root / "images.json"
            output = root / "BackgroundPage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "div", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": []},
                ],
                "resources": [],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计画布": {"宽度像素": 320, "高度像素": 180},
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 320, "height": 180}},
                "节点": [
                    {"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 320, "height": 180}, "style": {"display": "block"}},
                    {
                        "nodeId": "n2",
                        "visible": True,
                        "bounds": {"x": 20, "y": 30, "width": 100, "height": 60},
                        "style": {
                            "display": "block",
                            "backgroundImage": "url(\"http://127.0.0.1:54321/images/card-cover.png\")",
                            "backgroundSize": "cover",
                        },
                    },
                ],
            }), encoding="utf-8")
            images_path.write_text(json.dumps({"images": [{
                "sourcePath": "images/card-cover.png",
                "outputName": "card_cover.png",
                "outputPath": "app/src/main/res/mipmap-xxhdpi/card_cover.png",
            }]}), encoding="utf-8")

            result = GENERATOR.generate_compose(
                dom_path,
                design_path,
                output,
                "com.example.generated",
                images_path,
                "com.example",
            )
            source = output.read_text(encoding="utf-8")

            self.assertIn("R.mipmap.card_cover", source)
            self.assertIn("contentScale = ContentScale.Crop", source)
            self.assertEqual(result["backgroundImageCount"], 1)

    def test_does_not_replace_identical_generated_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            output = root / "StablePage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "attributes": {}, "classTokens": [], "directText": "稳定", "childrenIds": []},
                ],
                "resources": [],
            }, ensure_ascii=False), encoding="utf-8")
            design_path.write_text(json.dumps({"节点": [{
                "nodeId": "n1",
                "visible": True,
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 40},
                "style": {"display": "block", "fontSize": "16px"},
            }]}), encoding="utf-8")

            first = GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated")
            first_stat = output.stat()
            second = GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated")

            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(output.stat().st_mtime_ns, first_stat.st_mtime_ns)

    def test_uses_design_root_id_when_body_has_multiple_visual_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            output = root / "MultipleRootsPage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "html", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "body", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n3", "n4"]},
                    {"nodeId": "n3", "parentId": "n2", "tag": "main", "attributes": {}, "classTokens": [], "directText": "主区域", "childrenIds": []},
                    {"nodeId": "n4", "parentId": "n2", "tag": "aside", "attributes": {}, "classTokens": [], "directText": "侧区域", "childrenIds": []},
                ],
                "resources": [],
            }, ensure_ascii=False), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计画布": {"宽度像素": 320, "高度像素": 180},
                "设计根节点": {"nodeId": "n2", "边界": {"x": 0, "y": 0, "width": 320, "height": 180}},
                "节点": [
                    {"nodeId": "n2", "visible": True, "bounds": {"x": 0, "y": 0, "width": 320, "height": 180}, "style": {"display": "block"}},
                    {"nodeId": "n3", "visible": True, "bounds": {"x": 0, "y": 0, "width": 200, "height": 180}, "style": {"display": "block"}},
                    {"nodeId": "n4", "visible": True, "bounds": {"x": 200, "y": 0, "width": 120, "height": 180}, "style": {"display": "block"}},
                ],
            }, ensure_ascii=False), encoding="utf-8")

            result = GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated")
            source = output.read_text(encoding="utf-8")

            self.assertEqual(result["rootNodeId"], "n2")
            self.assertIn('text = "主区域"', source)
            self.assertIn('text = "侧区域"', source)

    def test_uses_browser_selected_srcset_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            images_path = root / "images.json"
            output = root / "ResponsiveImagePage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "img", "attributes": {"src": "images/fallback.png", "srcset": "images/small.png 1x, images/large.png 2x"}, "classTokens": [], "directText": "", "childrenIds": []},
                ],
                "resources": [
                    {"kind": "image", "source": "images/fallback.png", "resolvedPath": "images/fallback.png", "nodeId": "n2"},
                    {"kind": "image", "source": "images/small.png", "resolvedPath": "images/small.png", "nodeId": "n2"},
                    {"kind": "image", "source": "images/large.png", "resolvedPath": "images/large.png", "nodeId": "n2"},
                ],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计画布": {"宽度像素": 100, "高度像素": 100},
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 100, "height": 100}},
                "节点": [
                    {"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}, "style": {"display": "block"}},
                    {"nodeId": "n2", "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}, "style": {"display": "block", "objectFit": "cover"}},
                ],
                "图片资源": [{"nodeId": "n2", "source": "http://127.0.0.1:43210/images/small.png"}],
            }), encoding="utf-8")
            images_path.write_text(json.dumps({"images": [
                {"sourcePath": "images/fallback.png", "outputName": "fallback.png", "outputPath": "app/src/main/res/mipmap/fallback.png"},
                {"sourcePath": "images/small.png", "outputName": "small.png", "outputPath": "app/src/main/res/mipmap/small.png"},
                {"sourcePath": "images/large.png", "outputName": "large.png", "outputPath": "app/src/main/res/mipmap/large.png"},
            ]}), encoding="utf-8")

            GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated", images_path, "com.example")
            source = output.read_text(encoding="utf-8")

            self.assertIn("R.mipmap.small", source)
            self.assertNotIn("R.mipmap.large", source)

    def test_uses_browser_text_runs_for_mixed_inline_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            output = root / "InlineTextPage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "rootNodeId": "n0",
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "attributes": {}, "classTokens": [], "directText": "", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "p", "attributes": {}, "classTokens": [], "directText": "A  C", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "b", "attributes": {}, "classTokens": [], "directText": "B", "childrenIds": []},
                ],
                "resources": [],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计画布": {"宽度像素": 100, "高度像素": 30},
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 100, "height": 30}},
                "节点": [
                    {"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 30}, "style": {"display": "block", "fontSize": "16px"}},
                    {"nodeId": "n2", "visible": True, "bounds": {"x": 20, "y": 0, "width": 10, "height": 20}, "style": {"display": "inline", "fontSize": "16px", "fontWeight": "700"}},
                ],
                "文本片段": [
                    {"hostNodeId": "n1", "text": "A", "bounds": {"x": 0, "y": 0, "width": 10, "height": 20}, "visible": True, "style": {"fontSize": "16px"}},
                    {"hostNodeId": "n2", "text": "B", "bounds": {"x": 20, "y": 0, "width": 10, "height": 20}, "visible": True, "style": {"fontSize": "16px", "fontWeight": "700"}},
                    {"hostNodeId": "n1", "text": "C", "bounds": {"x": 40, "y": 0, "width": 10, "height": 20}, "visible": True, "style": {"fontSize": "16px"}},
                ],
            }), encoding="utf-8")

            GENERATOR.generate_compose(dom_path, design_path, output, "com.example.generated")
            source = output.read_text(encoding="utf-8")

            self.assertIn('text = "A"', source)
            self.assertIn('text = "B"', source)
            self.assertIn('text = "C"', source)
            self.assertNotIn('text = "A C"', source)
            self.assertIn("designDp(40f, scaleX)", source)

    def test_browser_paint_order_keeps_later_image_over_earlier_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            images_path = root / "images.json"
            output = root / "PaintOrderPage.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "directText": "", "childrenIds": ["n2", "n3"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "span", "directText": "文字", "childrenIds": []},
                    {"nodeId": "n3", "parentId": "n1", "tag": "img", "attributes": {"src": "images/top.png"}, "childrenIds": []},
                ],
                "resources": [{"kind": "image", "nodeId": "n3", "resolvedPath": "images/top.png"}],
            }, ensure_ascii=False), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计画布": {"宽度像素": 100, "高度像素": 100},
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 100, "height": 100}},
                "节点": [
                    {"nodeId": "n1", "paintOrder": 0, "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}, "style": {}},
                    {"nodeId": "n2", "paintOrder": 1, "visible": True, "bounds": {"x": 0, "y": 0, "width": 80, "height": 20}, "style": {"color": "rgb(1, 2, 3)"}},
                    {"nodeId": "n3", "paintOrder": 3, "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}, "style": {}},
                ],
                "文本片段": [{"hostNodeId": "n2", "paintOrder": 2, "text": "文字", "visible": True, "bounds": {"x": 0, "y": 0, "width": 80, "height": 20}, "style": {"color": "rgb(1, 2, 3)"}}],
                "图片资源": [{"nodeId": "n3", "source": "images/top.png"}],
            }, ensure_ascii=False), encoding="utf-8")
            images_path.write_text(json.dumps({"images": [{
                "sourcePath": "images/top.png", "outputName": "top.png", "outputPath": "app/src/main/res/mipmap/top.png"
            }]}), encoding="utf-8")

            GENERATOR.generate_compose(dom_path, design_path, output, "com.example", images_path, "com.example")
            source = output.read_text(encoding="utf-8")

            self.assertLess(source.index('text = "文字"'), source.index("R.mipmap.top"))

    def test_transparent_browser_text_stays_transparent(self) -> None:
        self.assertEqual(GENERATOR._text_color("rgba(0, 0, 0, 0)"), "Color.Transparent")

    def test_escapes_kotlin_string_template_marker(self) -> None:
        self.assertEqual(GENERATOR._kotlin_string("价格 $name"), '"价格 \\$name"')

    def test_rejects_unmapped_css_gradient_instead_of_silently_dropping_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            dom_path.write_text(json.dumps({
                "version": 1,
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "div", "directText": "渐变", "childrenIds": []},
                ],
                "resources": [],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 100, "height": 20}},
                "节点": [{
                    "nodeId": "n1",
                    "visible": True,
                    "bounds": {"x": 0, "y": 0, "width": 100, "height": 20},
                    "style": {"display": "block", "backgroundImage": "linear-gradient(rgb(0, 0, 0), rgb(255, 255, 255))"},
                }],
            }), encoding="utf-8")

            with self.assertRaisesRegex(GENERATOR.GenerationError, "background-image"):
                GENERATOR.generate_compose(dom_path, design_path, root / "Page.kt", "com.example.generated")

    def test_rejects_visual_dom_node_missing_browser_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            dom_path.write_text(json.dumps({
                "version": 1,
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "span", "directText": "不应静默生成", "childrenIds": []},
                ],
                "resources": [],
            }, ensure_ascii=False), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 100, "height": 20}},
                "节点": [{"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 20}, "style": {}}],
            }), encoding="utf-8")

            with self.assertRaisesRegex(GENERATOR.GenerationError, "缺少浏览器布局"):
                GENERATOR.generate_compose(dom_path, design_path, root / "Page.kt", "com.example")

    def test_rejects_descendant_that_requires_parent_overflow_clipping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            dom_path.write_text(json.dumps({
                "version": 1,
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "directText": "", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "div", "directText": "", "childrenIds": []},
                ],
                "resources": [],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 50, "height": 50}},
                "节点": [
                    {"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 50, "height": 50}, "style": {"overflow": "hidden", "backgroundColor": "rgb(0, 0, 255)"}},
                    {"nodeId": "n2", "visible": True, "bounds": {"x": 25, "y": 0, "width": 75, "height": 50}, "style": {"backgroundColor": "red"}},
                ],
            }), encoding="utf-8")

            with self.assertRaisesRegex(GENERATOR.GenerationError, "overflow"):
                GENERATOR.generate_compose(dom_path, design_path, root / "Page.kt", "com.example")

    def test_omits_descendant_fully_outside_parent_overflow_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            output = root / "Page.kt"
            dom_path.write_text(json.dumps({
                "version": 1,
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "main", "childrenIds": ["n2"]},
                    {"nodeId": "n2", "parentId": "n1", "tag": "div", "childrenIds": []},
                ],
                "resources": [],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 50, "height": 50}},
                "节点": [
                    {"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 50, "height": 50}, "style": {"overflow": "hidden", "backgroundColor": "rgb(0, 0, 255)"}},
                    {"nodeId": "n2", "visible": True, "bounds": {"x": 0, "y": 60, "width": 20, "height": 10}, "style": {"backgroundColor": "red"}},
                ],
            }), encoding="utf-8")

            GENERATOR.generate_compose(dom_path, design_path, output, "com.example")

            self.assertNotIn("n2", output.read_text(encoding="utf-8"))

    def test_rejects_visible_pseudo_element_without_measured_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom_path = root / "dom.json"
            design_path = root / "设计解析.json"
            dom_path.write_text(json.dumps({
                "version": 1,
                "nodes": [
                    {"nodeId": "n0", "parentId": None, "tag": "document", "childrenIds": ["n1"]},
                    {"nodeId": "n1", "parentId": "n0", "tag": "div", "directText": "正文", "childrenIds": []},
                ],
                "resources": [],
            }), encoding="utf-8")
            design_path.write_text(json.dumps({
                "设计根节点": {"nodeId": "n1", "边界": {"x": 0, "y": 0, "width": 100, "height": 20}},
                "节点": [{"nodeId": "n1", "visible": True, "bounds": {"x": 0, "y": 0, "width": 100, "height": 20}, "style": {"display": "block"}}],
                "伪元素": [{"nodeId": "n1:before", "hostNodeId": "n1", "pseudo": "::before", "content": "NEW", "visible": True, "bounds": None}],
            }), encoding="utf-8")

            with self.assertRaises(GENERATOR.GenerationError) as error:
                GENERATOR.generate_compose(dom_path, design_path, root / "Page.kt", "com.example.generated")

            self.assertIn("伪元素", str(error.exception))


if __name__ == "__main__":
    unittest.main()
