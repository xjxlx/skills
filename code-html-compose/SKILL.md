---
name: "code-html-compose"
description: "将蓝湖等工具导出的 HTML/CSS/图片设计包转换为可量化验收的 Jetpack Compose 高保真基线；用于元素缺失、文字裁切、布局偏移或需要模拟器验证的还原任务。"
---

# HTML → Jetpack Compose 高保真转换

所有面向用户的沟通、说明和代码注释使用中文。

## 适用范围

- 输入为含 `index.html`、CSS 和 `img/` 的 HTML 设计压缩包。
- 需要以像素、元素边界和模拟器截图验证 Compose 还原结果。
- 已有绝对定位基线，需要在验收通过后再安全重构为 `Row`、`Column` 或列表。

不适用于只有截图、没有 HTML/CSS/图片资源的任务；先要求用户提供完整设计包。

## 固定设计尺寸与换算基准

- HTML 设计稿固定为 `1334px × 750px`，不得根据 CSS、目录名或 `semantic.json` 自动切换其他设计尺寸。
- Android 目标视图固定为 `375dp × 667dp`；HTML 按 2 倍设计稿处理，固定使用 `DP_PER_PX=0.5`（`1dp=2px`）。
- 数值对应关系固定为：HTML `1334px` ↔ Android `667dp`，HTML `750px` ↔ Android `375dp`；页面方向按目标 Android 页面实际方向对齐，禁止横纵分别拉伸或裁切。
- 设计包不是 `1334px × 750px` 时立即报告尺寸不匹配并停止，不得静默适配或回退到其他尺寸。

## 固定流程

1. 在目标 Android 项目根目录确认工作区改动，并先根据 `COMPOSE_ACTIVITY` 定位当前生成布局实际承载的 Activity（或 Activity-alias），检查它自己的 `MAIN` + `LAUNCHER` 默认 intent-filter。未检测到目标 Activity 或标签时必须提示用户、停止全部后续操作；禁止自行创建 Activity、补写 `MAIN`/`LAUNCHER` 标签或使用其他 Activity 绕过检查。横向设计稿通过前，只能在已找到的目标 Activity 声明上写入或更新 `android:screenOrientation="landscape"`。
2. 安装脚本依赖：`npm ci --prefix <本技能>/scripts`。
3. 配置 `PROJECT_ROOT`、Compose 目标目录、包名、`R` 与图片组件导入；完整变量见 [配置参考](references/configuration.md)。
4. 用 `node <本技能>/scripts/run.js <设计包.zip>` 执行：解压、DOM 采集、规范化 HTML、有限像素对比、Compose 生成、构建安装和结构/局部像素验收。
5. 以 `<PROJECT_ROOT>/.code-html-compose/` 内的 `original.png` 和验收报告为真源；它们是运行产物，不得提交或复制到技能仓库。

### Launcher Activity 与屏幕方向前置检查

- 这里检查的是 Launcher 的 `intent-filter` 标签，不是 `android:launchMode` 属性。
- 总入口和直接的 Compose 生成/验收入口都会读取 `COMPOSE_ACTIVITY`（验收命令行参数优先）并定位该 Activity；只认它自己的同一个 `intent-filter` 中同时声明 `android.intent.action.MAIN` 和 `android.intent.category.LAUNCHER`。
- 目标 Activity 未配置、未找到或缺少任一标签时，输出明确提示，停止后续 HTML/Compose 生成、编译、安装和验收，并以失败状态退出；不得用项目中其他 Launcher Activity 替代，也不得自动创建 Activity 或补写 `MAIN`/`LAUNCHER` 标签。
- 横向设计稿在生成、编译、安装或启动前，更新该目标 Activity 的源 `AndroidManifest.xml` 声明，确保存在 `android:screenOrientation="landscape"`；如果已有其他方向值，替换该值。不得修改其他 Activity。技能不得通过 ADB 修改模拟器的 `wm size`、`wm density`、`policy_control`、`accelerometer_rotation` 或 `user_rotation`；需要横屏时只提示用户将模拟器旋转为横向。
- `build/`、`.gradle/` 和其他生成目录不参与发现，避免用过期合并 Manifest 掩盖项目源配置缺失。

## 必须遵守的判断

- `original.png` 是最终视觉真源；`normalized.png` 只用于诊断，不能覆盖原始截图。
- HTML 规范化每个确定性策略最多执行一次。未达标时保留最佳报告，禁止无限重试。
- Compose 先生成逐元素高保真基线；仅当结构通过率不少于 95%、局部抽查通过率不少于 80% 后，才能局部语义化重构。
- 先识别复合列表项：当 3 个及以上视觉条目沿横向或纵向共享相同的外框卡片尺寸（允许约 1dp/1–2px 栅格误差）、对齐轴、间距和字段槽位时，必须按列表建模；卡片内部标题、按钮、锁图标或高亮等状态差异不否定列表语义，连续的 `01`、`02`、`03` 等编号是强信号。若最后一个条目只因落在设计稿/宿主视口边界而显示不全，按可见裁切矩形记录，但不能用它否定前面完整条目的列表判定。把字段按条目边界聚合为数据类、`listOf` 数据和 item Composable，禁止生成 `Number01`、`Number02`、`Number03` 这类复制粘贴的页面级组件。
- 强列表证据下，基线验收通过后必须完成数据驱动的 `Column`、`LazyColumn`、`LazyRow` 或网格重构；容器类型由设计图的排列方向和是否存在可视视口决定。重构后仍须保留每个条目的可观测边界，并重新执行结构和局部像素验收。
- 像素级验收固定使用 `semantic.designW=1334`、`semantic.designH=750`；尺寸校验失败时立即停止，禁止通过 `DESIGN_WIDTH`、`DESIGN_HEIGHT` 或其他方式静默适配。
- 生成器固定按 `DP_PER_PX=0.5` 把 HTML 坐标和尺寸换算为 Android dp；不得修改源坐标或用 `graphicsLayer` 整页缩放掩盖基线误差。
- 运行时页面按窗口宽高的较小比例设置局部 `Density`，居中完整显示固定逻辑画布；不同宽高比允许留白，禁止横纵分别拉伸或裁切。
- 横向设计稿验收前必须确保目标 Activity 的静态方向配置为 `landscape`，并要求模拟器当前已经横向显示；截图必须保持设备原始方向，禁止通过 ADB 修改窗口分辨率/density、锁定或设置旋转、使用 `rotate90` 或其他图像变换补偿方向。截图仍为竖屏时直接报错并停止验收；不得为了适配设计稿而覆盖模拟器分辨率，边界换算应使用当前横屏截图的实际尺寸。
- 每个可观测视觉元素须有 `testTag("e<domIndex>")`；完整被覆盖的层须写入可观测性报告，不能静默跳过。
- 只生成设计图中可见且有视觉证据的节点，不能凭名称补造箭头、指示器或装饰图。

## 资源

- `scripts/`：DOM 解析、HTML 对比、Compose 基线生成、模拟器结构与局部像素校验及测试。
- `references/configuration.md`：运行命令、环境变量和产物边界。
- `references/workflow.md`：工作流细则与视觉还原约束。

运行产生的 `run-*`、`compose-run-*`、截图、JSON 报告、图片资源、`node_modules/` 均只允许位于目标项目工作目录，不得发布到 GitHub。
