---
name: code-image
description: Use when 需要导入 Android 图片资源，或明确要求比较设计图与应用截图的视觉差异。
---

# Code Image

导入一个明确来源：单张图片或一个 ZIP。单图复制到项目 `mipmap-xxhdpi`；ZIP 仅临时解压，按其中的 `mipmap` 或 `mipmap-*` 目录将重命名后的图片复制到项目对应目录，并以 ZIP 文件名作为资源名前缀。原始 ZIP 文件不会复制到项目，临时原始文件在导入结束后自动清理。每张导入图片均生成语义化的 Android 资源名并记录映射；每次成功执行还会扫描项目所有 Android 模块的 `src/main/res` 图片，累计维护项目级索引。视觉对比是独立能力，不会在图片转换时自动执行。

## 强制入口与维护边界

每次调用先执行：

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"
```

遵循 `$skill-common` 的启动检测、中文输出和职责边界。对“持续进化”声明例外：日常图片处理和外部 Skill 调用均不得修改本 Skill；只有用户明确要求维护 `code-image` 时才允许修改其规则、脚本或引用文件。

## 输入契约

- 必须且只能提供其中一项：`--scan`、`--image <path>` 或 `--zip <path>`。`--scan` 只扫描项目资源，不接收图片输入；重复参数、目录、通配符和同时传递两种输入均无效。
- `--image` 只接受一张可解码的 `.png`、`.jpg`、`.jpeg`、`.webp` 或 `.gif` 图片；扩展名与实际内容不符时拒绝，源文件保留不动。
- `--zip` 只接受一个 ZIP，且其中必须至少有一张图片位于 `mipmap` 或 `mipmap-*` 目录；否则在解压前拒绝，不能按 ZIP 处理。需要处理其中内容时，改为向 `--image` 传入一张实际图片。
- `--compose <path>` 可选。提供时必须是实际存在的 Compose 文件，仅用于生成页面命名空间。
- `--asset-name <name>` 可选，仅与 `--image` 一起使用；上游已解析设计节点语义时，用它替代导出文件名参与命名。
- `--project-root <path>` 可选，默认当前工作目录。
- 中文命名依赖 Python 包 `text-unidecode`；缺少该依赖且名称含未配置的中文时应报错，禁止退回 MD5 或 `image_` 名称。

## 导入位置

- 未提供 `--compose` 时写入 `<project>/app/src/main/res/`；提供时从 Compose 的 `src` 路径确定真实模块，禁止跨模块导入。
- 单图进入目标模块 `mipmap-xxhdpi/`；ZIP 先按完整 MD5 校验并安全解压到系统临时目录，再将重命名后的图片复制到项目中同名的 `mipmap` 或 `mipmap-*` 密度目录，例如 ZIP 内 `mipmap-xxhdpi/` 进入项目 `mipmap-xxhdpi/`。项目中只保留重命名后的输出图片和资源清单，不保留 ZIP 原始图片。
- 输出图片始终使用目标目录；不以输入图片原目录或示例中的 `mipmap-nodpi` 作为单图输出位置。

## 命名规则

- 图片基础名先删除 `备份`、`副本`、`copy`、`backup` 以及独立的复制编号字段，再转换为语义英文和小写 snake_case；例如 `矩形备份 4.png` → `rectangle.png`、`编组 40.png` → `group.png`。
- 常见中文设计词使用语义英文映射；未配置的中文使用拼音，不使用 MD5：`今日目标.png` → `today_target.png`，`测试图标.png` → `ce_shi_tu_biao.png`。
- 无 `--compose` 时输出 `icon_<图片基础名>.<扩展名>`，例如 `Group 62.png` → `icon_group.png`。
- 有 `--compose` 时输出 `icon_<页面命名空间>_<图片基础名>.<扩展名>`；提供 `--asset-name` 时图片基础名取该语义名，`Layout` 和 `Page` 后缀不参与命名空间。
- ZIP 导入时以 ZIP 文件名作为前缀，先规范化 ZIP 名称再拼接图片基础名；例如 `L6.zip` 中的 `Group 62.png` 输出为 `icon_l6_group.png`。ZIP 前缀优先于 Compose 页面命名空间；ZIP 内已规范化的图片名也必须补上 ZIP 前缀。
- 命名完成后，如果目标密度目录中已有同名文件，或同一 ZIP 的同一密度目录中生成了同名结果，从 `_1` 开始递增：`icon_l6_group.png` → `icon_l6_group_1.png` → `icon_l6_group_2.png`。禁止覆盖未登记图片。
- 已以 `icon_` 开头且满足 Android 小写资源名规则的单图名称不再加前缀；统一清单内，来源路径加 Hash 或同目标密度的内容 Hash 命中已有记录时，先验证输出路径、模块和内容 Hash。完整命中不复制；缺失或损坏时原子恢复记录中的输出名；不再依赖命名版本字段迁移旧名称；`--asset-name` 不迁移已有资源映射。

## 记录与改名

项目 `.code-image/` 使用统一的 `image.json` 累计资源索引。每次成功 `--apply` 都会扫描所有 Android 模块的 `src/main/res` 图片并原子更新：新增文件追加、同路径内容变化更新、已删除文件移除；多个路径拥有相同 MD5 时分别保留。旧版按来源生成的 `*.resources.json` 和 `resources.json` 会在成功写入后清理，已导入的图片输出文件保留。ZIP 原始文件只在系统临时目录存在，导入结束后清理，不在项目中建立解压缓存。记录格式见 [resource-cache.md](references/resource-cache.md)。

每项清单至少记录 `md5`、`identifier`、`path`、`name`；`identifier` 固定为 `path-md5`，`path` 是相对项目根目录的实际资源路径，`name` 是文件名。ZIP 导入记录额外写入 `source`（`<ZIP文件名>!/<ZIP内部路径>`）。完整 `md5` 是与 `code-html-compose` 协作的唯一内容匹配依据；同一 MD5 的不同项目路径不能合并。旧版 `originalHash`/`outputPath`/`outputName` 只用于迁移读取，并在下一次成功 `--apply` 时转换为新格式。

## 工作流程

1. 校验唯一输入及可选 Compose 文件；`--scan` 直接进入全局目录扫描。
2. 由 Compose 路径确定模块；ZIP 在写入前校验规范化重复路径、符号链接、条目数、解压大小和压缩比。
3. 在内存中扫描项目资源并按目标目录和内容 Hash 规划导入；完整命中时复用已有输出，否则生成名称或恢复损坏输出。
4. 输出 Dry Run；确认后以 `--apply` 原子复制图片，再扫描全局资源并原子更新累计 `image.json`。

单独扫描项目图片：

```bash
python3 scripts/normalize_images.py --scan --project-root . --apply
```

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
  --zip ~/Downloads/L6.zip \
  --project-root . \
  --apply
```

