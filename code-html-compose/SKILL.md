---
name: "code-html-compose"
description: "将蓝湖等工具导出的 HTML/CSS/图片设计包转换为具备页面结构、状态交互和可量化验收能力的 Jetpack Compose 高保真基线；用于元素缺失、文字裁切、布局偏移、列表/弹窗还原或需要模拟器验证的任务。"
---

# HTML → Jetpack Compose 高保真转换

所有面向用户的沟通、说明和代码注释使用中文。

## 适用范围

- 输入为含 `index.html`、CSS 和 `img/` 的 HTML 设计压缩包。
- 需要以像素、元素边界和模拟器截图验证 Compose 还原结果。
- 已有绝对定位基线，需要在验收通过后再安全重构为 `Row`、`Column` 或列表。
- 页面同时包含固定视觉骨架、重复列表、弹窗、选中态、滚动或页面级导航逻辑。

不适用于只有截图、没有 HTML/CSS/图片资源的任务；先要求用户提供完整设计包。

## 页面角色与换算基准

- 参考清单中的 `primary-page` 才是主页面视觉真源；当前项目主页面验收基准为 `1334px × 750px`。
- `vertical-list-state` 只描述中间纵向列表的内容/滚动状态，`popup-state` 只描述右上角套系弹窗和遮挡关系；状态片段可以有不同的 CSS 高度，不能被误当成新的整页布局，也不能替换主页面。
- 先判定设计包的页面角色：若存在独立且有明确边界的居中面板，外层有全屏遮罩，遮罩下内容只是上下文，则按 Dialog 处理；只生成 Dialog 内部节点，背景上下文不生成、不参与结构验收，遮罩仅保留为 Dialog 宿主行为或统一底色。只有明确要求恢复底层页面时才提取背景。
- Android 目标视图固定为 `375dp × 667dp`；HTML 按 2 倍设计稿处理，固定使用 `DP_PER_PX=0.5`（`1dp=2px`）。
- 数值对应关系固定为：HTML `1334px` ↔ Android `667dp`，HTML `750px` ↔ Android `375dp`；页面方向按目标 Android 页面实际方向对齐，禁止横纵分别拉伸或裁切。
- 主页面不是 `1334px × 750px` 时报告尺寸不匹配并停止；状态片段只做局部语义提取和行为校验，不参与主页面尺寸判定。

## 固定流程

1. 在目标 Android 项目根目录确认工作区改动，并先根据 `COMPOSE_ACTIVITY` 定位当前页面实际承载的 Activity（或 Activity-alias）。默认要求它有自己的 `MAIN` + `LAUNCHER`；已有页面 Activity 不是 Launcher 时显式使用 `COMPOSE_ACTIVITY_MODE=existing`，只允许复用该页面和真实导航入口，禁止创建 Activity、补写 `MAIN`/`LAUNCHER` 或用其他页面绕过检查。横向设计稿通过前，只能在已找到的 Activity 声明上写入或更新 `android:screenOrientation="landscape"`。
2. 安装脚本依赖：`npm ci --prefix <本技能>/scripts`。
3. 配置 `PROJECT_ROOT`、Compose 目标目录、包名、`R`、图片组件导入、参考角色清单和现有资源映射；完整变量见 [配置参考](references/configuration.md)。
4. 先读取目标 Kotlin、调用方、状态数据和 `.code-image` 资源元数据，并搜索项目中同类生产级 Compose 页面；记录实际宿主（普通页、Dialog 或 Popup）、状态 owner/callback、组件选型和资源/生命周期约定。生产文件只作为决策证据，不复制业务布局，再用 `node <本技能>/scripts/run.js <主页面设计包.zip>` 执行主页面基线；滚动/弹窗 ZIP 只通过参考清单关联，不能单独生成整页 Kotlin。
5. 以 `<PROJECT_ROOT>/.code-html-compose/` 内的 `original.png` 和验收报告为真源；它们是运行产物，不得提交或复制到技能仓库。

### Launcher Activity 与屏幕方向前置检查

- 这里检查的是 Launcher 的 `intent-filter` 标签，不是 `android:launchMode` 属性。
- 总入口和直接的 Compose 生成/验收入口都会读取 `COMPOSE_ACTIVITY`（验收命令行参数优先）并定位该 Activity；默认只认它自己的同一个 `intent-filter` 中同时声明 `android.intent.action.MAIN` 和 `android.intent.category.LAUNCHER`。`COMPOSE_ACTIVITY_MODE=existing` 可显式允许已有非 Launcher 页面，但只改变检查方式，不改变 Android 导出安全限制，也不自动提供启动路径。
- 目标 Activity 未配置或未找到时，输出明确提示并停止；禁止用项目中其他 Launcher Activity 替代、创建 Activity 或补写 `MAIN`/`LAUNCHER`。
- 横向设计稿在生成、编译、安装或启动前，更新该目标 Activity 的源 `AndroidManifest.xml` 声明，确保存在 `android:screenOrientation="landscape"`；如果已有其他方向值，替换该值。不得修改其他 Activity。技能不得通过 ADB 修改模拟器的 `wm size`、`wm density`、`policy_control`、`accelerometer_rotation` 或 `user_rotation`；需要横屏时只提示用户将模拟器旋转为横向。
- `build/`、`.gradle/` 和其他生成目录不参与发现，避免用过期合并 Manifest 掩盖项目源配置缺失。

