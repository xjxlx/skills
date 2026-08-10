#!/usr/bin/env python3
"""完整 HTML DOM 解析契约测试。"""

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("parse_html_dom.py")
SPEC = importlib.util.spec_from_file_location("parse_html_dom", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT}")
PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER)


class HtmlDomParserTest(unittest.TestCase):
    def test_stores_full_dom_parent_child_text_and_resource_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "pages/index.html",
                    """<!doctype html><html><head><link rel="stylesheet" href="../css/index.css"></head>
                    <body><main id="root" class="flex-col screen"><h1>标题</h1>
                    <img src="../images/logo.png" alt="logo"><section data-kind="cards"><span>内容</span></section>
                    </main></body></html>""",
                )
                zipped.writestr("css/index.css", ".screen { display: flex; }")
                zipped.writestr("images/logo.png", b"png")

            result = PARSER.parse_html_archive(archive, "pages/index.html")
            output = json.loads(json.dumps(result, ensure_ascii=False))
            nodes = {node["nodeId"]: node for node in output["nodes"]}

            self.assertEqual(output["version"], 1)
            self.assertEqual(output["htmlPath"], "pages/index.html")
            self.assertEqual(nodes[output["rootNodeId"]]["tag"], "document")
            main = next(node for node in output["nodes"] if node["attributes"].get("id") == "root")
            self.assertEqual(main["parentId"], next(node["nodeId"] for node in output["nodes"] if node["tag"] == "body"))
            self.assertEqual(main["classTokens"], ["flex-col", "screen"])
            self.assertEqual(main["childrenIds"], [node["nodeId"] for node in output["nodes"] if node["tag"] in {"h1", "img", "section"}])
            self.assertEqual(output["resources"], [
                {"kind": "stylesheet", "source": "../css/index.css", "resolvedPath": "css/index.css", "nodeId": next(node["nodeId"] for node in output["nodes"] if node["tag"] == "link")},
                {"kind": "image", "source": "../images/logo.png", "resolvedPath": "images/logo.png", "nodeId": next(node["nodeId"] for node in output["nodes"] if node["tag"] == "img")},
            ])

    def test_rejects_resource_path_outside_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("index.html", '<img src="../../outside.png">')

            with self.assertRaises(PARSER.DomParseError):
                PARSER.parse_html_archive(archive, "index.html")


if __name__ == "__main__":
    unittest.main()
