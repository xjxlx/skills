#!/usr/bin/env python3
"""独立的设计图与应用截图视觉对比工具。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np


class ComparisonError(ValueError):
    """输入图片或对比参数不满足契约。"""


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise ComparisonError(f"图片不存在：{path}")
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ComparisonError(f"无法读取图片：{path}")
    return image


def align_images(design: np.ndarray, app: np.ndarray, tolerance: float) -> tuple[np.ndarray, dict]:
    design_height, design_width = design.shape[:2]
    app_height, app_width = app.shape[:2]
    design_ratio = design_width / design_height
    app_ratio = app_width / app_height
    ratio_error = abs(design_ratio - app_ratio) / design_ratio
    if ratio_error > tolerance:
        raise ComparisonError(
            f"设计图与应用截图宽高比不一致：{design_width}x{design_height} "
            f"vs {app_width}x{app_height}，偏差 {ratio_error:.4f} > {tolerance:.4f}"
        )
    if (app_width, app_height) == (design_width, design_height):
        aligned = app.copy()
        scale_x = scale_y = 1.0
    else:
        aligned = cv2.resize(app, (design_width, design_height), interpolation=cv2.INTER_AREA)
        scale_x = design_width / app_width
        scale_y = design_height / app_height
    return aligned, {
        "designSize": [design_width, design_height],
        "appSize": [app_width, app_height],
        "alignedSize": [design_width, design_height],
        "scale": [round(scale_x, 8), round(scale_y, 8)],
        "offset": [0, 0],
        "aspectRatioError": round(ratio_error, 8),
    }


def ssim_score(first: np.ndarray, second: np.ndarray) -> float:
    """计算不依赖 scikit-image 的灰度 SSIM 均值。"""
    first_gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY).astype(np.float64)
    second_gray = cv2.cvtColor(second, cv2.COLOR_BGR2GRAY).astype(np.float64)
    kernel = (11, 11)
    sigma = 1.5
    mean_first = cv2.GaussianBlur(first_gray, kernel, sigma)
    mean_second = cv2.GaussianBlur(second_gray, kernel, sigma)
    mean_first_square = mean_first * mean_first
    mean_second_square = mean_second * mean_second
    mean_product = mean_first * mean_second
    variance_first = cv2.GaussianBlur(first_gray * first_gray, kernel, sigma) - mean_first_square
    variance_second = cv2.GaussianBlur(second_gray * second_gray, kernel, sigma) - mean_second_square
    covariance = cv2.GaussianBlur(first_gray * second_gray, kernel, sigma) - mean_product
    constant_one = (0.01 * 255) ** 2
    constant_two = (0.03 * 255) ** 2
    numerator = (2 * mean_product + constant_one) * (2 * covariance + constant_two)
    denominator = (mean_first_square + mean_second_square + constant_one) * (
        variance_first + variance_second + constant_two
    )
    return float(np.clip(np.mean(numerator / np.maximum(denominator, 1e-12)), 0.0, 1.0))


def build_regions(diff: np.ndarray, mask: np.ndarray, minimum_area: int) -> list[dict]:
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    regions = []
    max_error = diff.max(axis=2)
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if area < minimum_area:
            continue
        region_mask = mask[y : y + height, x : x + width] > 0
        region_error = max_error[y : y + height, x : x + width]
        regions.append(
            {
                "bounds": [x, y, width, height],
                "area": area,
                "changedRatio": round(float(region_mask.mean()), 6),
                "meanError": round(float(region_error[region_mask].mean()), 4),
                "maxError": int(region_error.max()),
                "center": [round(float(centroids[index][0]), 2), round(float(centroids[index][1]), 2)],
            }
        )
    return sorted(regions, key=lambda region: region["area"], reverse=True)


def atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def compare_images(
    design_path: Path,
    app_path: Path,
    output_dir: Path,
    threshold: int = 8,
    minimum_region_area: int = 4,
    aspect_tolerance: float = 0.01,
) -> dict:
    if not 0 <= threshold <= 255:
        raise ComparisonError("--threshold 必须在 0 到 255 之间")
    if minimum_region_area < 1:
        raise ComparisonError("--min-region-area 必须大于 0")
    if aspect_tolerance < 0:
        raise ComparisonError("--aspect-tolerance 不能为负数")

    design = load_image(design_path)
    app = load_image(app_path)
    aligned_app, transform = align_images(design, app, aspect_tolerance)
    diff = cv2.absdiff(design, aligned_app)
    max_error = diff.max(axis=2)
    mask = np.where(max_error > threshold, 255, 0).astype(np.uint8)
    regions = build_regions(diff, mask, minimum_region_area)
    changed_pixels = int(np.count_nonzero(mask))
    total_pixels = int(mask.size)
    mae = float(diff.mean())
    rmse = float(np.sqrt(np.mean(np.square(diff.astype(np.float64)))))
    edges_design = cv2.Canny(design, 100, 200)
    edges_app = cv2.Canny(aligned_app, 100, 200)
    edge_mask = cv2.bitwise_xor(edges_design, edges_app)

    output_dir.mkdir(parents=True, exist_ok=True)
    mask_path = output_dir / "diff-mask.png"
    heatmap_path = output_dir / "diff-heatmap.png"
    overlay_path = output_dir / "diff-overlay.png"
    report_path = output_dir / "diff.json"
    cv2.imwrite(str(mask_path), mask)
    cv2.imwrite(str(heatmap_path), cv2.applyColorMap(max_error, cv2.COLORMAP_JET))
    overlay = cv2.addWeighted(design, 0.5, aligned_app, 0.5, 0)
    overlay[mask > 0] = (0, 0, 255)
    cv2.imwrite(str(overlay_path), overlay)
    report = {
        "version": 1,
        "design": {"path": str(design_path.resolve()), "md5": md5_file(design_path)},
        "app": {"path": str(app_path.resolve()), "md5": md5_file(app_path)},
        "transform": transform,
        "threshold": threshold,
        "minRegionArea": minimum_region_area,
        "metrics": {
            "changedPixels": changed_pixels,
            "totalPixels": total_pixels,
            "changedRatio": round(changed_pixels / total_pixels, 8),
            "mae": round(mae, 6),
            "rmse": round(rmse, 6),
            "maxError": int(max_error.max()),
            "similarity": round(ssim_score(design, aligned_app), 8),
            "edgeChangedRatio": round(float(np.count_nonzero(edge_mask) / edge_mask.size), 8),
        },
        "changedPixels": changed_pixels,
        "similarity": round(ssim_score(design, aligned_app), 8),
        "regions": regions,
        "artifacts": {
            "mask": str(mask_path.resolve()),
            "heatmap": str(heatmap_path.resolve()),
            "overlay": str(overlay_path.resolve()),
        },
    }
    atomic_write_json(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立对比设计图与应用截图的像素、结构和差异区域")
    parser.add_argument("--design", required=True, type=Path, help="设计基准图")
    parser.add_argument("--app", required=True, type=Path, help="应用截图")
    parser.add_argument("--output-dir", required=True, type=Path, help="差异报告与证据图输出目录")
    parser.add_argument("--threshold", type=int, default=8, help="单像素最大通道差异阈值，默认 8")
    parser.add_argument("--min-region-area", type=int, default=4, help="忽略小于该像素面积的差异区域，默认 4")
    parser.add_argument("--aspect-tolerance", type=float, default=0.01, help="允许的宽高比相对偏差，默认 1%%")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = compare_images(
            args.design,
            args.app,
            args.output_dir,
            threshold=args.threshold,
            minimum_region_area=args.min_region_area,
            aspect_tolerance=args.aspect_tolerance,
        )
    except (ComparisonError, OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", "report": str((args.output_dir / 'diff.json').resolve()), "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
