# 蓝湖信息到 Compose 的解析与映射

## 输入形态

蓝湖支持复制的常见信息：

1. 标注信息：选中图层后复制的尺寸、位置、颜色、字号、圆角、间距字段
2. CSS 代码：从“开发”面板复制的 CSS 片段
3. 资源清单：切图、图标、图片的下载清单
4. 截图：整块设计稿图片（无法解析数值时，结合项目基准估算并请用户确认关键尺寸）

## 通用换算

- 设计稿基准：优先取项目约定的设计稿宽度（如 375dp 逻辑宽度或 1080px 像素宽度）
- 换算公式：`dp = px × 设计稿逻辑宽度 / 设计稿像素宽度`；字号同理换算为 `sp`
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

完整示例见 [examples/lanhu-sample.md](../examples/lanhu-sample.md)。
