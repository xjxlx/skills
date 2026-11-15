---
name: "code-compose-v2"
description: "将蓝湖等工具导出的 HTML/CSS/图片设计包转换为可运行、可验证的 Jetpack Compose 页面；用于元素缺失、文字裁切、布局偏移、列表/弹窗还原和图标验证。"
---

# 蓝湖 HTML → Jetpack Compose

所有面向用户的沟通、说明和代码注释使用中文。

## 职责

本 Skill 负责一次完整的 HTML 设计包到 Jetpack Compose 页面转换：

- 解析 HTML DOM 的几何、样式、层级和布局关系。
- 直接选择 `Box`、`Row`、`Column`、`LazyRow`、`LazyColumn` 或网格容器。
- 复用项目资源、状态和组件封装。
- 通过已运行的应用、整页像素、元素边界和局部色差完成验收。

不适用于只有截图、没有 HTML/CSS/图片资源的任务；先要求用户提供完整设计包。

## 固定基准与页面宿主

- 只接受 `1334px × 750px` 的横屏设计包；尺寸不一致时立即停止并提示用户重新导出。
- 固定 `DP_PER_PX=0.5`，即 `1334×750px → 667×375dp`。不得通过 `DESIGN_WIDTH`、`DESIGN_HEIGHT`、`DP_PER_PX` 或其他环境变量覆盖。
- 生成页面不处理窗口适配，不生成 `AutoSizeConfig`、`BoxWithConstraints`、局部 `Density` 或整页缩放。
- Activity 层只调用一次项目已有的 `BaseV3Page { GeneratedPage() }`。`BaseV3Page` 是唯一允许承载横屏基准缩放的包装层。
- 优先复用项目的 `TestActivity.kt`，要求它继承项目已有的全屏 Compose Activity 封装，并通过 `BaseV3Page` 承载页面。已有测试 Activity 只补充当前页面的临时入口、状态和样例数据，不创建第二套 Activity。
- 测试 Activity 不承担业务导航，只用于临时展示、截图和结构校验；验收完成后撤销本轮临时接线和样例数据，保留可复用的全屏测试宿主。
- Activity、方向和 Manifest 只在任务开始时扫描一次，结果写入 `.code-compose-v2/out/runtime-context.json`；后续生成和验证脚本直接复用，不得重复扫描。

## 启动与依赖

1. 检查远端技能版本并按公共约束拉取最新提交。
2. 确认工作区现有改动，不覆盖用户未提交内容。
3. 检查 `scripts/node_modules` 和依赖状态；依赖存在时直接使用，不重复执行 `npm ci`。缺失时明确提示用户安装，不在正常页面流程中自动重装依赖。
4. 配置 `PROJECT_ROOT`、Compose 目录、包名、`R`、`TextItem`/`ImageItem` import、Activity 和目标页面名；完整变量见 [配置参考](references/configuration.md)。

## 固定流程

1. 在目标 Android 项目根目录定位并确认全屏 Compose 测试 Activity，只解析一次 Manifest。
2. 解压设计包，定位直接包含 `index.html` 或 `.code-lanhu-index.html` 的目录。
3. 运行一次 `normalize.js`：采集 DOM 语义树，并截取 `original.png` 作为唯一视觉真源。
4. 根据 HTML 布局参数直接生成 Compose，不生成“绝对定位基线”中间阶段，也不设置验收后才允许语义化的门槛。
5. 将生成页面临时接入全屏测试 Activity，由 IDE Running、Run 或 Apply Changes 刷新正在运行的应用。脚本不执行 `assembleDebug` 或 `adb install -r`。
6. 运行 `compose-validate.js`，一次生成整页像素、结构边界、局部抽查、差异图和统一报告。
7. 未达到 95% 时，根据差异区域和失败元素修正生成逻辑，再由 IDE 刷新并重新验证。

## HTML 与 Compose 生成

- 以 DOM 文本、角色、矩形、层级、间距、对齐轴、背景和重复结构为依据选择布局，不根据页面业务名称生成固定结构。
- 固定骨架和可重复入口使用稳定锚点。页面级区域可使用 `ConstraintLayout` 和独立 `Guideline`；在首次使用 Guideline 的节点前就地创建，禁止集中声明在 `ConstraintLayout` 顶部。有明确方向的连续内容使用 `Row`、`Column` 或列表容器。
- 3 个及以上条目共享近似外框尺寸、对齐轴、间距和字段槽位时，按数据类、`listOf` 和单一 item Composable 建模。
- 横向或纵向列表由可见视口和排列方向决定。尾项只被视口裁切时，数据仍保存完整 item 尺寸，由 `LazyRow`/`LazyColumn` 自然裁切。
- 透明容器可扁平化；同 rect 的背景层可合并到同一复合项。只有设计和交互确实需要时才使用页面级 `offset`，不得用 `graphicsLayer` 整页缩放掩盖几何误差。
- 文字内容默认由文字测量决定宽高；固定视觉盒、裁切和覆盖关系才使用固定尺寸。固定行盒出现底部裁切时，先检查父约束和测量高度，再调整行高、绘制高度或 `wrapContentHeight(unbounded = true)`。
- 页面颜色、Shape 和视觉常量按“类型 + 实际值”命名，例如 `COLOR_F5F7FA`、`ROUNDED_CORNER_SHAPE_14`。
- 每个命名 Composable、辅助函数和自定义定位方法使用中文 KDoc；参数较多时补充 `@param`。
- 只生成原始 HTML 中可见且有视觉证据的节点。不得根据文案或组件名补造箭头、指示器、装饰和业务数据。

