# 工作流细则

## 1. 输入与预检

执行任何生成前：

- 检查当前工作区改动，保留用户已有修改。
- 确认设计稿为 `1334×750px`。
- 默认定位项目的 `TestActivity`，确认它由 `BaseV3Page` 包裹；指定页面时使用 `COMPOSE_ACTIVITY`。
- 为页面设置唯一 `PAGE_NAME`，使用默认隔离目录 `.code-compose-v2/<PAGE_NAME>`；只扫描一次 Manifest 和对应 Gradle 模块，将包名、Activity 完整类名、Manifest 路径和横屏修改结果写入该目录的 `runtime-context.json`。
- 检查 `node_modules` 已存在；正常流程不执行 `npm ci`。

## 2. HTML 解析

解压目录必须直接包含 `index.html` 或 `.code-lanhu-index.html`，以及其引用的 CSS 和图片目录。

`normalize.js` 只执行一次：

- Chrome 加载原始 HTML。
- 遍历可见 DOM 节点，记录矩形、文本、颜色、背景、圆角、阴影、层级和对齐样式。
- 合并被祖先裁切的可见矩形。
- 输出 `semantic.json`。
- 截取 `original.png`。

不再生成规范化 HTML、`normalized.png`、多策略对比或 HTML 像素迭代。

## 3. Compose 生成

生成器直接根据 HTML 布局参数决定 Compose 结构：

- 页面首个布局默认生成 `ConstraintLayout`，全部子布局引用统一用一次 `createRefs()` 声明。
- 每个约束子布局至少生成三条 Guide，并在 `constrainAs` 中至少使用一个 `Dimension.fillToConstraints`；纯文字布局可豁免。
- 只有用户明确指定其他根布局，或现有宿主存在不可兼容契约时才允许例外，并在入口 KDoc 中说明原因。
- 根据连续子项的对齐轴和间距选择 Row/Column。
- 根据重复外框、公共槽位和视口选择 Lazy 容器。
- 根据背景、层级和覆盖关系保留必要遮罩。
- 每个提取出的自定义子布局 Composable 调用点写不带“子布局：”前缀的中文用途注释；该 Composable 写中文 KDoc，包含用途、位置和尺寸。标准 Compose 布局调用只注释复杂视觉块。
- 根 `ConstraintLayout` 不写 `testTag("e0")`，校验标签只标记实际视觉元素。
- 根据资源 MD5、项目映射和视觉证据选择 ImageItem。
- 根据文本内容和样式选择 TextItem。

不存在“先输出一次性绝对定位基线，验收后再重构”的阶段。生成首稿就应使用合理容器和可维护数据模型。

## 4. 项目适配

页面内部不引入第二套尺寸适配。固定逻辑尺寸为 `667×375dp`，Activity:

```kotlin
InitView {
    setContent {
        BaseV3Page {
            GeneratedPage()
        }
    }
}
```

生成页面只负责内容布局，不导入 `AutoSizeConfig`、`BoxWithConstraints`、局部 `Density` 或整页 `graphicsLayer` 缩放。

优先复用现有状态和回调。静态 HTML 无法证明业务接口、导航目标或组件生命周期时，不臆造契约。

## 5. 运行方式

生成 Kotlin 和资源后，不使用 Android Studio/IntelliJ 的 Run、Running 或 Apply Changes。代码有改动时执行安装脚本：

```bash
node <技能目录>/scripts/install-app.js
```

验证脚本只负责：

- 从 `runtime-context.json` 读取缓存的包名与 Activity。
- `am force-stop` 缓存的当前包。
- `am start -W -n <缓存的 Activity> -a MAIN -c LAUNCHER` 启动默认或指定测试页面。
- `COMPOSE_START_ARGS` 存在时追加到启动命令，用于 Intent 路由测试页面。
- 短轮询等待 `testTag` 节点。
- 截图、dump 和报告。

修改代码后必须先通过命令行完成安装，再复测；否则验证结果仍是旧页面。

## 6. 统一验收

`compose-validate.js` 是唯一验收入口，包含：

### 整页像素

- 当前真实横屏截图缩放到 `1334×750`。
- 与 `original.png` 逐像素计算平均归一化色差。
- 相似度目标不少于 95%。
- 输出 10×5 热点和最大差异区域。

### 结构边界

- 从语义树读取全部可见元素。
- 全屏根容器不参与结构校验，历史报告中的根 `domIndex 0` 由验证器自动排除。
- 从 `uiautomator` 读取 `e<domIndex>` 实际 bounds。
- 位置和尺寸容差默认 4 设计 px，文本尺寸默认 6 设计 px。
- 通过率目标不少于 95%。

### 局部抽查

- 优先选择文本和关键大区域。
- 每个区域缩放到 48×48 后计算平均色差。
- 通过率目标不少于 80%。

三项同时通过才判定成功。

## 7. 差异修正闭环

低于 95% 时读取统一报告，按以下顺序修正：

1. `not-found` 或缺失元素：检查 DOM 过滤、列表槽位、图片可见性、`testTag` 和页面挂载。
2. 位置或尺寸异常：检查父约束、Row/Column 测量、Guideline、fixed size 和视口裁切。
3. 整页热点集中在图片：检查 code-image Hash、资源映射、ContentScale 和背景裁切。
4. 文本色差或裁切：检查 TextItem 字号、行高、maxLines、对齐、父高度和行盒。
5. 局部层级错误：检查 z 序、遮罩、Dialog/Popup 宿主和覆盖节点。

每轮只根据真实报告修正，不修改设计图片模拟结果。最多执行 5 轮生成、命令行安装和验证；仍未通过时保留最佳报告并明确停止。

## 8. 产物

统一产物位于 `<PROJECT_ROOT>/.code-compose-v2/<PAGE_NAME>/`：

- `out/semantic.json`
- `out/original.png`
- `out/compose-generation-report.json`
- `out/runtime-context.json`
- `out/compose-structure-report.json`
- `compose-run-<时间>/compose-report.json`
- `compose-run-<时间>/compose-diff.png`
- `compose-run-<时间>/compose-shot.png`

这些产物不得提交到技能仓库。
