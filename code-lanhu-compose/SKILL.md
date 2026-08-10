---
name: code-lanhu-compose
description: Use when 用户提供或准备提供蓝湖导出的 HTML/CSS ZIP，需要在 Android 项目中生成或还原 Jetpack Compose 页面，并进行图片资源处理、编译运行或设计稿截图对比。
---

# code-lanhu-compose

把蓝湖导出的 HTML/CSS ZIP 转换为符合当前 Android 项目规范的 Compose 页面，并用设计稿与 App 截图完成可追溯的视觉修正。结构按 HTML 层级转换，间距按 CSS 属性归属转换，浏览器最终计算结果用于消除样式歧义和验证视觉结果。

## 职责与例外

- 遵循 `$skill-common` 基础规范。每次调用本 Skill 时，先执行 `"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"`；检测或发布成功后再继续，失败时立即停止。
- 只负责蓝湖 ZIP 的设计解析、Compose 生成、图片接入和视觉验证闭环。
- 不调用、不继承旧 `$code-compose`，也不读取它的规则或缓存。
- 图片接入、内容 Hash、资源清单和浏览器最终布局采集均由 Python 固定脚本全权执行；图片接入时再调用 `$code-image` 这个确定性子工具。大模型不得参与 Hash、路径解析、资源命名或 DOM 采集，也不得修改原始 JSON 证据。
- 模拟器验证能力可用时调用 `test-android-apps:android-emulator-qa`；不可用时才执行本 Skill 规定的显式 ADB 流程。
- 以 `scripts/lanhu_pipeline.py run-fixed` 作为默认固定入口；它自动完成设计服务/浏览器采集、资源 Hash/导入、Gradle 任务发现和编译。浏览器、资源和 Gradle 命令均由 Python 决定并执行；大模型不得逐项调用或替换这些步骤，只能修改 Compose 并再次调用 `run-fixed`，或提交页面语义相关的契约化 JSON 决策。
- 无法从设计、编译或截图证据确定语义时，写入 `needs-user-input.json` 并暂停，交由用户确认，不用猜测推进。

## 必需输入

首次处理一个设计时，只确认：

1. 蓝湖 ZIP 本地路径。用户未提供时必须先索取。
2. 目标 Compose 文件；如果文件尚不存在，确认页面名、模块和包路径。

将调用时的当前工作目录视为目标 Android 项目根目录，禁止向用户单独索取根目录地址。当前工作目录缺少 `settings.gradle`、`settings.gradle.kts` 或 Gradle Wrapper 等 Android 项目标识时，停止并要求用户从正确的项目根目录重新调用，不改为索取目录地址。

复用用户已经提供的信息，不重复询问。无法确定目标文件时，不生成代码。

## 执行流程

### 1. 预检项目和设计包

- 首次处理 ZIP 先执行 `python3 scripts/lanhu_pipeline.py run-fixed --zip <zip> --project-root <project> --compose <Compose.kt>`；同一完整 `sourceMd5` 命中完整缓存时直接复用当前阶段，不得重新解析 ZIP 或重置 `pipeline.json`。固定阶段和参数见 [固定编排链路契约](references/pipeline-contract.md)。
- 确认 ZIP、当前工作目录中的 Android 项目、目标模块和构建入口可访问；在项目根目录优先执行 `./gradlew`，仅当 Wrapper 缺失且系统存在 `gradle` 时才回退到 `gradle`。
- 在解析 ZIP、导入图片或生成 Compose 前，从项目任务列表确定唯一最小相关编译任务并执行一次 Gradle 编译。编译失败时立即停止本次 Skill：只报告该次命令和首个可行动的失败原因，不再运行其他 Gradle 任务，也不继续检查、解析或修改任何设计与资源文件。
- 首轮取证完成后一次性读取 `设计解析.json`、`images.json`、`repeated-block-candidates.json` 和目标页面的项目模式；后续实现阶段复用这些结果，不为同一 ZIP 重复启动浏览器、重复解析或逐项探索相同证据。
- 计算 ZIP 完整 MD5；禁止根据文件名判断是否为同一设计。
- 以规范化的 ZIP 文件名和完整 MD5 前六位确定本次专属工作目录：`.code-lanhu-compose/<zip-stem>-<md5前6位>/`。目录内保存 `设计解析.json`、`images.json` 与 `runs/`；完整 MD5 必须写入 JSON 供身份校验。
- 安全解压到当前用户下载目录的 `<zip-stem>-<md5前6位>/`，解压前拒绝绝对路径、`..` 路径穿越和指向目录外的符号链接。
- 找到唯一有效的 `index.html`，并找到它实际引用的 `index.css`。存在多个候选页面根目录时，列出候选并让用户选择。
- 缺少入口、CSS 无法加载或资源路径越界时停止，不生成猜测代码。
- 创建或复用 `runs/` 公共证据目录前，必须先执行 `start-design-server` 与 `采集设计`，并确认本次专属工作目录中的 `设计解析.json` 存在、可解析且其 `sourceMd5` 与当前 ZIP 一致；缺失时不得只创建 `runs/` 并把截图当作完整缓存。