## 必须遵守的判断

- `original.png` 是最终视觉真源；`normalized.png` 只用于诊断，不能覆盖原始截图。
- HTML 规范化每个确定性策略最多执行一次。未达标时保留最佳报告，禁止无限重试。
- Compose 先生成逐元素高保真基线；仅当结构通过率不少于 95%、局部抽查通过率不少于 80% 后，才能局部语义化重构。
- 先识别复合列表项：当 3 个及以上视觉条目沿横向或纵向共享相同的外框卡片尺寸（允许约 1dp/1–2px 栅格误差）、对齐轴、间距和字段槽位时，必须按列表建模；卡片内部标题、按钮、锁图标或高亮等状态差异不否定列表语义，连续的 `01`、`02`、`03` 等编号是强信号。若最后一个条目只因落在设计稿/宿主视口边界而显示不全，必须仍作为一个使用完整卡片尺寸的 item 数据对象加入 `listOf`，由列表宿主视口按设计稿可见宽度自然裁切；禁止另造页面级半截组件，也禁止把半截可见宽度写入 item 数据。把字段按条目边界聚合为数据类、`listOf` 数据和 item Composable，禁止生成 `Number01`、`Number02`、`Number03` 这类复制粘贴的页面级组件。
- 强列表证据下，基线验收通过后必须完成数据驱动的 `Column`、`LazyColumn`、`LazyRow` 或网格重构；容器类型由设计图的排列方向和是否存在可视视口决定。横向同态条目且尾项只在边界露出时，必须用 `LazyRow` 的可滚动视口承载完整 item，由容器自然裁切，不能把尾项做成半截组件。重构后仍须保留每个条目的可观测边界，并重新执行结构和局部像素验收。
- 固定骨架和可重复入口必须先建立稳定锚点：返回、左侧导航、标题、目标栏等页面级节点不得成为筛选列表的子项；页面级区域优先用 `ConstraintLayout` 和独立 `Guideline` 约束。需要适配手机和平板的外层面板，按设计稿比例使用 parent 的 percentage `Guideline` 或 `Dimension.fillToConstraints`，不要用固定 `size` 充当外层适配策略；内部固定 dp 仅用于已验收的资产和微调。重复入口先建数据列表并在已锚定的 `Row`/`Column` 内用 `forEach`/`forEachIndexed` 和固定 `Arrangement.spacedBy` 排列；只有设计要求独立起点、跨区域对齐或叠层时，才为每个入口建立独立 `Guideline`。选中态只能改变入口状态，不能用前一个条目的测量结果、内容高度或自适应间距推导后续位置；禁止用页面级 `offset` 代替锚点，仅允许经过验收的 item 内微小光学修正；标题等文本的 `Arrangement`/`align` 必须与其设计区域的起点一致，左侧标题不得默认居中。
- 使用 inline `ConstraintLayout` DSL 时，页面级 `Guideline` 及其他外层 helper 必须在同一个外层内容块中按固定顺序统一创建，并在调用子 Composable 前完成；子 Composable 只能接收并使用 `HorizontalAnchor`/`VerticalAnchor` 等约束引用，禁止在 `ConstraintLayoutScope` 子函数中创建外层 Guideline。helper ID 按执行顺序生成，筛选、弹窗或条件列表引起的重组可能改变分散创建的顺序，导致约束引用错位。
- 生成的每个命名 Composable、辅助函数和自定义定位方法上方必须有中文 KDoc；参数较多时补充 `@param`，不能只写文件级说明代替方法说明。
- 像素级验收固定使用 `semantic.designW=1334`、`semantic.designH=750`；尺寸校验失败时立即停止，禁止通过 `DESIGN_WIDTH`、`DESIGN_HEIGHT` 或其他方式静默适配。
- 生成器固定按 `DP_PER_PX=0.5` 把 HTML 坐标和尺寸换算为 Android dp；不得修改源坐标或用 `graphicsLayer` 整页缩放掩盖基线误差。
- 运行时尺寸适配先检查目标 Activity 的真实继承链和项目已有的 AutoSize；已完成全局适配时直接使用项目惯用的 `dp`/`sp`（或既有适配代理），不要再引入 `BoxWithConstraints`、局部 Density 或整页缩放。Popup 的 `PopupPositionProvider` 为把 `Dp` 转成窗口像素而使用 `LocalDensity` 属于定位例外，不是尺寸适配。只有项目没有全局适配时，才按窗口宽高比例承载固定逻辑画布，并用设计背景色或背景图填充剩余空间，不能横纵分别拉伸或裁切。
- 横向设计稿验收前必须确保目标 Activity 的静态方向配置为 `landscape`，并要求模拟器当前已经横向显示；截图必须保持设备原始方向，禁止通过 ADB 修改窗口分辨率/density、锁定或设置旋转、使用 `rotate90` 或其他图像变换补偿方向。截图仍为竖屏时直接报错并停止验收；不得为了适配设计稿而覆盖模拟器分辨率，边界换算应使用当前横屏截图的实际尺寸。
- 只有验收基线需要为可观测视觉元素设置 `testTag("e<domIndex>")` 并记录被覆盖层；集成到没有 UI 自动化或无障碍依赖的业务布局时，移除生成用 `testTag` 和 `testTagsAsResourceId`，不要把验收标记当成布局的一部分。
- 只生成设计图中可见且有视觉证据的节点，不能凭名称补造箭头、指示器或装饰图。

