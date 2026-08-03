# 蓝湖信息到 Compose 的解析与映射

## 输入形态

蓝湖支持复制的常见信息：

1. 标注信息：选中图层后复制的尺寸、位置、颜色、字号、圆角、间距字段
2. CSS 代码：从“开发”面板复制的 CSS 片段
3. 资源清单：切图、图标、图片的下载清单
4. 截图：整块设计稿图片（无法解析数值时，结合项目基准估算并请用户确认关键尺寸）

## 通用换算

- 设计稿基准：以蓝湖导出信息中的页面/画布实际尺寸为准（如 HTML/CSS 中 `.page` 的宽高），禁止写死固定基准；设计稿尺寸不规范（异常宽高比、与项目约定不一致）时仍按导出尺寸换算，并明确标注假设
- 换算公式：`dp = px × 设计稿实际逻辑宽度 / 设计稿像素宽度`；字号同理换算为 `sp`
- 颜色：`#RRGGBB` → `Color(0xFFRRGGBB)`，`#RRGGBBAA` → `Color(0xRRGGBBAA)`；先查项目色板，禁止硬编码已有语义色
- 圆角：`border-radius` → `RoundedCornerShape`
- 阴影：`box-shadow` → `Modifier.shadow` 或 elevation
- 间距：`margin/padding/gap` → `Modifier.padding`、`Arrangement.spacedBy`、`Spacer`；优先项目 spacing 体系

## CSS 到 Compose 的典型映射

| CSS | Compose |
|---|---|
| `display: flex; flex-direction: row/column` | `Row` / `Column` |
| `justify-content` / `align-items` | `Arrangement` / `Alignment` |
| `gap` | `Arrangement.spacedBy` / `Spacer` |
| `padding` / `margin` | `Modifier.padding` |
| `width` / `height` | `Modifier.size` / `width` / `height`（含 dp 换算） |
| `font-size` / `font-weight` / `line-height` | `fontSize` / `fontWeight` / `lineHeight` |
| `color` | `Color`（查项目色板） |
| `border-radius` | `RoundedCornerShape` |
| `box-shadow` | `Modifier.shadow` / elevation |
| `background` | `Modifier.background` |
| `border` | `Modifier.border` |
| `overflow: hidden` | `Modifier.clip` |
| `position: absolute` | `Box` + `Modifier.offset` / `Alignment` |

## 生成顺序

1. 结构：确定 Root（`Scaffold`/`Column`/`Box`）与子层级
2. 布局：排列与间距
3. 内容：文本、图片、组件
4. 样式：颜色、字体、圆角、阴影
5. 状态与交互：点击、选中态、禁用态；默认态/加载态/空态/错误态按项目约定

## 输出要求

- 优先复用项目既有 Composable、图标和 drawable，不引入新依赖（除非用户明确要求且项目允许）
- 遵循项目命名与目录约定
- 使用不可变 UI 状态，状态提升到最低公共父级
- 输出文件路径、入口与使用说明

## 输入不足时的处理

- 缺尺寸：用项目间距/组件默认值，标注假设
- 缺颜色：查项目主题，标注假设
- 缺交互说明：只生成静态布局并提示用户补充

## 蓝湖资源命名与缓存

### 命名规范

- 图片输出命名、Hash 冲突和缓存更新统一由 `$code-image` 负责；其 `icon_<compose>_<asset>.ext` 结果是本流程唯一认可的资源名。
- `code-compose` 只负责查找和引用，不复制另一套清洗规则，也不从原始名推导新文件名。

### 缓存文件

- 位置：项目根目录 `.codex/lanhu-resources.json`（项目已有其他固定资源目录时，缓存放同目录）
- 格式：`{"原始名称或URL": "当前本地资源文件名"}`；同名资源可以使用“资源族路径/原始文件名”作为键。
- 示例：`{"Group 62.png": "icon_report_home_v2_group_62.png", "res/layouts/report/mipmap-xhdpi/Group 63.png": "icon_report_home_v2_group_63.png"}`
- 查找时使用 `scripts/resolve_resources.py`，按本地实际文件、简单映射、完整 manifest 的顺序解析；只有确认文件存在后才生成 `R.mipmap.<资源 stem>`。
- 示例命令：`python3 scripts/resolve_resources.py --project-root /path/to/project --original "Group 62.png"`
- 缓存缺失、过期或出现多个候选时，必须报告原始文件名和候选路径，禁止在 Compose 代码中猜测资源名。

完整示例见 [examples/lanhu-sample.md](../examples/lanhu-sample.md)。
