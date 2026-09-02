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
4. 先读取目标 Kotlin、调用方、状态数据和 `.code-image` 资源元数据，再用 `node <本技能>/scripts/run.js <主页面设计包.zip>` 执行主页面基线；滚动/弹窗 ZIP 只通过参考清单关联，不能单独生成整页 Kotlin。
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
- 强列表证据下，基线验收通过后必须完成数据驱动的 `Column`、`LazyColumn`、`LazyRow` 或网格重构；容器类型由设计图的排列方向和是否存在可视视口决定。重构后仍须保留每个条目的可观测边界，并重新执行结构和局部像素验收。
- 固定骨架和可重复入口必须先建立稳定锚点：返回、左侧导航、标题、目标栏等页面级节点不得成为筛选列表的子项；3 个及以上同类入口应先创建数据列表、布局引用和每个入口独立的 `Guideline`（尤其是垂直起点），再用 `forEach`/`forEachIndexed` 调用同一个 item Composable。选中态只能改变入口状态，不能用前一个条目的测量结果、内容高度或自适应间距推导后续位置；标题等文本的 `Arrangement`/`align` 必须与其设计区域的起点一致，左侧标题不得默认居中。
- 生成的每个命名 Composable、辅助函数和自定义定位方法上方必须有中文 KDoc；参数较多时补充 `@param`，不能只写文件级说明代替方法说明。
- 像素级验收固定使用 `semantic.designW=1334`、`semantic.designH=750`；尺寸校验失败时立即停止，禁止通过 `DESIGN_WIDTH`、`DESIGN_HEIGHT` 或其他方式静默适配。
- 生成器固定按 `DP_PER_PX=0.5` 把 HTML 坐标和尺寸换算为 Android dp；不得修改源坐标或用 `graphicsLayer` 整页缩放掩盖基线误差。
- 运行时页面按窗口宽高的较小比例设置局部 `Density`，居中完整显示固定逻辑画布；不同宽高比产生的剩余空间必须由设计背景色或背景图铺满，不能暴露测试容器底色；禁止横纵分别拉伸或裁切设计内容。
- 横向设计稿验收前必须确保目标 Activity 的静态方向配置为 `landscape`，并要求模拟器当前已经横向显示；截图必须保持设备原始方向，禁止通过 ADB 修改窗口分辨率/density、锁定或设置旋转、使用 `rotate90` 或其他图像变换补偿方向。截图仍为竖屏时直接报错并停止验收；不得为了适配设计稿而覆盖模拟器分辨率，边界换算应使用当前横屏截图的实际尺寸。
- 每个可观测视觉元素须有 `testTag("e<domIndex>")`；完整被覆盖的层须写入可观测性报告，不能静默跳过。
- 只生成设计图中可见且有视觉证据的节点，不能凭名称补造箭头、指示器或装饰图。

## 行为型页面规则

- 生成前必须画出状态模型：页面数据、当前套系、弹窗开关、当前列表项、滚动容器和点击后的变化；HTML/CSS 只负责外观，不能代替 Compose 状态。
- 固定骨架、纵向套系列表、横向书卡和右上角弹窗必须拆成有职责的 Composable。弹窗是页面状态，不是把弹窗 ZIP 追加到主页面坐标树；列表是数据 + item renderer，不是重复复制卡片。
- 优先复用现有页面的状态字段、回调和资源名；不凭设计文字臆造 API、导航、业务数据或图片。缺少行为证据时保留当前代码契约，并在报告中标注未验证行为。
- 弹窗中的项目少时直接用 `Column`，项目多时使用弹窗内部的滚动容器；不要把 `LazyColumn` 嵌入 `DropdownMenu` 这类 intrinsic measurement 容器。选中态、关闭、箭头旋转和筛选结果必须由同一状态源驱动。
- 套系选择只允许替换或过滤列表数据，必须保留根页面背景、返回、左侧导航、标题、目标栏和触发器；筛选状态与滚动偏移是两个独立变量。每个套系 item 使用完整且一致的外框高度，初始未滚动时也不得按状态片段或可见半截反推高度；尾项半截只能由列表 viewport 自然裁切。
- 行为验收至少覆盖：默认主页面、打开弹窗、选择一个套系、弹窗关闭后的筛选结果、纵向列表滚动/当前项定位；每个宏观区域都要有稳定 `testTag`，不能只给静态 DOM 节点贴标签。

## 资源

- `scripts/`：DOM 解析、HTML 对比、Compose 基线生成、模拟器结构与局部像素校验及测试。
- `references/configuration.md`：运行命令、环境变量和产物边界。
- `references/workflow.md`：工作流细则与视觉还原约束。

运行产生的 `run-*`、`compose-run-*`、截图、JSON 报告、图片资源、`node_modules/` 均只允许位于目标项目工作目录，不得发布到 GitHub。
