---
name: code-image
description: Use when 需要将单个 Android mipmap 图片改为合规资源名，并记录原始名称与新名称的稳定映射。
---

# Code Image

只处理调用方明确传入的一张图片：将其改为合规 Android 资源名，并在项目根目录 `.code-image/resources.json` 记录原始信息和改名结果。它不批量扫描或重命名其他图片，不修改 Compose，也不负责图片导入。

## 强制入口与维护边界

每次调用先执行：

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"
```

遵循 `$skill-common` 的启动检测、中文输出和职责边界。对“持续进化”声明例外：日常图片处理和外部 Skill 调用均不得修改本 Skill；只有用户明确要求维护 `code-image` 时才允许修改其规则、脚本或引用文件。

## 输入契约

- `--image <path>` 是唯一必填输入，必须是项目内 `mipmap` 或 `mipmap-*` 目录下的一张 `.png`、`.jpg`、`.jpeg`、`.webp` 或 `.gif` 图片。
- `--compose <path>` 是可选参考。提供时必须是实际存在的 Compose 文件；仅用于生成页面命名空间。
- 每次命令只能传入一个 `--image`。有 N 张图片时必须调用 N 次；禁止输入目录、通配符、ZIP 清单或多图片列表。
- `--project-root <path>` 可选；未提供时从图片路径推断项目根目录。

## 命名规则

- 图片基础名转为小写 snake_case：`Group 62.png` → `group_62.png`；无可用英文字符时使用稳定 Hash；数字开头时加 `image_`。
- 无 `--compose` 时输出 `icon_<图片基础名>.<扩展名>`，例如 `icon_group_62.png`。
- 有 `--compose` 时输出 `icon_<页面命名空间>_<图片基础名>.<扩展名>`，例如 `ReportHomeV2Layout.kt` → `icon_report_home_v2_group_62.png`。
- Compose 文件名以 `Layout` 或 `Page` 结尾时去掉该后缀：`Test3Page.kt` → `test3`。
- 已以 `icon_` 开头的合规名称不再加前缀；重跑已记录图片时保留已有输出名。
- 目标名与同一 mipmap 资源族中既有文件冲突时，追加稳定 Hash；只读取冲突文件名，不改动它们。

## 记录与改名

所有运行时生成文件只允许放在项目根目录 `.code-image/`：

```text
.code-image/
└── resources.json
```

实际改名只发生在输入图片原本所在的 mipmap 目录。应用改名后，原子更新 `.code-image/resources.json`，每项至少记录原始路径和名称、原始 Hash、输出路径和名称、Compose 文件（可为 `null`）、资源族及更新时间。格式见 [resource-cache.md](references/resource-cache.md)。

重复调用时先匹配当前输出路径，或匹配原始路径且 Hash 一致；未命中时才以同一资源族内唯一的 Hash 匹配。命中后更新同一记录，保留首次原始路径和名称，避免二次加前缀。相同 Hash 对应多条记录时不得自动合并。

## 工作流程

1. 校验唯一的 `--image` 和可选 `--compose`；确认图片位于项目内 mipmap 资源目录。
2. 读取 `.code-image/resources.json`，计算输入图片 Hash；仅检查同资源族文件名是否占用目标名。
3. 输出这一张图片的 Dry Run 计划。
4. 用户确认后以 `--apply` 原地改名，并原子更新 `resources.json`。
5. 报告原文件名、输出文件名、资源记录路径和未处理的冲突。

## 使用脚本

无 Compose 上下文：

```bash
python3 scripts/normalize_images.py \
  --image app/src/main/res/mipmap-nodpi/Group\ 62.png \
  --project-root .
```

有 Compose 上下文并执行：

```bash
python3 scripts/normalize_images.py \
  --image app/src/main/res/mipmap-nodpi/Group\ 62.png \
  --compose app/src/main/java/com/example/report/ReportHomePage.kt \
  --project-root . \
  --apply
```

## 禁止事项

- 禁止处理未明确传入的第二张图片、目录或 ZIP 清单中的图片。
- 禁止写入 `.code-image/` 之外的缓存、映射、日志或临时产物；不得写入 `.codex/`。
- 禁止覆盖已有图片、自动合并内容相同的不同图片，或修改 Compose 引用。
- 禁止因外部 Skill 调用或日常执行而自行修改本 Skill。

## 验证

```bash
python3 scripts/test_normalize_images.py
python3 /Users/XJX/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/XJX/.codex/skills/code-image
```

修改本 Skill 后再次运行 `check_and_publish.sh`，确认发布成功。
