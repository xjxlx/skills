# DOM 到 Compose 代码生成

## 固定输入

生成器只读取以下文件：

```text
dom.json             # parse_html_dom.py 产生的完整 HTML DOM IR
设计解析.json         # 浏览器按 nodeId 写入的 computed style 和 bounds
images.json          # Python 按源路径和内容 Hash 写入的 Android 资源映射
目标 Compose 文件     # 仅读取 package、已有 R 包声明和目标路径
```

`dom.json` 是结构唯一来源。它保存 `nodeId`、`parentId`、`tag`、完整属性、原始 class token、直接文本和 `childrenIds`；class 名称不是组件名、布局方向或业务语义。资源引用保存 `nodeId`、原始 `source` 和校验过的 `resolvedPath`。

`设计解析.json` 只补充浏览器已经计算出的事实：`display`、`flexDirection`、可见性、字体、颜色、边界、层叠、变换和最终图片 URL。它不重新组织 DOM。已有 Compose 的 `package` 与 `import ...R` 只用于确定 Kotlin 文件包名和资源 R 包，不用于推断页面结构。

## 固定映射

| 输入证据 | 生成结果 |
|---|---|
| `display:flex` 且 `flexDirection:row` | `Row` |
| `display:flex` 且 `flexDirection:column` | `Column` |
| 普通块节点含多个可见子节点 | `Column` |
| 重叠/绝对定位事实 | `Box`，保留父子顺序 |
| 直接文本 | `Text`，使用 JSON 字符串转义 |
| `<img>` + `images.json` 的 `sourcePath/outputName` | `Image` + `painterResource(R.drawable/mipmap.name)` |
| 不可见节点、脚本、样式声明节点 | 不生成视觉 Composable |

缺失资源映射、无可见根、DOM IR 损坏或设计节点无法按 `nodeId` 对齐时，生成器必须报错并停止。不能改用文件名、class 名、截图观察或模型记忆来补齐。

## 执行入口

```bash
python3 scripts/lanhu_pipeline.py parse-dom \
  --zip <zip> --project-root <project>

python3 scripts/lanhu_pipeline.py generate-compose \
  --zip <zip> --project-root <project> --compose <Compose.kt>
```

通常直接运行 `run-fixed`，它按 `inspect → 设计采集 → validate → preflight → assets → generate-compose → compile` 顺序执行。生成器使用原子写入；生成后必须继续执行固定的源码检查和 Gradle 阶段。

## 模型的边界

模型可以读取生成输入和编译/截图证据，处理项目已有主题、Composable、交互回调或无法由证据决定的适配问题。模型不能：

- 根据 class 层级重新构造页面；
- 手写首轮 DOM 到 Compose 的结构替换；
- 猜测图片对应关系、资源名或资源路径；
- 修改 `dom.json`、`设计解析.json` 或 `images.json` 来让生成器通过。

模型确需改动时，先通过 `record-decision` 记录证据；能由固定规则解决的结构问题应扩展生成器和回归测试，而不是添加页面特判。