## 行为型页面规则

- 生成前必须画出状态模型：页面数据、当前套系、弹窗开关、当前列表项、滚动容器和点击后的变化；HTML/CSS 只负责外观，不能代替 Compose 状态。
- 固定骨架、纵向套系列表、横向书卡和右上角弹窗必须拆成有职责的 Composable。优先复用项目已有的 Dialog 宿主（如 `ComposeDialog`）和锚点 `Popup`/`PopupPositionProvider`，让宿主负责遮罩、关闭和窗口定位；弹窗是页面状态，不是把弹窗 ZIP 追加到主页面坐标树；列表是数据 + item renderer，不是重复复制卡片。包含播放器或其他需释放资源的内容时，用与可见状态绑定的 `DisposableEffect` 在关闭/离开组合时清理资源。
- 优先复用现有页面的状态字段、回调和资源名；不凭设计文字臆造 API、导航、业务数据或图片。缺少行为证据时保留当前代码契约，并在报告中标注未验证行为。
- 弹窗内按顺序排列的标题、说明、提示、描述和按钮必须使用 `Column`/列表容器；动态高度内容用 `verticalScroll` 或合适的列表承载，避免用 `Box` 的多层 `padding(top=...)` 定位造成重叠。复合项内部有明确方向时使用 `Row`/`Column`/`weight` 排列，不用 `Box` 叠加上下左右 padding 模拟方向布局；`Box` 只用于单个复合项的背景、叠层或点击容器。不要把 `LazyColumn` 嵌入 `DropdownMenu` 这类 intrinsic measurement 容器。选中态、关闭、箭头旋转和筛选结果必须由同一状态源驱动。
- 套系选择只允许替换或过滤列表数据，必须保留根页面背景、返回、左侧导航、标题、目标栏和触发器；筛选状态与滚动偏移是两个独立变量。每个套系 item 使用完整且一致的外框高度，初始未滚动时也不得按状态片段或可见半截反推高度；尾项半截只能由列表 viewport 自然裁切。
- 行为验收至少覆盖：默认主页面、打开弹窗、选择一个套系、弹窗关闭后的筛选结果、纵向列表滚动/当前项定位；验收基线可用稳定 `testTag` 观测宏观区域，正式业务布局则使用真实文本、点击回调和列表状态核对，不要求保留生成用标签。
- 涉及筛选、Tab、套系或弹窗选择的页面，切换前后必须核对返回、侧栏、标题和目标栏等固定骨架节点的 bounds；固定节点发生位置变化时，先检查外层 helper 的创建归属/顺序和状态是否存在二次同步，再考虑尺寸或 offset 调整。

## 资源

- `scripts/`：DOM 解析、HTML 对比、Compose 基线生成、模拟器结构与局部像素校验及测试。
- `references/configuration.md`：运行命令、环境变量和产物边界。
- `references/workflow.md`：工作流细则与视觉还原约束。
- 图片资源默认按完整 `originalHash` 优先复用目标模块 `.code-image/image.json` 的实际输出；需要复用时先用 `$code-image` 导入并 `--apply`，本 Skill 只读取清单，不重新导入或改名。文件名不参与匹配；跨 Skill 只依赖 `originalHash`、`outputPath` 和 `outputName`，不依赖 `identity`、`composeFile` 或 `namingVersion`。无可用清单或 Hash 未命中时才使用设计包的 `img`/`image` 图片，禁止跨模块或复用不存在、内容 Hash 不一致的输出文件。若导出图片只是纯色背景、圆角或边缘噪声，且 CSS/像素证据可确定其样式，优先用 `background`/`clip(RoundedCornerShape)` 代码实现并删除冗余图片组件。

运行产生的 `run-*`、`compose-run-*`、截图、JSON 报告、图片资源、`node_modules/` 均只允许位于目标项目工作目录，不得发布到 GitHub。
