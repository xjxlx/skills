---
name: code-image
description: Use when 蓝湖下载的图片文件名不符合 Android 资源命名规范、需要按指定 Compose 文件生成资源名、需要处理 mipmap 路径冲突，或需要根据文件 Hash 更新已有图片名称缓存。
---

# Code Image

将蓝湖图片转换为可用于 Android 的稳定资源名，并维护 `code-compose` 可以继续查找的本地映射。核心原则是：Compose 文件名提供页面命名空间，资源 Hash 负责识别同一张图片，缓存负责保证重复执行和原文件改名后的结果稳定。

## 强制入口

每次调用先执行：

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"
```

遵循 `$skill-common` 的中文输出、验证和技能进化约束。

## 每次执行必须先确认的输入

在扫描或重命名之前，必须向用户确认：

1. 当前资源对应的 Compose 文件路径或完整文件名，例如 `ReportHomeV2Layout.kt`。
2. mipmap 路径，例如 `res/mipmap` 或 `res.layouts.report.mipmap`。

用户未提供 mipmap 路径时，使用项目根目录下的 `res/mipmap`；实际项目存在 `app/src/main/res` 时，同时尝试解析为 `app/src/main/res/mipmap`。禁止根据图片内容或当前目录猜测 Compose 文件名。路径解析规则见 [resource-cache.md](references/resource-cache.md)。

## 命名规则

- 使用 Compose 文件 stem 生成 snake_case 命名空间；文件名末尾为 `Layout` 或 `Page` 时必须去掉该后缀：`ReportHomeV2Layout.kt` → `report_home_v2`，`Test3Page.kt` → `test3`。
- 图片基础名统一使用小写 snake_case：`Group 62.png` → `group_62.png`；名称以数字开头时加 `image_` 前缀，中文或无可用英文字符时使用 `image_` 加稳定 Hash。
- 所有输出文件名必须以 `icon_` 开头；最终名称为 `icon_ + Compose命名空间 + 图片基础名 + 原扩展名`，例如 `icon_report_home_v2_group_62.png`。禁止输出驼峰拼接或无分隔符名称。
- 同一资源族在 `mipmap-xhdpi`、`mipmap-xxhdpi` 等密度目录中必须使用同一个文件名。
- 同一资源族内出现不同图片但基础名相同时，为每个资源追加由稳定资源身份计算的 Hash；禁止依赖扫描顺序生成 `_1`、`_2`。
- 扫描项目中已有的 mipmap 文件名；目标名已被其他资源占用时禁止覆盖，改用稳定 Hash 或报告冲突。

## 缓存和改名规则

维护两个文件：

- `.codex/lanhu-resources.json`：保存原始名称或路径到新资源名的简单映射，供 `code-compose` 查找。
- `.codex/code-image-manifest.json`：保存原名、新名、当前路径、Compose 文件、mipmap 资源族和文件 Hash。格式见 [resource-cache.md](references/resource-cache.md)。

重跑时按以下顺序定位历史资源：当前路径 → 缓存中的输出路径 → 相同输出名与资源族 → 相同 Hash 与资源族。Hash 相同但原文件名变化时，视为同一资源，更新缓存中的原名和新生成的资源名；Hash 变化时视为新资源，不删除旧记录。源文件已按 `icon_<命名空间>_` 规范命名时视为已规范化，保留当前名称并只同步缓存，禁止再次追加前缀。

如果同一资源已经被其他 Compose 文件登记，保持原资源名并在报告中标记为共享资源，不要静默追加新的页面前缀。

## 工作流程

1. 确认 Compose 文件和 mipmap 路径，解析基础 mipmap 目录及其密度目录。
2. 读取两个缓存，计算当前图片 Hash，并扫描项目已有资源名。
3. 生成重命名计划：列出原名、新名、Hash 前缀、资源路径和冲突原因。
4. 默认执行 Dry Run；只有用户明确要求执行或确认计划后，才使用 `--apply`。
5. 应用计划时禁止覆盖文件，使用临时文件避免多个资源互换名称时丢失数据。
6. 更新两个缓存；已有 Compose 引用需要同步时，额外使用 `--update-compose`，只修改用户指定的 Compose 文件。
7. 验证目标目录无重名、缓存映射指向实际文件，并报告未处理或无法判断的资源。

## 使用脚本

```bash
python3 scripts/normalize_images.py \
  --compose app/src/main/java/com/jollyeng/www/compose/ui/activity/report/ReportHomeV2Layout.kt \
  --mipmap-path res.layouts.report.mipmap
```

确认 Dry Run 输出后执行：

```bash
python3 scripts/normalize_images.py \
  --compose app/src/main/java/com/jollyeng/www/compose/ui/activity/report/ReportHomeV2Layout.kt \
  --mipmap-path res.layouts.report.mipmap \
  --apply
```

默认只处理指定 mipmap 路径及其密度目录，不处理项目其他图片。缓存已存在时，脚本会根据 Hash 和历史输出路径恢复关系，保证重复执行具有幂等性。

## 禁止事项

- 禁止未确认 Compose 文件名和 mipmap 路径就开始改名。
- 禁止使用简单递增序号解决冲突。
- 禁止覆盖已有图片、删除旧缓存或自动合并内容相同的图片。
- 禁止只更新图片文件而不更新 `lanhu-resources.json`。
- 禁止扫描整个项目后批量重命名未被用户指定的资源。

## 验证

运行技能脚本测试：

```bash
python3 scripts/test_normalize_images.py
python3 /Users/XJX/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/XJX/.codex/skills/code-image
```

技能更新完成后再次运行 `check_and_publish.sh`，确认安全扫描、统一仓库同步和发布状态均成功。

## 职责边界

- `$code-compose`：根据缓存映射引用图片并生成 Compose UI。
- `$code-image`：规范图片文件名、处理资源冲突和维护图片缓存。
- `$code-analyzer`：分析 Kotlin/Java 逻辑，不由本技能替代。

任务结束按 `$skill-common` 复盘；只有用户确认或源码、测试可验证的规则才写入本技能。
