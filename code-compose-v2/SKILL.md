---
name: code-compose-v2
description: Use when recreating a Jetpack Compose page from a Lanhu HTML ZIP containing index.html, CSS, and images, especially when pixel bounds and emulator screenshot acceptance are required.
---

# 蓝湖 HTML 到 Compose 高保真还原 v2

## 职责与入口

本 Skill 是用户提供蓝湖 HTML 压缩包并要求 Compose 还原时的专用入口。收到 ZIP 后先解压并检查 `index.html`、它引用的 CSS 和图片，以实际页面布局作为原型底稿，再实现页面。

**必需子 Skill：**完整执行 `$code-html-compose` 的页面分析、实现、像素/元素边界验收、模拟器截图验证和命名规范。它是详细流程的唯一维护位置；本 Skill 只增加下方的用户约定，不复制其余规则。

## 本 Skill 的强制约定

- 主页面验收尺寸为 `1334px × 750px`。设计稿按 2 倍处理，固定使用 `DP_PER_PX=0.5`（`1dp=2px`）；不把其他手机逻辑画布值写成页面或示例的设计基准。
- 图片先检查项目根目录 `.code-image` 中与设计资源对应的现有资源。找到匹配资源时优先复用；找不到时，才把 ZIP 图片临时放入 `mipmap-xxhdpi` 使用。该资源位置是本 Skill 的明确项目约定，即使常规 Android 建议倾向其他资源目录，也按此约定执行。
- 图片、背景、卡片、面板等具有稳定宽高比的区域，优先使用 `aspectRatio(设计宽 / 设计高)`，再配合 `Guideline`、`Dimension.fillToConstraints` 或 `weight` 约束；禁止用 `requiredSize(width, height)` 或成对固定 `width`/`height` 写死尺寸。只有无法表达为比例的结构才使用固定 dp，并说明原因。
- 页面可见文本默认使用 `TextItem`，不要直接使用 Material3 `Text`。需要多种文字样式时，组合多个使用同一字体参数的 `TextItem`；仅在 `TextItem` 无法表达且原因明确时才使用其他文本组件。
- 使用 inline `ConstraintLayout` DSL 时，只有跨多个页面区域共用的锚点才集中放在内容块顶部；区域/组件专属 `Guideline` 必须放在所属区域注释下、紧挨其首个消费者之前，禁止把所有定位线统一堆在顶部。变量名同时表达所属区域和方向，且方向后缀必须与创建方法一致：`createGuidelineFromStart` 用 `...Start`、`createGuidelineFromEnd` 用 `...End`、`createGuidelineFromTop` 用 `...Top`、`createGuidelineFromBottom` 用 `...Bottom`；避免 `guide1` 等无语义名称。
- 每个目标项目开始页面验收前，按文件名检索项目的 `TestActivity.kt` 并复用已有类；首次未找到时，按项目现有包名和目录约定创建一个长期保留的测试 Activity，并告知用户该文件供其审阅和提交。此类是本 Skill 对子 Skill“不得创建 Activity”约束的唯一例外，只用于临时展示和比较当前页面；通过显式的 debug/test 启动方式运行，不得添加 `MAIN`/`LAUNCHER` 或替换应用默认入口。它只辅助日常页面比较，不替代 `$code-html-compose` 对正式页面 Activity 的入口检查和最终验收。使用前保留现有测试页内容；验收后撤销本轮加入的临时页面接线、样例数据和专用临时资源，恢复干净、可复用的测试页，保留 `TestActivity.kt` 本身；后续任务发现该类时直接复用，不重复创建。
- 遵守 `$code-html-compose` 中的引用命名、模块视觉常量命名和中文 KDoc 要求；用户明确指定参考某项已有功能或函数时，先读取其实现与调用关系，确认可复用的行为约定，再把经过验证且能复用于后续任务的要点补入本 Skill。一次性业务细节和未经验证的推测不写入。
- 设计行盒高度必须保留而文字底部被裁切时，给 `Text` 加 `Modifier.wrapContentHeight(unbounded = true)` 并让 `lineHeight` 大于 `fontSize`，父容器不得 `clip`，使字形超出固定行盒居中绘制；不要改成整块内容撑高来替代设计行高。

## 技能公共约束

- 每次调用先执行：`"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"`。若检测或发布失败，立即停止；无变化或嵌套检测跳过后再继续。
- 遵守 `$skill-common` 的中文优先、职责唯一、依赖去重及证据驱动的进化规范；任务完成并验证后调用 `$skill-common` 复盘。作为子流程运行时不得反向调用本 Skill。
