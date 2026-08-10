---
name: code-lanhu-compose
description: Use when 用户提供或准备提供蓝湖导出的 HTML/CSS ZIP，需要在 Android 项目中生成或还原 Jetpack Compose 页面，并进行图片资源处理、编译运行或设计稿截图对比。
---

# code-lanhu-compose

把蓝湖导出的 HTML/CSS ZIP 转换为符合当前 Android 项目规范的 Compose 页面，并用设计稿与 App 截图完成可追溯的视觉修正。HTML DOM、资源引用、浏览器最终计算结果和 Compose 初稿均由 Python 固定脚本处理；模型只负责项目适配、异常决策和有证据的视觉修正。

## 职责与例外

- 遵循 `$skill-common` 基础规范。每次调用本 Skill 时，先执行 `"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"`；检测或发布成功后再继续，失败时立即停止。
- 只负责蓝湖 ZIP 的设计解析、Compose 生成、图片接入和视觉验证闭环。
- 不调用、不继承旧 `$code-compose`，也不读取它的规则或缓存。
- 图片接入、内容 Hash、资源清单、完整 DOM 解析、浏览器最终布局采集和 Compose 初稿生成均由 Python 固定脚本全权执行；图片接入时再调用 `$code-image` 这个确定性子工具。大模型不得参与 Hash、路径解析、资源命名、DOM/class 层级推断或 Compose 首稿生成，也不得修改原始 JSON 证据。
- 模拟器验证能力可用时调用 `test-android-apps:android-emulator-qa`；不可用时才执行本 Skill 规定的显式 ADB 流程。
- 以 `scripts/lanhu_pipeline.py run-fixed` 作为默认固定入口；它自动完成完整 DOM 存储、设计服务/浏览器采集、资源 Hash/导入、Compose 生成、Gradle 任务发现和编译。浏览器、资源、代码生成和 Gradle 命令均由 Python 决定并执行；大模型不得逐项调用或替换这些步骤。
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
- 首轮取证完成后一次性读取 `dom.json`、`设计解析.json`、`images.json` 和目标页面的项目模式；后续实现阶段复用这些结果，不为同一 ZIP 重复启动浏览器、重复解析或逐项探索相同证据。
- 计算 ZIP 完整 MD5；禁止根据文件名判断是否为同一设计。
- 以规范化的 ZIP 文件名和完整 MD5 前六位确定本次专属工作目录：`.code-lanhu-compose/<zip-stem>-<md5前6位>/`。目录内保存 `设计解析.json`、`images.json` 与 `runs/`；完整 MD5 必须写入 JSON 供身份校验。
- 安全解压到当前用户下载目录的 `<zip-stem>-<md5前6位>/`，解压前拒绝绝对路径、`..` 路径穿越和指向目录外的符号链接。
- 找到唯一有效的 `index.html`，并找到它实际引用的 `index.css`。存在多个候选页面根目录时，列出候选并让用户选择。
- 缺少入口、CSS 无法加载或资源路径越界时停止，不生成猜测代码。
- 创建或复用 `runs/` 公共证据目录前，必须先执行 `start-design-server` 与 `采集设计`，并确认本次专属工作目录中的 `设计解析.json` 存在、可解析且其 `sourceMd5` 与当前 ZIP 一致；缺失时不得只创建 `runs/` 并把截图当作完整缓存。

缓存目录和设计产物遵循 [缓存与设计解析](references/cache-and-parsing.md)。缓存只复用设计解析结果，不复用最终 Compose 代码。

### 2. 固化 DOM 和最终设计信息

