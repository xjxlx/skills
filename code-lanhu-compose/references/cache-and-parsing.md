# 缓存与设计解析

## 目录结构

在调用 Skill 时的当前工作目录（即 Android 项目根目录）维护：

```text
.code-lanhu-compose/
└── <zip-stem>-<sha256前6位>/
    ├── 设计解析.json
    ├── images.json
    ├── repeated-block-candidates.json
    └── runs/
        ├── 设计截图.png
        ├── 应用截图.png
        └── 应用截图_1.png
```

`<zip-stem>` 必须经过安全文件名规范化；目录名由 ZIP 文件名和完整 SHA-256 前六位组成。`设计解析.json`、`images.json` 和每次运行证据均只属于这个 ZIP，不保存最终 Compose 代码。项目文件始终依据当前代码、主题和组件重新适配。

两个 JSON 都必须记录完整 `sourceSha256`。首次创建和后续写入前先校验已有完整 Hash：相同 Hash 可以原子更新当前产物，不同 Hash 必须拒绝覆盖，即使前六位恰好相同。旧版根目录下的 `designs/`、`images/`、`runs/` 不得当作新布局的缓存命中，也不得自动移动或删除。

## 图片导入清单

蓝湖 HTML/CSS ZIP 不是 `$code-image --zip` 所需的 `mipmap*` 资源包。图片解压、路径解析、Hash、资源命名和清单写入都由 Python 完成；先运行本 Skill 的逐图协调脚本：

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

首次处理时先用 `start-design-server` 启动仅本机可访问的设计服务，再执行 `采集设计`。解析结果固定写入专属目录内的 `设计解析.json`。同一完整 SHA-256 只保留一个当前解析结果和一份公共设计截图 `runs/设计截图.png`；后续调用会校验完整 Hash、设计解析版本、根节点和公共截图，全部匹配时直接复用，不再启动服务、解压 ZIP、启动浏览器或重复截图。资源导入也复用同一 Hash 对应且文件完整的下载解压目录。所有运行证据直接保留在同一目录的 `runs/` 根目录，禁止创建时间戳子目录；App 截图按 `应用截图.png`、`应用截图_1.png`、`应用截图_2.png`……递增保存。

## 缓存命中

只有以下条件全部成立才复用：

1. 当前 ZIP 对应的专属目录存在。
2. `设计解析.json` 真实存在且可解析。
3. 解析文件记录的源 SHA-256 与当前 ZIP 一致。
4. 解析结构与当前读取逻辑兼容。

任一条件失败时重新执行 `start-design-server → 采集设计` 并原子更新 `设计解析.json`；只有截图证据而没有设计解析文件时，不得判定为缓存命中。写入 JSON 时先写临时文件，再原子替换，避免中断造成半文件。

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
- `repeated-block-candidates.json` 中的近似尺寸卡片候选、四项尺寸范围、背景资源、共享父节点要求与待确认的布局方向。

## 解析要求

- 用 DOM 关系确定结构，不只扫描 `.paragraph_4` 一类选择器。
- 节点身份、图片资源名优先取非布局工具的主类或 ID；`flex-row`、`flex-col` 不能单独成为节点名。它们若在实际加载 CSS 中命中规则，必须通过 `getComputedStyle()` 保留对布局的贡献。
- 用 `getComputedStyle()` 解析继承、层叠、行内样式和 CSS 变量。
- 用 `getBoundingClientRect()` 记录浏览器完成 flex、transform 和定位计算后的边界。
- 分别读取 `::before`、`::after`；有可见内容时作为设计节点记录。
- 等待 `document.fonts.ready`、图片完成和布局稳定后再采集。
- 同时保留父级和子级的 padding、gap、margin 声明，避免只看最终坐标后丢失间距归属。
- 记录遮挡与 `z-index`，但不可据此把正常流布局改写成全页面绝对定位。
- 每次 `inspect` 对实际加载 CSS 运行重复卡片检测：仅在宽、高、背景宽、背景高单位一致且每项总范围不超过 `2`、并由 HTML 确认共享父节点时写入候选；候选不是方向或可滚动性的证据，后续必须以共享父节点的 `getComputedStyle()` 和最终边界确认。