缓存目录和设计产物遵循 [缓存与设计解析](references/cache-and-parsing.md)。缓存只复用设计解析结果，不复用最终 Compose 代码。

### 2. 解析最终设计信息

- 以 `index.html` 的 DOM 父子关系建立结构树。
- 拆分每个 `class` 的 token：节点和资源命名优先使用非 `flex-row`/`flex-col` 的主类；这两个工具类不单独生成设计节点或 Compose 组件。若实际加载的 CSS 为工具类声明样式，仍须参与层叠，布局方向以 `getComputedStyle()` 最终值映射为 `Row` 或 `Column`。
- `inspect` 会写入 `repeated-block-candidates.json`：同一单位的宽、高、背景宽和背景高的总范围均不超过 `2`、且至少有两个共享父节点的兄弟项时，先按数据列表生成。候选的横竖方向只能由共享父节点的最终 DOM 布局决定；没有最终坐标证据时不得猜测方向或滚动性。
- 仅当完整设计缓存未命中时，才通过 `start-design-server` 启动本机服务并执行 `采集设计`；该命令使用本机 Chrome 等待字体和图片完成，读取 `getComputedStyle()`、`getBoundingClientRect()`、可见性、层叠顺序、变换和最终资源 URL。
- 同时处理继承、层叠覆盖、行内样式、flex 计算、绝对定位、伪元素、字体加载、遮挡和 `z-index`。
- 保留“声明来源”和“最终计算结果”：前者用于判断间距归属，后者用于确认最终边界和视觉验证。
- 将标准化设计 JSON 原子写入本次专属工作目录的 `设计解析.json`。相同完整 MD5 的 ZIP 可以更新覆盖该目录内的当前产物；不同完整 MD5 禁止写入同一目录。

详细字段和缓存命中条件见 [缓存与设计解析](references/cache-and-parsing.md)。

### 3. 生成 Compose 结构

- 先扫描当前项目的主题、已有 Composable、资源封装、命名方式、页面目录和屏幕适配方式；项目规范优先于通用写法。
- 使用 Material3；项目已有 Material3 包装组件时优先复用，不为页面额外引入项目不存在的依赖。
- 将纵向布局映射为 `Column`，横向布局映射为 `Row`，重叠或相对定位映射为 `Box`，重复且可滚动内容映射为 `LazyColumn` 或 `LazyRow`。
- 禁止因为浏览器提供了坐标就把整个页面实现为 `Box + offset`。
- 将重复颜色提取为 `Color` 常量，将重复间距提取为 `Dp` 常量；字号使用 `sp`，布局尺寸使用 `dp`。
- 设计稿中的 `1600×720` 等尺寸按设计像素（px/PS）处理，不是 dp；先读取实际 Compose 可用窗口的物理像素尺寸，再建立换算关系，禁止无条件假设 `1px = 1dp`。
- 如果需求是“铺满全屏”，虚拟设计画布从父容器左上角放置，分别计算 `scaleX = viewportWidthPx / designWidthPx / density` 和 `scaleY = viewportHeightPx / designHeightPx / density`；不要动态计算 `translationX`、`translationY`。使用 `graphicsLayer` 时只保留固定的 `TransformOrigin(0f, 0f)` 作为缩放基准，不把它作为适配参数。
- 用 `Modifier` 表达尺寸、间距、背景、裁剪、边框和阴影，并检查 Modifier 顺序是否改变视觉结果。
- Compose 生成后必须通过固定管线的布局安全检查；`padding(...)` 参数必须保持非负。CSS 的负 margin 或跨边界相对坐标不得翻译成负 padding，需用 `Modifier.offset` 或有足够空间的父级布局表达，并保留原有视觉位移语义。
- 将页面拆成小而内聚的私有 Composable；只生成设计能够证明的静态状态和用户明确提供的交互。
- 只修改目标页面及其必需的同作用域文件，保留用户已有修改，不做无关清理。

