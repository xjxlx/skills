# 工作流细则

## 输入与中间层

开始任何解压、生成、编译、安装或模拟器操作前，先根据 `COMPOSE_ACTIVITY` 在项目源 Manifest 中定位当前页面的承载 Activity。默认确认该 Activity 自己的同一个 `<intent-filter>` 同时声明 `MAIN` 和 `LAUNCHER`；已有非 Launcher 页面必须显式使用 `COMPOSE_ACTIVITY_MODE=existing`。该模式不创建入口、不补写标签、不改用其他 Activity，调试时要走应用真实导航或项目已有测试入口。横向设计稿仅允许给已确认的 Activity 写入 `android:screenOrientation="landscape"`。`build/` 等生成目录中的合并 Manifest 不能替代源配置。

## 参考包分工

先建立 `COMPOSE_REFERENCE_MANIFEST`，把多个设计包声明成一个页面的不同证据来源：

```json
{
  "primary": { "zip": "/绝对路径/L6.zip", "scope": "primary-page" },
  "fragments": [
    { "zip": "/绝对路径/滑动.zip", "scope": "vertical-list-state" },
    { "zip": "/绝对路径/弹窗.zip", "scope": "popup-state" }
  ]
}
```

只对 `primary` 执行整页 `normalize → original.png → Compose` 基线；对每个片段提取差异：纵向片段只确认列表 viewport、item 顺序和滚动后的内容，弹窗片段只确认触发锚点、弹窗边界、选中项和遮挡关系。片段的 DOM index、CSS 高度和截图坐标不能直接追加到主页面树。

## 先反向理解现有代码

生成或修改前按以下顺序检查：目标 Kotlin 的页面入口和区域 Composable、Activity/Fragment 的数据流和回调、Manifest 方向与导出属性、`.code-image` 资源元数据及现有 `R` 引用、列表键和弹窗状态；再搜索项目中同类生产级 Compose 页面，确认实际宿主、组件、定位、状态和资源生命周期约定。已有结构正确时只补齐状态和验收标签，不重新生成一个平行页面；生产文件只迁移决策，不复制业务布局代码。

对“固定骨架 + 列表 + 弹窗”页面，目标结构至少应是：页面根 → 左导航/顶部 → 今日目标与套系触发器 → 纵向套系列表 → 每个套系内横向书卡；弹窗作为根页面的条件 overlay。页面级固定区域优先用 `ConstraintLayout` 和独立 `Guideline` 锚定；同轴重复入口在已锚定的 `Row`/`Column` 中用数据列表和固定间距排列，只有存在独立起点、跨区域对齐或叠层时才给每个入口单独 Guideline；局部可视列表用 `LazyColumn`/`LazyRow`，`Box` 只保留给背景叠层、锁遮罩和单个复合点击项。状态至少包含 `selectedSet`、`popupVisible`、列表数据和当前 item 定位，不能由静态节点名称推导。

解压目录必须直接包含 `index.html`（或 `.code-lanhu-index.html`）、引用的 CSS 和 `img/`。解析器用 Chrome/Puppeteer 采集可见元素的几何、文本、颜色、背景、圆角、阴影和层级，输出 `semantic.json`。

规范化 HTML 逐元素绝对定位，并为元素加 `data-vi`。内联 `background-image:url(...)` 的属性值必须做 HTML 转义，否则双引号会破坏属性边界。

## HTML 阶段

原始 HTML 和 `normalized.html` 均截图后进行像素对比，报告包含相似度、差异比例和 10×5 热点网格。只执行有限策略集合；若未达到 0.9995，恢复最佳策略并记录报告，但 Compose 仍以 `original.png` 为视觉真源。

## Compose 基线

