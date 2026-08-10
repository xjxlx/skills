#!/usr/bin/env python3
"""把 App 截图归一化到设计截图尺寸，供 code-image 做像素对比。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


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
    design = Image.open(design_path)
    app = Image.open(app_path)
    if mode == "fit" and crop is None:
        raise ValueError("fit 模式必须显式提供有效设计画布的裁剪区域")

    source = app
    area = (0, 0, app.width, app.height)
    if crop is not None:
        x, y, width, height = crop
        if x < 0 or y < 0 or x + width > app.width or y + height > app.height:
            raise ValueError(f"裁剪区域超出 App 截图边界：{crop}，截图尺寸为 {app.size}")
        area = crop
        source = app.crop((x, y, x + width, y + height))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    source.convert("RGBA").resize(design.size, Image.Resampling.LANCZOS).save(output_path)
    return {
        "mode": mode,
        "designSize": list(design.size),
        "appSize": list(app.size),
        "effectiveArea": list(area),
        "normalizedSize": list(design.size),
        "scaleX": round(design.width / source.width, 8),
        "scaleY": round(design.height / source.height, 8),
        "design": str(design_path.resolve()),
        "app": str(app_path.resolve()),
        "output": str(output_path.resolve()),
    }


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
