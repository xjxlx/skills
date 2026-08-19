# DOM 到 Compose 代码生成

## 固定输入

```text
dom.json          完整 DOM IR 和经 ZIP 边界校验的资源引用
设计解析.json      稳定 nodeId 对应的浏览器最终 bounds/style/text runs/currentSrc
images.json       源路径与真实 Android 输出资源的内容寻址映射
目标 Kotlin 文件   package、显式 R import、模块 namespace/Manifest
```

DOM 决定哪些节点属于页面和遍历顺序；浏览器决定它们最终是否可见、在哪里、长宽多少、显示什么资源和样式。任一侧不能按稳定 `nodeId` 唯一对应时停止，禁止回退到 class 名或数组下标。

## 生成算法

1. 校验 DOM 版本、非空节点、设计画布和可见根。
2. 以 `设计根节点.nodeId` 定位生成范围；多视觉根时根为 `body`，不会只取第一个兄弟。
3. 拒绝当前不能精确表达的可见伪元素和 CSS 渐变/多重背景。
4. 建立 `nodeId → layout`、`sourcePath → images.json record` 映射；`img` 优先使用浏览器实际选择的 `currentSrc`。
5. 把节点 primitive 与文本 Range 合并为统一绘制事件，并按 Chrome `DOMSnapshot.paintOrder` 排序：
   - 忽略 head、script、style、link、meta、注释和不可见节点；
   - 使用最终 bounds 减去根 bounds 得到相对画布位置；
   - 发出背景/边框、CSS 背景图、`img` 和文字；不把扁平化前局部 CSS `z-index` 再施加到顶层 Box；
   - 设计解析含 text runs 时，只按 Range 片段发出文字，避免父子 directText 重复或乱序。
6. 生成 `BoxWithConstraints` 虚拟画布，位置/尺寸使用横纵缩放，字号使用较小比例。
7. 原子写入；目标内容相同时不改 mtime，返回源码 `composeMd5` 和 `changed:false`。

## 结果计数

生成 JSON 至少包含：

| 字段 | 含义 |
|---|---|
| `nodeCount` | DOM 总节点数 |
| `rootNodeId` | 实际生成根 |
| `styledNodeCount` | 发出至少一种可见样式/内容的次数 |
| `textCount` | 文字 Composable 数量 |
| `imageCount` | `<img>` 数量 |
| `backgroundImageCount` | CSS 资源背景数量 |
| `composeMd5` | 生成源码内容 Hash |
| `changed` | 是否真实改写目标文件 |

这些计数用于暴露覆盖率，不是视觉通过标准。最终仍需编译与截图对比。

## 资源与 Kotlin 细节

- `outputName` 先去扩展名，再规范为 Android 资源 ID；不能生成 `R.mipmap.name_png`。
- 根据真实输出路径选择 `R.mipmap` 或 `R.drawable`。
- 有图片时必须找到目标模块资源包；无图片页面不导入 `R`。
- `object-fit: cover/contain/scale-down/none` 对应 `Crop/Fit/Inside/None`；`object-position` 映射 Compose Alignment/BiasAlignment，其他 fit 值使用 `FillBounds`。
- 文本参数来自 computed style，支持斜体、下划线和删除线；所有字符串用 JSON/Kotlin 兼容转义，并额外转义 `$`。
- `effectiveOpacity` 已包含祖先透明度；祖先为 0 的子节点不会生成。
- 扁平基线不能等价表达的分组透明度、圆角/越界子树裁剪、非平移 transform、重复/auto 背景、渐变、多背景、非 solid/非统一边框和无法解析到 sRGB 的颜色会失败关闭，不生成未经验证的近似。

## 执行入口

```bash
python3 scripts/lanhu_pipeline.py generate-compose \
  --zip <zip> --project-root <project> --compose <Compose.kt>
```

默认应使用 `run-fixed`，不存在人工阶段标记旁路。若固定规则缺失，先补失败测试和通用生成逻辑；项目特有交互或主题适配才由模型用 `record-decision` 登记后打最小补丁。