- 像素级验收宽高固定为 `semantic.designW=1334`、`semantic.designH=750`；设计包尺寸不一致时直接失败，禁止通过 `DESIGN_WIDTH` 与 `DESIGN_HEIGHT` 覆盖。
- 元素位于由固定设计尺寸和 `DP_PER_PX=0.5` 推导出的逻辑画布内；页面级区域按语义边界用约束和 `Guideline` 定位，内容内部再用 `padding` 表达间距。禁止用页面级 `offset`、修改源坐标或 `graphicsLayer` 整页缩放掩盖基线误差；经过验收的 item 内小幅光学微调可以保留。
- 页面入口先复用目标 Activity/项目的全局 AutoSize，直接使用项目惯用的 `dp`/`sp`；不要为了整页缩放引入 `BoxWithConstraints`、局部 Density 或逻辑画布。仅当项目没有全局适配时，才按窗口比例承载固定逻辑画布。Popup 的 `PopupPositionProvider` 为 `Dp` 到窗口像素换算而读取 `LocalDensity` 属于定位例外；不同宽高比的剩余空间由设计背景色或背景图铺满，不能分别拉伸或裁切。
- 横向设计稿启动前依赖目标 Activity 的静态 `android:screenOrientation="landscape"` 配置，并要求模拟器已经由用户旋转到横向；截图必须保持原始方向，若截图仍为竖屏则直接失败。禁止脚本执行 `wm size`、`wm density`、`policy_control`、`accelerometer_rotation`、`user_rotation`，禁止旋转图片或做方向补偿；当前模拟器分辨率保持不变，验收按截图真实尺寸换算边界。
- 坐标、尺寸、字号、行高和圆角固定按 `DP_PER_PX=0.5` 换算，保留半 dp/sp 精度；HTML `1334×750` 与 Android `375×667dp` 的轴向对应关系为 `1334↔667`、`750↔375`。
- 背景图、裁切背景、圆角阴影、文字基线和单行文字缩放由生成器统一处理。
- 图片默认使用 `COMPOSE_RESOURCE_MODE=reuse`：需要复用时先调用 `$code-image` 导入并 `--apply`，再计算设计包 `img`/`image` 文件的完整 MD5，与当前目标模块 `.code-image/image.json` 中所有 `originalHash` 匹配；命中且 `outputPath` 实际存在、输出内容 Hash 仍一致时只引用其 `outputName` 对应的 `R.mipmap`，不复制设计包图片。无清单、Hash 未命中或输出损坏时才回退复制设计包图片。`copy` 强制复制设计包图片，`existing` 仍要求显式资源映射；显式映射优先于自动匹配。同一 Hash 多个有效输出时按 `outputPath` 稳定选择首个，需要指定其他资源时使用显式映射。
- 元素较多时拆分私有 Composable，避免单方法字节码超过 64KB。
- 重复且外框几何一致的卡片或文本项识别为列表；横向、纵向均适用，前置完整卡片的宽高允许约 1dp/1–2px 栅格误差。卡片内部的标题、按钮、锁图标、完成态和高亮态属于 item 状态，不因这些字段不同而拆散列表。若最后一个条目在宿主视口边界被裁切，仍要在列表数据中增加一个完整尺寸的 item 对象，再由宿主视口自然裁切其可见部分；不能额外创建半截页面组件，也不能把半截可见宽度写进 item 数据。

### 列表结构识别

列表识别不能只看是否存在图片卡片，也不能只把重复的单个文本节点标记出来。应先按几何关系把同一条记录的字段聚合成复合 item，再决定 Compose 容器：

- 至少 3 条记录具有相同的字段槽位、相近的尺寸/间距和稳定的对齐轴，只变化编号、标题、来源/副标题、时间或数值时，视为列表候选。
- `01`、`02`、`03` 等连续编号、相同的右侧时间列、重复的“标题 + 来源”两行结构，是把页面内容识别为列表的强证据；即使只有 3 条、条目没有图片或某条有高亮背景，也不能按独立页面组件处理。
- 编号、标题、来源和时间属于同一 item 的槽位。生成或重构时使用 item 数据类、数据列表和单一 item Composable；不要生成按序号命名的一组平铺函数，也不要把一条记录的字段提升为列表外的兄弟节点。
- `Column`、`LazyColumn`、`LazyRow` 或网格只表达容器策略，列表语义来自“数据列表 + item 渲染器”。若像素基线阶段暂时逐元素输出，必须在基线验收通过后完成上述语义化重构，并检查每个 item 的边界、顺序和 `testTag` 映射。
- 判定顺序固定为“先看前面至少 3 个完整卡片的外框，再用完整 item 数据统一卡片尺寸，最后看尾项是否只是视口裁切”：不要拿尾项的可见宽高改写 item 尺寸，也不要因条目内部状态不同回退成多个页面级 Composable。

### 状态与交互识别

- 弹窗 ZIP 的额外高度通常是展开状态的画布延伸，不是新的页面高度；保留主页面根尺寸，优先使用项目已有 Dialog 宿主或锚点 `Popup`/`PopupPositionProvider` 表达展开态，不手动画全屏遮罩或把弹窗背景上下文复制进内部布局。
- 触发器、箭头、选中项、关闭行为和筛选后的列表必须共用一个状态源；副作用用稳定业务 key 驱动（如当前套系/课程 ID），播放器等资源在 `DisposableEffect` 中随组合销毁；不允许生成“看起来打开但点了没有变化”的静态弹窗。
- 中间纵向列表只在其 viewport 内滚动，左右书卡保持 `LazyRow`/横向容器语义；不要让整页滚动替代设计稿给出的局部滚动。

## 验收

生成器输出可观测元素清单和被完全覆盖层。安装 APK 后，校验器通过 `uiautomator dump` 比对宏观 `testTag` 与 `testTag("e<domIndex>")` 边界，并从文本优先的样本中裁剪设计截图和模拟器截图做局部色差比较。行为验收顺序固定为：主页面 → 打开套系弹窗 → 选择套系 → 检查筛选 → 滚动中间列表 → 检查当前项定位。

结构通过率低于 95% 或局部抽查低于 80% 即为失败。失败时输出元素/区块清单并保留在目标项目的工作目录；修复生成器后重新跑同一验收，再进行任何语义化重构。
