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

## 固定流程

1. 在目标 Android 项目根目录确认工作区改动，避免把生成的 Kotlin 与资源误判为手写代码。
2. 安装脚本依赖：`npm ci --prefix <本技能>/scripts`。
3. 配置 `PROJECT_ROOT`、Compose 目标目录、包名、`R` 与图片组件导入；完整变量见 [配置参考](references/configuration.md)。
4. 用 `node <本技能>/scripts/run.js <设计包.zip>` 执行：解压、DOM 采集、规范化 HTML、有限像素对比、Compose 生成、构建安装和结构/局部像素验收。
5. 以 `<PROJECT_ROOT>/.code-html-compose/` 内的 `original.png` 和验收报告为真源；它们是运行产物，不得提交或复制到技能仓库。

## 必须遵守的判断

- `original.png` 是最终视觉真源；`normalized.png` 只用于诊断，不能覆盖原始截图。
- HTML 规范化每个确定性策略最多执行一次。未达标时保留最佳报告，禁止无限重试。
- Compose 先生成逐元素高保真基线；仅当结构通过率不少于 95%、局部抽查通过率不少于 80% 后，才能局部语义化重构。
- 生成器使用语义树坐标，按 `DP_PER_PX` 换算，默认适配 @2x 设计稿（`0.5`）；不得把整页等比缩放当作还原方案。
- 每个可观测视觉元素须有 `testTag("e<domIndex>")`；完整被覆盖的层须写入可观测性报告，不能静默跳过。
- 只生成设计图中可见且有视觉证据的节点，不能凭名称补造箭头、指示器或装饰图。

## 资源

- `scripts/`：DOM 解析、HTML 对比、Compose 基线生成、模拟器结构与局部像素校验及测试。
- `references/configuration.md`：运行命令、环境变量和产物边界。
- `references/workflow.md`：工作流细则与视觉还原约束。

运行产生的 `run-*`、`compose-run-*`、截图、JSON 报告、图片资源、`node_modules/` 均只允许位于目标项目工作目录，不得发布到 GitHub。
