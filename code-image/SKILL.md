---
name: code-image
description: Use when 需要导入单张图片或含 mipmap 目录的 ZIP，并转换为合规 Android 资源名和稳定映射。
---

# Code Image

导入一个明确来源：单张图片或一个 ZIP。单图复制到项目 `mipmap-xxhdpi`；ZIP 解压后按其中的 `mipmap` 或 `mipmap-*` 目录复制到项目对应目录。每张导入图片均独立生成合规名称并记录映射。

## 强制入口与维护边界

每次调用先执行：

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"
```

遵循 `$skill-common` 的启动检测、中文输出和职责边界。对“持续进化”声明例外：日常图片处理和外部 Skill 调用均不得修改本 Skill；只有用户明确要求维护 `code-image` 时才允许修改其规则、脚本或引用文件。

## 输入契约

- 必须且只能提供其中一项：`--image <path>` 或 `--zip <path>`。重复参数、目录、通配符和同时传递两者均无效。
- `--image` 只接受一张 `.png`、`.jpg`、`.jpeg`、`.webp` 或 `.gif` 图片；源文件保留不动。
- `--zip` 只接受一个 ZIP，且其中必须至少有一张图片位于 `mipmap` 或 `mipmap-*` 目录；否则在解压前拒绝，不能按 ZIP 处理。需要处理其中内容时，改为向 `--image` 传入一张实际图片。
- `--compose <path>` 可选。提供时必须是实际存在的 Compose 文件，仅用于生成页面命名空间。
- `--asset-name <name>` 可选，仅与 `--image` 一起使用；上游已解析设计节点语义时，用它替代导出文件名参与命名。
- `--project-root <path>` 可选，默认当前工作目录。

## 导入位置

- 单图：复制到 `<project>/app/src/main/res/mipmap-xxhdpi/`。
- ZIP：先安全解压到 `~/Downloads/<zip-stem>-<zip-sha256前6位>/`，再将各图片复制到 `<project>/app/src/main/res/<ZIP 内对应的 mipmap 目录名>/`。
- 输出图片始终使用目标目录；不以输入图片原目录或示例中的 `mipmap-nodpi` 作为单图输出位置。

## 命名规则

- 图片基础名转为小写 snake_case：`Group 62.png` → `group_62.png`；无可用英文字符时使用稳定 Hash；数字开头时加 `image_`。
- 无 `--compose` 时输出 `icon_<图片基础名>.<扩展名>`，例如 `icon_group_62.png`。
- 有 `--compose` 时输出 `icon_<页面命名空间>_<图片基础名>.<扩展名>`；提供 `--asset-name` 时图片基础名取该语义名，`Layout` 和 `Page` 后缀不参与命名空间。
- 已以 `icon_` 开头的合规名称不再加前缀；重复导入已记录源时保留已有输出名，显式提供新的 `--asset-name` 时仅在旧文件内容未变时迁移到新语义名。
- 目标 mipmap 目录已有同名文件时，从 `_1` 开始依次递增：`icon_group_62.png` → `icon_group_62_1.png` → `icon_group_62_2.png`。禁止覆盖已有图片。

## 记录与改名

每次导入都在项目 `.code-image/` 新建专属清单：`<来源名>-<来源SHA-256前6位>-<操作编号>.resources.json`，例如 `1600-xxxxxx-1.resources.json`。禁止读写共享 `resources.json`，禁止覆盖或合并历史清单；编号从同一来源身份已有最大值加一。ZIP 用 ZIP 名称和 Hash，单图用图片名称和 Hash。记录格式见 [resource-cache.md](references/resource-cache.md)。

每项记录原始路径和名称、原始 Hash、输出路径和名称、可选 Compose 文件及稳定身份。每次操作只读取和写入自己的新清单；历史资源及其清单必须保留。协调脚本可通过 `--resources-file` 指定符合上述命名的新清单。

## 工作流程

1. 校验唯一输入及可选 Compose 文件。
2. 单图确定 `mipmap-xxhdpi` 目标；ZIP 安全解压到下载目录并收集各 `mipmap*` 图片。
3. 为每张图片独立生成名称；只检查目标目录重名。
4. 输出 Dry Run；确认后以 `--apply` 复制图片并原子写入本次专属清单。

## 使用脚本

单图：

```bash
python3 scripts/normalize_images.py \
  --image ~/Downloads/Group\ 62.png \
  --compose app/src/main/java/com/example/report/ReportHomePage.kt \
  --project-root . \
  --apply
```

ZIP：

```bash
python3 scripts/normalize_images.py \
  --zip ~/Downloads/report-assets.zip \
  --project-root . \
  --apply
```

## 禁止事项

- 禁止覆盖已有图片、自动合并不同来源的图片或修改 Compose 引用。
- 禁止把单图输出到输入所在目录；必须使用 `mipmap-xxhdpi`。
- 禁止把不含 `mipmap*` 图片目录的 ZIP 当作合格 ZIP；必须改用单张实际图片的 `--image` 逻辑。
- 禁止写入 `.codex/`，或因外部 Skill 调用、日常执行而自行修改本 Skill。

## 验证

```bash
python3 scripts/test_normalize_images.py
python3 /Users/XJX/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/XJX/.codex/skills/code-image
```

修改本 Skill 后再次运行 `check_and_publish.sh`，确认发布成功。