- 先运行 `parse-dom` 或让 `inspect` 自动运行 `scripts/parse_html_dom.py`，解析整个 `index.html`（包括 `head`、`body`、元素属性、文本、注释、父子关系和本地资源引用），原子写入 `dom.json`。`class` 只作为原始属性保存，不作为模型推断页面结构的输入。
- 浏览器采集只负责把 `getComputedStyle()`、`getBoundingClientRect()`、可见性、字体、层叠、变换和最终资源 URL 按 `nodeId` 写入 `设计解析.json`；不得以 class 选择器重新建立结构树。
- 仅当完整设计缓存未命中时，才通过 `start-design-server` 启动本机服务并执行 `采集设计`；该命令使用本机 Chrome 等待字体和图片完成，读取 `getComputedStyle()`、`getBoundingClientRect()`、可见性、层叠顺序、变换和最终资源 URL。
- 同时处理继承、层叠覆盖、行内样式、flex 计算、绝对定位、伪元素、字体加载、遮挡和 `z-index`。
- 保留“声明来源”和“最终计算结果”：前者用于判断间距归属，后者用于确认最终边界和视觉验证。
- 将标准化设计 JSON 原子写入本次专属工作目录的 `设计解析.json`。相同完整 MD5 的 ZIP 可以更新覆盖该目录内的当前产物；不同完整 MD5 禁止写入同一目录。

详细字段和缓存命中条件见 [缓存与设计解析](references/cache-and-parsing.md)；DOM IR 到 Compose 的固定映射见 [DOM 到 Compose 代码生成](references/dom-to-compose.md)。

### 3. 由 DOM IR 生成 Compose

- `run-fixed` 自动调用 `scripts/generate_compose.py`，输入固定为 `dom.json`、`设计解析.json`、`images.json` 和目标文件的 package 声明；生成结果原子写入目标 Compose 文件，再由 Python 执行 `padding` 安全检查。
- 生成器只按存储的 DOM 父子关系、标签、文本、资源映射和浏览器计算样式选择 `Column`、`Row`、`Box`、`Text`、`Image`；不得让模型重写首稿或根据 class 名猜测组件。
- 生成失败、资源未映射、包名缺失或输入证据冲突时立即暂停并写入用户输入状态；模型只可处理项目已有组件/交互的适配决策，不可绕过 IR 直接手写结构。
- 需要重新生成时运行 `python3 scripts/lanhu_pipeline.py generate-compose --zip <zip> --project-root <project> --compose <Compose.kt>`；不要再使用“等待模型修改 Compose”的旧流程。
- 只修改目标页面及其必需的同作用域文件，保留用户已有修改，不做无关清理。

实现细节约束：

- 生成器根据 `images.json` 的真实映射生成 `Image`；若项目适配器已声明使用 `ImageItem`，只能把同一 `nodeId` 的资源调用替换为项目封装，并保持 `ContentScale.FillBounds` 和全屏 modifier 的证据语义，不得另行猜测背景资源。
- 禁止定义或调用 `Modifier.offsetPx`、`Modifier.sizePx` 等自定义像素换算 Modifier；普通间距使用布局层级、`padding`/`Arrangement`，确有负位移语义时使用标准 `Modifier.offset`，尺寸使用 `width`、`height`、`size` 或 `fillMax*` 表达。
- 使用 `BoxWithConstraints` 的 Composable 必须导入 `android.annotation.SuppressLint`，并直接标注 `@SuppressLint("UnusedBoxWithConstraintsScope")`；根布局使用时标注根 Composable，局部使用时标注对应私有 Composable。
- 标题、标签、数值、单位和右侧图标组成的复合内容必须使用 `Row`/`Column` 的对齐关系或项目已有标签组件表达；禁止用互不关联的固定 `offset` 拼接，完成后检查文字是否裁剪、标签文字是否真实存在、数值和单位是否同一基线。
- 重复视觉单元必须依据完整 DOM IR 中的真实兄弟节点生成数据列表；共享父节点的最终方向决定 `Row`/`Column`，仅在 item 超出可视范围、页面支持滑动或用户要求滑动时使用对应 `Lazy*` 组件。禁止逐个硬编码同类 Composable 或用固定 `Row`/`Column` 堆叠可能超出视口的 item。复合卡片必须逐项保留设计中可见的图片、左右装饰、标签和操作入口，不得只保留中心文字或主数值。
布局映射和间距归属必须遵循 [Compose 映射规则](references/compose-mapping.md)。

