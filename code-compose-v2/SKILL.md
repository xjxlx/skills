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
- 遵守 `$code-html-compose` 中的引用命名、模块视觉常量命名和中文 KDoc 要求；用户明确指定参考某项已有功能或函数时，先读取其实现与调用关系，确认可复用的行为约定，再把经过验证且能复用于后续任务的要点补入本 Skill。一次性业务细节和未经验证的推测不写入。

## 技能公共约束

- 每次调用先执行：`"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"`。若检测或发布失败，立即停止；无变化或嵌套检测跳过后再继续。
- 遵守 `$skill-common` 的中文优先、职责唯一、依赖去重及证据驱动的进化规范；任务完成并验证后调用 `$skill-common` 复盘。作为子流程运行时不得反向调用本 Skill。
