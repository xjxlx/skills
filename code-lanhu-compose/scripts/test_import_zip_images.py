#!/usr/bin/env python3
"""import_zip_images.py 的本地缓存契约测试。"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("import_zip_images.py")
SPEC = importlib.util.spec_from_file_location("import_zip_images", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {SCRIPT_PATH}")
IMPORT_IMAGES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT_IMAGES)


class ImportZipImagesContractTest(unittest.TestCase):
    def test_extract_zip_reuses_complete_source_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "design.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("images/a.png", b"original-image")

            source_hash = IMPORT_IMAGES.sha256_file(archive)
            with patch.object(IMPORT_IMAGES.Path, "home", return_value=Path(temp_dir)):
                extraction_root, images = IMPORT_IMAGES.extract_zip(archive, source_hash)
                image_path = images[0][1]
                image_path.write_bytes(b"cached-content")

                second_root, second_images = IMPORT_IMAGES.extract_zip(archive, source_hash)

            self.assertEqual(second_root, extraction_root)
            self.assertEqual(second_images[0][1].read_bytes(), b"cached-content")


if __name__ == "__main__":
    unittest.main()
