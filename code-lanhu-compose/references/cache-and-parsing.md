# 缓存与设计解析

## 目录结构

在调用 Skill 时的当前工作目录（即 Android 项目根目录）维护：

```text
.code-compose/
├── index.json
├── designs/
│   └── yyyyMMdd-HHmmss-<sha256前8位>.json
└── runs/
    └── <run-id>/
```

`index.json` 只路由设计源和解析产物，不保存最终 Compose 代码。项目文件始终依据当前代码、主题和组件重新适配。

## 索引格式

```json
{
  "a1b2c3d4完整SHA256": {
    "sourceName": "report-home.zip",
    "sourcePath": "/Users/name/Downloads/report-home.zip",
    "sourceSize": 123456,
    "sourceSha256": "a1b2c3d4完整SHA256",
    "artifactPath": "designs/20260805-143025-a1b2c3d4.json",
    "canvasWidthPx": 1920,
    "canvasHeightPx": 720
  }
}
```

使用 `yyyyMMdd-HHmmss-<sha256前8位>.json` 命名解析文件。同一 SHA-256 只保留一个当前有效路由，运行证据保留在 `runs/`。

## 缓存命中

只有以下条件全部成立才复用：

1. ZIP 完整 SHA-256 存在于 `index.json`。
2. `artifactPath` 指向的文件真实存在且可解析。
3. 解析文件记录的源 SHA-256 与当前 ZIP 一致。
4. 解析结构与当前读取逻辑兼容。

任一条件失败时重新解析并修复索引。写入 JSON 时先写临时文件，再原子替换，避免中断造成半文件。

## 标准化设计产物

解析产物至少包含：

- 源 ZIP 名称、完整 SHA-256、HTML/CSS 相对路径。
- 设计画布宽高、设计根节点和浏览器渲染环境。
- DOM 父子层级、元素标签、class、id、文本和伪元素内容。
- 每个节点的最终边界、可见性、层叠顺序和变换矩阵。
- 布局模式、方向、对齐、`gap`、padding、margin、宽高约束和 overflow。
- 最终颜色、字体族、字号、字重、行高、字距、文本对齐和最大行数。
- 背景、边框、圆角、阴影、透明度和资源 URL。
- 图片相对路径、内容 Hash、原始像素尺寸和展示裁剪方式。

## 解析要求

- 用 DOM 关系确定结构，不只扫描 `.paragraph_4` 一类选择器。
- 用 `getComputedStyle()` 解析继承、层叠、行内样式和 CSS 变量。
- 用 `getBoundingClientRect()` 记录浏览器完成 flex、transform 和定位计算后的边界。
- 分别读取 `::before`、`::after`；有可见内容时作为设计节点记录。
- 等待 `document.fonts.ready`、图片完成和布局稳定后再采集。
- 同时保留父级和子级的 padding、gap、margin 声明，避免只看最终坐标后丢失间距归属。
- 记录遮挡与 `z-index`，但不可据此把正常流布局改写成全页面绝对定位。
