#!/usr/bin/env python3
"""把 App 截图归一化到设计截图尺寸，供 code-image 做像素对比。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from PIL import Image


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".normalization.json")


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("裁剪区域必须是 x,y,width,height")
    try:
        crop = tuple(int(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError("裁剪区域必须全部是整数") from error
    if crop[2] <= 0 or crop[3] <= 0:
        raise argparse.ArgumentTypeError("裁剪宽高必须大于 0")
    return crop


def normalize(design_path: Path, app_path: Path, output_path: Path, mode: str, crop: tuple[int, int, int, int] | None) -> dict[str, object]:
    design_path = design_path.resolve()
    app_path = app_path.resolve()
    output_path = output_path.resolve()
    if output_path in {design_path, app_path}:
        raise ValueError("输出文件不能覆盖设计截图或 App 截图")
    if mode == "fit" and crop is None:
        raise ValueError("fit 模式必须显式提供有效设计画布的裁剪区域")

    with Image.open(design_path) as design, Image.open(app_path) as app:
        design_size = design.size
        app_size = app.size
        source = app.convert("RGBA")
        area = (0, 0, app.width, app.height)
        if crop is not None:
            x, y, width, height = crop
            if x < 0 or y < 0 or x + width > app.width or y + height > app.height:
                raise ValueError(f"裁剪区域超出 App 截图边界：{crop}，截图尺寸为 {app.size}")
            area = crop
            source = source.crop((x, y, x + width, y + height))

        source_ratio = source.width / source.height
        design_ratio = design.width / design.height
        aspect_error = abs(source_ratio / design_ratio - 1.0)
        if mode == "fit" and aspect_error > 0.001:
            raise ValueError(
                f"fit 模式裁剪区域与设计稿宽高比不一致：{source.size} vs {design.size}；"
                "请修正 --crop，禁止拉伸后比较"
            )
        normalized = source.resize(design.size, Image.Resampling.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    output_format = Image.registered_extensions().get(suffix, "PNG")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.stem}-",
            suffix=suffix or ".png",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        normalized.save(temporary_path, format=output_format)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    result = {
        "mode": mode,
        "designSize": list(design_size),
        "appSize": list(app_size),
        "effectiveArea": list(area),
        "normalizedSize": list(design_size),
        "scaleX": round(design_size[0] / source.width, 8),
        "scaleY": round(design_size[1] / source.height, 8),
        "aspectRatioError": round(aspect_error, 8),
        "design": str(design_path),
        "app": str(app_path),
        "output": str(output_path),
        "designMd5": md5_file(design_path),
        "appMd5": md5_file(app_path),
        "outputMd5": md5_file(output_path),
    }
    report = provenance_path(output_path)
    result["provenancePath"] = str(report)
    temporary_report = report.with_suffix(report.suffix + ".tmp")
    temporary_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_report, report)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="归一化设计稿与 App 截图的有效画布")
    parser.add_argument("--design", required=True, type=Path)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("fill", "fit"), required=True)
    parser.add_argument("--crop", type=parse_crop, help="x,y,width,height；fit 模式必填")
    args = parser.parse_args()
    try:
        result = normalize(args.design, args.app, args.output, args.mode, args.crop)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