## 独立视觉对比（必须显式调用）

只有用户明确要求比较两张图时，才调用 `scripts/compare_images.py`；它不复制图片、不修改 Compose、不写入资源映射，也不被导入流程隐式调用。脚本校验宽高比和输入/输出路径，按设计图尺寸对齐应用截图，原子输出像素差、SSIM、边缘差异、差异区域及三张绑定 MD5 的证据图。完整契约见 [image-comparison.md](references/image-comparison.md)。

```bash
python3 scripts/compare_images.py \
  --design <设计截图.png> \
  --app <应用截图.png> \
  --output-dir <差异证据目录>
```

## 禁止事项

- 禁止覆盖未登记图片、自动合并不同来源的图片或修改 Compose 引用；清单只覆盖记录内容，不覆盖已有图片。
- 禁止把单图输出到输入所在目录；必须使用 `mipmap-xxhdpi`。
- 禁止把不含 `mipmap*` 图片目录的 ZIP 当作合格 ZIP；必须改用单张实际图片的 `--image` 逻辑。
- 禁止把 ZIP 原始文件解压到项目目录、公开 Downloads 或其他不受本 Skill 管理的目录；原始文件只能进入系统临时目录，并在本次导入结束后清理。禁止让差异输出覆盖输入图片。
- 禁止写入 `.codex/`，或因外部 Skill 调用、日常执行而自行修改本 Skill。

## 验证

```bash
python3 scripts/test_normalize_images.py
python3 scripts/test_compare_images.py
python3 /Users/XJX/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/XJX/.codex/skills/code-image
```

修改本 Skill 后再次运行 `check_and_publish.sh`，确认发布成功。