## 项目组件与资源

- 页面可见文本默认使用项目 `TextItem`；图片默认使用 `ImageItem` 和 `ImageParameter`。只有文字装饰、特殊交互或项目封装无法表达时，才使用 Material3 组件。
- `TextItem` 和 `ImageItem` 的具体 import 由项目配置提供，不得硬编码到不兼容的包名。
- 图片优先按完整 MD5 从项目根目录 `.code-image/image.json` 中复用当前模块的有效资源，并确认路径存在且内容 Hash 匹配。
- 显式 `COMPOSE_RESOURCE_MAP` 可指定现有 `R` 资源名；映射优先于自动匹配。
- 项目现有资源和 `.code-image` 均无法确认匹配时，才从设计包复制图片到当前模块 `mipmap-xxhdpi`。
- 纯色背景、圆角、描边、阴影和透明边缘使用 Compose `Color`、`Shape` 和 Modifier；只有纹理、照片、插画和无法用代码可靠表达的图标使用图片。
- 运行产物只写入目标项目 `.code-compose-v2/`，不得把截图、报告、设计资源或 `node_modules` 复制回技能仓库。

## 状态与行为

- 生成前建立状态模型：页面数据、当前选中项、弹窗开关、列表数据、滚动状态和点击后的变化。
- 优先复用现有 ViewModel、状态 owner、回调和资源名；证据不足时保留项目现有契约，并记录未验证行为。
- 选中态、关闭态、箭头和筛选结果由同一状态源驱动。资源副作用使用稳定业务 key，并在 `DisposableEffect` 中释放。
- 弹窗使用项目已有 Dialog 或锚点 Popup 宿主，不把弹窗画布直接追加到主页面坐标树。
- 静态设计无法证明导航目标或接口数据时，不臆造业务 API；只生成可见状态或复用已有回调。

## 验收闭环

统一使用 `compose-validate.js`，不再保留独立整页截图脚本或重复验证器。单次验证包含：

1. 启动 IDE 已经运行的最新 Activity；使用 `am start -W` 和短轮询等待 `testTag` 就绪，不使用固定长等待。
2. 截取当前真实横屏画面，与 `original.png` 计算整页像素相似度。
3. 通过 `uiautomator` 获取 `testTag("e<domIndex>")` 边界，与语义树 rect 比对；重组或动画期间 dump 可能返回空树，短轮询重试直到非空语义树。
4. 对文本和关键区域做局部色差抽查。
5. 输出 `compose-report.json`、`compose-diff.png`、热点、差异区域和失败元素。

验收条件：

- 整页像素相似度不少于 `95%`。
- 结构边界通过率不少于 `95%`。
- 局部抽查通过率不少于 `80%`。
- 原始设计截图尺寸必须与语义树一致。

未通过时按以下顺序排查并修正：

1. 缺失元素：检查 DOM 可见性、资源过滤、列表槽位和 `testTag`。
2. 位置/尺寸异常：检查父容器约束、锚点、Row/Column 测量和视口裁切。
3. 图片差异：检查 code-image Hash、显式映射、ContentScale 和裁剪几何。
4. 文字差异：检查 `TextItem` 字体、行高、最大行数、对齐和父容器高度。
5. 层级差异：检查 z 序、遮罩、Dialog/Popup 宿主和覆盖关系。

修正生成器或页面后，通过 IDE Running 刷新应用并重新验证。单轮任务最多自动修正 5 次；仍未达到 95% 时保留最佳报告并明确停止，禁止原样重跑、无限循环或伪造通过。

## 参考文件

- [配置参考](references/configuration.md)：命令、变量、目录和运行模式。
- [工作流细则](references/workflow.md)：HTML 分析、生成、运行和验收细节。
- [生产级 Compose 适配](references/production-compose-style.md)：现有项目结构、组件和状态复用规则。

## 技能公共约束

- 本 Skill 对 `$skill-common` 的启动自动发布规则作明确例外：每次调用只拉取远端更新，不执行 `check_and_publish.sh`，不提交或推送本地 Skill 变更。使用 GitHub Manager 的网络封装对技能所在仓库执行 `fetch origin main`；本地落后时用 `pull --ff-only --autostash origin main` 安全快进，版本相同或本地领先时直接继续，历史分叉或拉取失败时立即停止并报告。只有用户明确要求发布时才允许上传本地更新。
- 遵守 `$skill-common` 的中文优先、职责唯一、依赖去重及证据驱动的进化规范；任务完成并验证后调用 `$skill-common` 复盘。