实现细节约束：

- 最底层存在背景图片时，必须直接使用 `ImageItem(parameter = ImageParameter(data = resId, modifier = modifier, contentScale = ContentScale.FillBounds))` 并让 `modifier` 为全屏布局；不得把根背景放进固定设计尺寸容器后再用局部缩放代替屏幕适配。
- 禁止定义或调用 `Modifier.offsetPx`、`Modifier.sizePx` 等自定义像素换算 Modifier；普通间距使用布局层级、`padding`/`Arrangement`，确有负位移语义时使用标准 `Modifier.offset`，尺寸使用 `width`、`height`、`size` 或 `fillMax*` 表达。
- 使用 `BoxWithConstraints` 的 Composable 必须导入 `android.annotation.SuppressLint`，并直接标注 `@SuppressLint("UnusedBoxWithConstraintsScope")`；根布局使用时标注根 Composable，局部使用时标注对应私有 Composable。
- 标题、标签、数值、单位和右侧图标组成的复合内容必须使用 `Row`/`Column` 的对齐关系或项目已有标签组件表达；禁止用互不关联的固定 `offset` 拼接，完成后检查文字是否裁剪、标签文字是否真实存在、数值和单位是否同一基线。
- 重复视觉单元与 `repeated-block-candidates.json` 命中的候选必须先建数据列表；共享父节点的最终方向决定 `Row`/`Column`，仅在 item 超出可视范围、页面支持滑动或用户要求滑动时使用对应 `Lazy*` 组件。禁止逐个硬编码同类 Composable 或用固定 `Row`/`Column` 堆叠可能超出视口的 item。复合卡片必须逐项保留设计中可见的图片、左右装饰、标签和操作入口，不得只保留中心文字或主数值。
布局映射和间距归属必须遵循 [Compose 映射规则](references/compose-mapping.md)。

### 4. 接入图片资源

- 从解析结果取得图片的真实相对路径和内容 Hash，禁止使用模糊文件名猜测资源。
- 运行 `python3 scripts/lanhu_pipeline.py assets --zip <zip> --compose <target-compose> --project-root <project> --apply`。编排器安全解压 ZIP、解析主节点类名或 ID、计算内容 Hash，并按 Hash 查询同一 ZIP 的 `.code-image` 清单；未命中时才调用 `$code-image --image --asset-name <节点名>`，命中时直接复用记录，不重复复制或比较目标文件。大模型只能读取最终 `images.json`，不能决定资源文件名或路径。
- 将每个 ZIP 源路径的结果（Hash、真实 `outputPath`、`outputName`）原子写入 `.code-lanhu-compose/<zip-stem>-<md5前6位>/images.json`；多个源路径可映射到同一资源。Compose 只能引用其中真实存在的 `outputName`；禁止根据 ZIP 文件名或旧 staging 文件猜测资源名。
- 蓝湖 HTML/CSS ZIP 通常不是 `mipmap*` 资源包，禁止把整个 ZIP 传给 `$code-image --zip`；必须先解压并逐图调用 `$code-image --image`。
- 只使用实际存在且映射成功的资源；禁止用文字、猜测圆角或临时 `Canvas` 替代已有设计切图。
- 图片匹配失败时列出设计节点、源路径、Hash 和候选文件，停止处理该资源并请求确认。

### 5. 编译、安装并打开目标页面

