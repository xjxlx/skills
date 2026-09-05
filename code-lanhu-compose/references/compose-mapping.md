# Compose 映射规则

## 两阶段策略

蓝湖 HTML 的第一目标是还原视觉事实，不是立即产出理想业务组件：

1. **视觉基线阶段**：以浏览器根画布和最终 bounds 生成扁平 `Box` 叠放，确保位置、尺寸、层叠和文本基线可测。
2. **项目适配阶段**：视觉对比证明一致后，才按真实语义和交互把局部分组替换为项目已有 `Row`、`Column`、列表或组件；替换后必须重新截图验证。

这不是按截图猜绝对坐标。坐标来自稳定 `nodeId` 对应的 `getBoundingClientRect()`，结构范围仍由 DOM 父子树限定。

## 虚拟画布

根 Composable 使用 `BoxWithConstraints`：

```text
scaleX = maxWidth.value  / designWidthPx
scaleY = maxHeight.value / designHeightPx
fontScale = min(scaleX, scaleY)
```

节点相对位置为 `bounds.x/y - rootBounds.x/y`，通过标准 `Modifier.offset` 和 `Modifier.size` 映射。位置与尺寸分别使用横纵缩放；文字使用较小比例，避免非等比画布把字体拉扁。禁止自定义 `offsetPx`/`sizePx` Modifier，也禁止用动态平移补偿父布局居中。

全屏填充允许 `scaleX != scaleY`；保持设计比例时必须由调用方明确留白或裁剪策略，不能偷偷拉伸。

### 父子尺寸职责

外层已通过 `ConstraintLayout` 约束、`Dimension.percent`、`fillToConstraints` 或固定容器尺寸确定某一方向的大小时，内部需要占满该方向的 `Box`、`Row` 或 `Column` 使用 `fillMaxHeight()` / `fillMaxWidth()`；不要再次写 `height(...)` / `width(...)` 的固定值。只有当内部节点本身在设计证据中拥有独立尺寸、并非填充父容器时，才保留对应的固定尺寸。

### 简单图形优先代码实现

进度条、分隔线、纯色或简单圆角块等可由尺寸、颜色、形状和裁剪准确表达的视觉元素，优先使用 Compose 布局、`Shape` 或 `Canvas` 实现，不要用图片资源替代；只有纹理、复杂图案或特殊绘制效果无法可靠重建时才保留图片。进度填充层应继承轨道的可用高度（如 `fillMaxHeight()`），仅按比例调整宽度，并通过视觉对比验证结果。

项目已有的 `ReadingProgress` 可作为同类进度布局的标准参考：先用 `fraction.coerceIn(0f, 1f)` 得到安全比例；外层 `Box` 负责整体宽高，轨道层使用 `fillMaxSize()`，填充层使用父容器的最大高度，并仅根据安全比例设置宽度。复用结构和尺寸职责，不直接照搬项目专属资源名或固定数值。

## 固定视觉映射

| 浏览器事实 | Compose 表达 |
|---|---|
| bounds | `offset + size` |
| `backgroundColor` | `background(Color)` |
| 单一 `url(...)` 背景 | `Image` + 对应 Android 资源 |
| `backgroundSize: cover/contain` | `ContentScale.Crop/Fit` |
| `borderWidth/color` | `border` |
| 统一 `borderRadius` | `RoundedCornerShape + clip` |
| 有效祖先透明度 | `alpha` |
| Chrome 实际 paint order | 同一扁平画布的发出顺序 |
| `<img currentSrc>` | `painterResource` |
| `objectFit/objectPosition` | `Crop/Fit/Inside/None/FillBounds + Alignment` |
| 文本 Range bounds | 独立 `Text` 视觉片段 |
| color/fontSize/fontWeight/fontStyle/lineHeight/letterSpacing/textAlign/textDecoration | 对应 `Text` 参数 |

同一节点的背景、背景图、边框、图片和文本与其他节点一起使用 Chrome CDP 捕获的实际 paint order；DOM DFS 只用于确定生成范围，不能冒充 CSS 绘制顺序。扁平层禁止再次应用原 CSS `z-index`，否则嵌套 stacking context 会逃逸。Android 资源 ID 使用 `outputName` 去扩展名后的合法名称；Kotlin 关键字使用反引号，R 包来自显式 import、目标模块 `namespace` 或 Manifest，不能从 Kotlin package 猜。

## 失败关闭与后续修正

下列事实当前不能可靠一对一映射，首稿必须暂停或把差异显式留给证据驱动修正：

- 可见 `::before/::after` 没有可验证 bounds；
- CSS 渐变、多重 background-image；
- `background-repeat`、`background-size:auto` 等无法由单张 Compose Image 等价表达的背景；
- 非 solid 或四边不统一的边框、非统一四角半径；
- 圆角/越界子树裁剪、0 到 1 之间的分组透明度、旋转/缩放等非平移 transform；
- 无法解析到 sRGB 的 CSS Color 4 值、未映射的文本变换/装饰；
- 图片 URL 无唯一清单映射；
- DOM 与浏览器稳定 ID 不一致；
- 无可见根或画布尺寸无效。

`box-shadow`、复杂滤镜和非资源字体应保留在设计解析证据中；若影响截图，依据差异做最小项目适配。不要用未经验证的近似值写进固定生成器。

语义化重构时，只有真实共享父节点和最终布局方向可支持 `Row`/`Column`；滚动、点击、数据列表和状态行为必须来自项目需求或用户确认，不能从 class 名推断。
