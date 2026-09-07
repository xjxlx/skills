# 生产级 Compose 页面适配规范

本规范只用于 HTML/设计基线通过后的项目级语义适配和维护，不替代 bounds-first 首稿，也不把某个业务特殊列表容器的实现方式泛化为通用规则。

## 页面分层与状态边界

- 页面入口 Composable 负责获取 `ViewModel`、用稳定业务输入作为 `LaunchedEffect` key 触发请求、收集 Flow，并在必需数据非空后把数据传给内容 Composable；不要在纯视觉区域函数中发起请求或持有页面级副作用。
- 内容 Composable 负责页面状态和派生数据：用 `remember(源数据)` 缓存选项/派生集合，用 `remember(源数据)` 重置与源数据绑定的选中状态，用无 key 的 `remember` 保存独立的弹窗开关；筛选结果用完整依赖作为 key 重新计算。
- 动画、选中态、弹窗开关和筛选结果必须由同一个状态源驱动。纯数据转换（例如选项构建、过滤）抽成无 UI 的辅助函数，便于单测和保持 Composable 简洁。

## 页面级 ConstraintLayout 产出

- 内容根使用项目既有尺寸适配和 `ConstraintLayout`；在同一个外层内容块顶部按固定顺序创建页面级 `createRefs()`、公共 Guideline 和其他 helper。`createRefs()` 解构名使用语义名并以 `Ref` 结尾：`titleRef`、`selectorRef`、`todayRef`；不要使用 `ref1`、`line1` 等序号名。
- 公共 Guideline 先创建；区域专属 Guideline 紧挨对应区域调用创建。区域调用前用中文注释标明归属，保证重组、筛选和弹窗状态变化不会改变 helper 的创建顺序。
- 需要外层锚点的区域用 `ConstraintLayoutScope` 扩展 Composable，并接收外层传入的 `ConstrainedLayoutReference` 与锚点；表示布局引用的参数以 `Res` 结尾，方向锚点使用 `Start`、`End`、`Top`、`Bottom` 后缀。区域函数不得自行创建外层 Guideline。
- 外层约束负责页面区域的边界：使用 `Dimension.value` 表达已验收的固定区域尺寸，使用 `Dimension.fillToConstraints` 表达由两侧/上下锚点决定的尺寸。子内容沿父约束方向使用 `fillMaxWidth`/`fillMaxHeight`/`fillMaxSize`，不要重复写同一方向的固定尺寸。

## 区域内部布局与 Modifier

- 有明确方向的连续内容使用 `Row`、`Column`、`LazyRow` 或 `LazyColumn`；`Box` 只用于背景、叠层、遮罩、对齐或单个复合点击容器。均分列使用 `weight`，弹性空白使用 `Spacer(weight = 1f)`，图片/卡片比例使用 `aspectRatio`。
- Modifier 保持职责顺序可读：先 `constrainAs` 和尺寸约束，再填充/间距，随后 `clip`、`background`/`border`、点击行为，最后放置 `testTag` 等验收标记。需要视觉微调时只在已验收的局部资产或 item 内使用 `offset`，不能用页面级 offset 替代锚点。
- 颜色、Shape 和其他视觉常量放在文件顶部，使用稳定的页面/模块前缀；每个命名 Composable、辅助函数和自定义定位方法上方写中文 KDoc，参数较多时补充 `@param`。

## Popup 与数据边界

- 锚点弹窗使用 `PopupPositionProvider` 计算窗口位置，只有定位换算读取 `LocalDensity`；用 `remember(density, hostView)` 缓存 provider。可见状态为真时才发出 `Popup`，设置 `focusable`、`onDismissRequest`，内部用 `Surface` 承载形状/颜色/阴影和列表选项。
- 显示计数、比例等动态指标先在渲染边界清洗：非负计数使用 `coerceAtLeast(0)`，分母为零时返回安全默认值，比例最终使用 `coerceIn(0f, 1f)`；避免 NaN、负宽度和越界填充进入布局。

## 验收边界

- 基线阶段保留稳定可观测边界；集成到正式业务布局时只保留确有价值的标签和真实点击回调。筛选、弹窗或动画变更后，除内容结果外，还要复核页面级固定区域的 bounds 和状态联动。
