# Compose 映射规则

## 容器映射

| 设计结构 | Compose 优先表达 |
|---|---|
| 纵向 flex 或普通纵向流 | `Column` |
| 横向 flex | `Row` |
| 重叠层、角标、局部绝对定位 | `Box` |
| 多锚点复杂定位 | 项目已有依赖时使用 `ConstraintLayout` |
| 纵向重复滚动内容 | `LazyColumn` |
| 横向重复滚动内容 | `LazyRow` |
| 单个绘制型装饰 | 优先真实资源；设计本身为图形时才使用 `Canvas` |

先根据 HTML 层级和布局语义选择容器，再用浏览器最终边界校验。不要机械复制无视觉意义的 DOM 包装层。

## 间距归属

1. 父容器 `padding` 只转换一次，负责父边界到所有子项的内部距离。
2. 父容器 `gap` 转换为 `Arrangement.spacedBy`；只有无法表达时才使用父布局中的 `Spacer`。
3. 子节点 `margin` 表示该子节点的特殊外部距离，由父布局在对应位置表达。
4. 子节点 `padding` 属于组件内部空间，即使父级已有 padding 或 gap 也不能删除。
5. 同一段视觉距离不得同时由父级 gap 和子级额外 padding 重复表达。
6. CSS 同时存在 gap 和 margin 时，根据最终元素边界确认二者是否叠加。
7. 普通块布局的 margin collapse 根据最终边界判断，禁止机械相加。

示例：

```css
.parent {
  display: flex;
  flex-direction: column;
  padding: 24px;
  gap: 12px;
}
```

```kotlin
Column(
    modifier = Modifier.padding(24.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
) {
    Item()
    Item()
}
```

子项不得再次添加用于表达兄弟间距的 `12.dp`。

## 样式映射

| CSS/视觉属性 | Compose 表达 |
|---|---|
| background/color | `background`、`Color`、主题 Token |
| border-radius | `RoundedCornerShape`、`clip` |
| border | `border` |
| box-shadow | `shadow` 或项目已有阴影封装 |
| object-fit: cover/contain | `ContentScale.Crop/Fit` |
| overflow: hidden | 在正确顺序执行 `clip` |
| font-size/line-height | `fontSize`、`lineHeight`，单位使用 `sp` |
| letter-spacing | `letterSpacing` |
| opacity | 颜色 alpha 或 `graphicsLayer`，依据影响范围选择 |
| transform | `graphicsLayer`、`offset` 或局部布局重构 |

检查 Modifier 顺序。阴影、裁剪、背景、边框和 padding 的调用顺序不同会产生不同视觉结果。

## 尺寸和代码结构

- 用设计画布宽度、目标设备宽度和 density 建立换算基准；线宽、字体和图片像素可单独校准。
- 内容可伸缩时优先使用 `fillMaxWidth`、`weight`、`aspectRatio` 和项目已有适配方案，不把所有最终边界固化为尺寸常量。
- 颜色和间距只有重复使用或具有语义时才提取常量，避免为每个单次值制造 Token。
- 每个私有 Composable 对应清晰的视觉或语义分组，不按每个 HTML 标签机械拆函数。
- 绝对定位只表达父容器内确实存在的叠放关系；普通内容流保持 `Row`、`Column` 或列表结构。
