# 图片视觉对比契约

`compare_images.py` 是 `code-image` 的独立脚本，只在明确要求视觉对比时调用。它与 `normalize_images.py` 没有共享写入流程，不会复制图片、修改 Android 资源或修改 Compose。

## 输入

```bash
python3 scripts/compare_images.py \
  --design <设计基准图> \
  --app <应用截图> \
  --output-dir <输出目录> \
  [--threshold 8] \
  [--min-region-area 4] \
  [--aspect-tolerance 0.01]
```

- `--design`：设计基准图。
- `--app`：应用截图。
- `--output-dir`：写入差异报告和证据图的目录；不会覆盖输入图。
- `--threshold`：单像素最大通道差异阈值，默认 `8`，用于过滤轻微抗锯齿误差。
- `--min-region-area`：忽略小于指定像素面积的连通区域，默认 `4`。
- `--aspect-tolerance`：允许设计图与应用截图的宽高比相对偏差，默认 `0.01`；超过时拒绝比较，避免拉伸掩盖布局错误。

应用截图与设计图宽高比一致但尺寸不同，会按设计图尺寸使用 `INTER_AREA` 对齐；缩放比例和原始尺寸会写入报告。

## 输出

输出目录包含：

- `diff.json`：输入 Hash、对齐变换、阈值、changed ratio、MAE、RMSE、SSIM、边缘差异和区域列表。
- `diff-mask.png`：超过阈值的像素遮罩。
- `diff-heatmap.png`：差异强度热力图。
- `diff-overlay.png`：设计图与应用截图叠加，差异像素标为红色。

区域 `bounds` 使用设计图对齐后的像素坐标 `[x, y, width, height]`。调用方可以把它与设计解析节点边界或页面区域映射，再决定是否修改 Compose；脚本本身不做代码修改。

## 判定边界

不要只用 `similarity` 一个指标决定是否通过。动态修正至少同时观察 `changedRatio`、`similarity`、`edgeChangedRatio` 和关键区域的 `meanError`；修改后指标没有改善时应拒绝该轮修改。脚本只提供可复现证据，不替代模型对页面语义的判断。
