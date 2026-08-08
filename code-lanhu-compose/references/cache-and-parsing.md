# 缓存与设计解析

## 目录结构

在调用 Skill 时的当前工作目录（即 Android 项目根目录）维护：

```text
.code-lanhu-compose/
└── <zip-stem>-<sha256前6位>/
    ├── design.json
    ├── images.json
    └── runs/
        └── yyyyMMdd-HHmmss/
```

`<zip-stem>` 必须经过安全文件名规范化；目录名由 ZIP 文件名和完整 SHA-256 前六位组成。`design.json`、`images.json` 和每次运行证据均只属于这个 ZIP，不保存最终 Compose 代码。项目文件始终依据当前代码、主题和组件重新适配。

两个 JSON 都必须记录完整 `sourceSha256`。首次创建和后续写入前先校验已有完整 Hash：相同 Hash 可以原子更新当前产物，不同 Hash 必须拒绝覆盖，即使前六位恰好相同。旧版根目录下的 `designs/`、`images/`、`runs/` 不得当作新布局的缓存命中，也不得自动移动或删除。

## 图片导入清单

蓝湖 HTML/CSS ZIP 不是 `$code-image --zip` 所需的 `mipmap*` 资源包。先运行本 Skill 的逐图协调脚本：

```bash
python3 scripts/import_zip_images.py \
  --zip <zip-path> \
  --compose <target-compose> \
  --project-root <project-root> \
  --apply
```

脚本安全解压 ZIP 到 `~/Downloads/<zip-stem>-<sha256前6位>/`，按 ZIP 内图片逐个调用 `$code-image --image <extracted-image> --compose <target-compose> --project-root <project-root> --apply`。输出位于 `$code-image` 规定的 `mipmap-xxhdpi`；同一 ZIP 的全部图片复用 `.code-image/<zip-stem>-<zip-sha256前6位>.resources.json` 与已有输出，不得使用共享 `resources.json`。

随后将本 ZIP 的来源和实际导入结果写入 `<zip-stem>-<sha256前6位>/images.json`。每项至少记录 ZIP 内 `sourcePath`、解压后路径、原始文件名、解析出的 `assetName`、内容 Hash、真实 `outputPath`、`outputName` 和 `resourceManifest`。该文件仅用于本 ZIP 的设计资源与 Compose 引用对应，不再作为 `$code-image` 的输入。

## 设计产物格式

```json
{
  "sourceName": "report-home.zip",
  "sourcePath": "/Users/name/Downloads/report-home.zip",
  "sourceSize": 123456,
  "sourceSha256": "a1b2c3d4完整SHA256",
  "canvasWidthPx": 1920,
  "canvasHeightPx": 720
}
```

解析结果固定写入专属目录内的 `design.json`。同一完整 SHA-256 只保留一个当前解析结果，运行证据保留在同一目录的 `runs/yyyyMMdd-HHmmss/`。运行目录只使用年月日、时分秒命名，不再拼接 SHA 或其他参数。

## 缓存命中

只有以下条件全部成立才复用：

1. 当前 ZIP 对应的专属目录存在。
2. `design.json` 真实存在且可解析。
3. 解析文件记录的源 SHA-256 与当前 ZIP 一致。
4. 解析结构与当前读取逻辑兼容。

任一条件失败时重新解析并原子更新 `design.json`；只有截图证据而没有设计 JSON 时，不得判定为缓存命中。写入 JSON 时先写临时文件，再原子替换，避免中断造成半文件。

## 标准化设计产物

解析产物至少包含：

- 源 ZIP 名称、完整 SHA-256、HTML/CSS 相对路径。
- 设计画布宽高、设计根节点和浏览器渲染环境。
- DOM 父子层级、元素标签、class、id、文本和伪元素内容。
- 每个 class 的原始 token、主节点 token、布局工具 token，以及各自命中的 CSS 选择器；`flex-row`、`flex-col` 只归为布局工具，仍保留其参与的最终计算样式。
- 每个节点的最终边界、可见性、层叠顺序和变换矩阵。
- 布局模式、方向、对齐、`gap`、padding、margin、宽高约束和 overflow。
- 最终颜色、字体族、字号、字重、行高、字距、文本对齐和最大行数。
- 背景、边框、圆角、阴影、透明度和资源 URL。
- 图片相对路径、内容 Hash、原始像素尺寸和展示裁剪方式。

## 解析要求

- 用 DOM 关系确定结构，不只扫描 `.paragraph_4` 一类选择器。
- 节点身份、图片资源名优先取非布局工具的主类或 ID；`flex-row`、`flex-col` 不能单独成为节点名。它们若在实际加载 CSS 中命中规则，必须通过 `getComputedStyle()` 保留对布局的贡献。
- 用 `getComputedStyle()` 解析继承、层叠、行内样式和 CSS 变量。
- 用 `getBoundingClientRect()` 记录浏览器完成 flex、transform 和定位计算后的边界。
- 分别读取 `::before`、`::after`；有可见内容时作为设计节点记录。
- 等待 `document.fonts.ready`、图片完成和布局稳定后再采集。
- 同时保留父级和子级的 padding、gap、margin 声明，避免只看最终坐标后丢失间距归属。
- 记录遮挡与 `z-index`，但不可据此把正常流布局改写成全页面绝对定位。