### 4. 接入图片资源

- 从解析结果取得图片的真实相对路径和内容 Hash，禁止使用模糊文件名猜测资源。
- 运行 `python3 scripts/lanhu_pipeline.py assets --zip <zip> --compose <target-compose> --project-root <project> --apply`。编排器安全解压 ZIP、解析主节点类名或 ID、计算内容 Hash，并按 Hash 查询同一 ZIP 的 `.code-image` 清单；未命中时才调用 `$code-image --image --asset-name <节点名>`，命中时直接复用记录，不重复复制或比较目标文件。大模型只能读取最终 `images.json`，不能决定资源文件名或路径。
- 将每个 ZIP 源路径的结果（Hash、真实 `outputPath`、`outputName`）原子写入 `.code-lanhu-compose/<zip-stem>-<md5前6位>/images.json`；多个源路径可映射到同一资源。Compose 只能引用其中真实存在的 `outputName`；禁止根据 ZIP 文件名或旧 staging 文件猜测资源名。
- 蓝湖 HTML/CSS ZIP 通常不是 `mipmap*` 资源包，禁止把整个 ZIP 传给 `$code-image --zip`；必须先解压并逐图调用 `$code-image --image`。
- 只使用实际存在且映射成功的资源；禁止用文字、猜测圆角或临时 `Canvas` 替代已有设计切图。
- 图片匹配失败时列出设计节点、源路径、Hash 和候选文件，停止处理该资源并请求确认。

### 5. 编译、安装并打开目标页面

- 预检、资源导入、DOM 解析、Compose 生成检查、编译、K80 安装和截图必须通过 `scripts/lanhu_pipeline.py` 的固定子命令执行；默认由 `run-fixed` 自动串联设计采集、资源导入、代码生成和编译，模型决策只能通过契约化 JSON 记录。
- `preflight` 根据目标 Compose 路径和 Gradle 任务列表由 Python 自动确定模块的 Debug Kotlin 编译任务并写入状态；`compile` 只能复用该任务，不接受模型临时指定的 task。若存在多个 Debug variant 或无法识别，脚本立即暂停并请求用户明确选择。
- `compile` 只编译 Kotlin，不保证生成可安装 APK；每次编译成功后必须执行 `package-debug --apk <apk>`。该命令从同一个 `preflightTask` 自动推导对应的 `assemble<Variant>`，并记录 Compose Hash 与 APK 路径；`install-k80` 会拒绝旧 APK、路径不一致或未登记的产物，避免安装 stale APK 后重复截图。
- 每轮修正只重新运行同一个由 Python 确定的最小相关编译任务，禁止把模糊的 `compileDebugKotlin` 当成所有项目的固定命令。
- 生成后的编译失败先定位首个可行动原因：若错误只涉及固定生成模板或新导入资源，且可由诊断直接确定最小修复（如作用域接收者、导入、类型、资源 ID），由脚本修正模板或重新生成并重跑同一编译任务，最多三轮。预检失败、用户既有文件错误、ZIP/资源映射错误、构建环境错误或需业务决策的错误仍须立即停止并报告；模型不得直接猜测布局来绕过生成器。
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
- `dom.json` 的节点/资源数量、`设计解析.json` 和生成器输出记录；明确首稿由 Python 根据 IR 生成。
- 生成或修改的 Compose 文件、资源文件和关键项目适配决策。
- 实际执行的编译、安装和页面打开方式。
- 每轮截图、差异结论、已修正项和剩余差异。
- 最终停止原因；如果未完成，明确区分代码问题、设计信息不足和环境阻塞。

## 经验沉淀

业务执行并验证后调用 `$skill-common` 复盘原始证据。只有稳定复现、能被编译/截图/布局数据验证，或用户明确要求固化的通用经验，才允许最小化更新本 Skill 或一层 reference。项目专属数值、单次偶发错误和未经验证的猜测不得写入规则；禁止追加按日期增长的事故日志。