- 预检、资源导入、生成检查、编译、K80 安装和截图必须通过 `scripts/lanhu_pipeline.py` 的固定子命令执行；默认由 `run-fixed` 自动串联设计采集、资源导入和编译，模型决策只能通过契约化 JSON 记录。
- `preflight` 根据目标 Compose 路径和 Gradle 任务列表由 Python 自动确定模块的 Debug Kotlin 编译任务并写入状态；`compile` 只能复用该任务，不接受模型临时指定的 task。若存在多个 Debug variant 或无法识别，脚本立即暂停并请求用户明确选择。
- `compile` 只编译 Kotlin，不保证生成可安装 APK；每次编译成功后必须执行 `package-debug --apk <apk>`。该命令从同一个 `preflightTask` 自动推导对应的 `assemble<Variant>`，并记录 Compose Hash 与 APK 路径；`install-k80` 会拒绝旧 APK、路径不一致或未登记的产物，避免安装 stale APK 后重复截图。
- 每轮修正只重新运行同一个由 Python 确定的最小相关编译任务，禁止把模糊的 `compileDebugKotlin` 当成所有项目的固定命令。
- 生成后的编译失败先定位首个可行动原因：若错误只涉及本次修改的 Compose 文件或新导入资源，且可由诊断直接确定最小修复（如作用域接收者、导入、类型、资源 ID），自动修复并重跑同一编译任务，最多三轮。预检失败、用户既有文件错误、ZIP/资源映射错误、构建环境错误或需业务决策的错误仍须立即停止并报告。
- 编译成功后安装到明确的模拟器或设备，固定分辨率、density、字体缩放、语言、主题和测试数据。
- 按 deeplink、目标 Activity、debug 路由、稳定导航步骤的顺序打开页面。
- 截图前通过当前 Activity、UI 结构或页面标识确认目标页面已经显示，并确认启动页、启动图标、空白加载态和过渡动画已经消失；只启动首页或截取启动画面不算完成。
- 编译、安装、页面打开或测试数据准备失败时保留日志并停止视觉修正。

### 6. 截图、对比和最多三轮修正

- `采集设计` 的完整缓存以 ZIP 完整 MD5、设计解析版本和 `runs/设计截图.png` 共同校验；命中时不得启动服务或浏览器。未命中时才执行 `start-design-server → 采集设计 → screenshot-design`，并在首次采集后固定复用 `runs/设计截图.png`。`screenshot-design` 无论登记成功或失败都会回收本次静态服务。去掉蓝湖预览外壳的缩小变换，但保留设计元素自身的变换。
- `runs/` 禁止创建时间戳子目录。App 截图固定按顺序保存为 `应用截图.png`、`应用截图_1.png`、`应用截图_2.png`……，不得覆盖已有证据。
- 截图对比前保留原始 App 截图，先按 [视觉验证闭环](references/visual-validation.md) 归一化有效内容区域、系统栏、颜色空间和画布尺寸；宽高比不一致时禁止直接调用 `compare_images.py` 或用 `--aspect-tolerance` 强行放行。
- K80 截图完成并生成归一化截图后，必须执行 `python3 scripts/lanhu_pipeline.py compare-screenshots --zip <zip> --project-root <project> --app <归一化截图>`；省略 `--app` 仅适用于原始截图与设计稿宽高比一致的情况。该阶段只调用 `$code-image` 的独立 `compare_images.py`，在 `runs/` 生成 `diff.json`、`diff-mask.png`、`diff-heatmap.png` 和 `diff-overlay.png`，并把本次 ZIP 的 `sourceMd5` 写入报告。也可以省略 `mark-diff` 的 `--report`，由它自动触发同一对比阶段。
- 模型必须读取 `diff.json` 的指标、区域和证据图后，才决定 `repair`、`pass` 或 `stop`；Python 只生成对比证据，不自动修改 Compose，修复仍通过模型的契约化补丁完成。
- 逐项比较整体布局、元素边界、文本基线、字号、行高、字距、间距、颜色、圆角、阴影、图片裁剪和遮挡关系。
- 初次生成后最多执行三轮“修正 → 编译 → 打包 → 安装/运行 → 截图 → 对比”。如果连续一次修正的关键指标和证据图没有改善，立即 `stop`，不要消耗剩余轮次；达到目标或遇到外部阻塞时同样提前停止。
- 每轮只修复有截图或布局数据支持的差异；禁止为了追求像素一致破坏项目公共组件或扩大修改范围。

截图命令、证据目录和停止条件见 [视觉验证闭环](references/visual-validation.md)。

## 完成标准

完成时报告：

- ZIP MD5、缓存命中状态和解析产物路径。
- 生成或修改的 Compose 文件、资源文件和关键项目适配决策。
- 实际执行的编译、安装和页面打开方式。
- 每轮截图、差异结论、已修正项和剩余差异。
- 最终停止原因；如果未完成，明确区分代码问题、设计信息不足和环境阻塞。

## 经验沉淀

业务执行并验证后调用 `$skill-common` 复盘原始证据。只有稳定复现、能被编译/截图/布局数据验证，或用户明确要求固化的通用经验，才允许最小化更新本 Skill 或一层 reference。项目专属数值、单次偶发错误和未经验证的猜测不得写入规则；禁止追加按日期增长的事故日志。
