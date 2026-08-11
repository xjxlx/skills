---
name: code-lanhu-compose
description: Use when 用户提供或准备提供蓝湖导出的 HTML/CSS ZIP，需要在 Android 项目中高保真生成或还原 Jetpack Compose 页面，并进行图片资源处理、编译运行或设计稿截图对比。
---

# code-lanhu-compose

把蓝湖 HTML/CSS ZIP 转换为可编译的 Jetpack Compose 视觉基线，并用可追溯截图完成修正。固定脚本负责证据身份、DOM/浏览器采集、资源映射、首稿生成和构建阶段；模型只做项目适配、语义决策和有差异证据支持的补丁。

## 启动约束

- 遵循 `$skill-common`。每次调用先执行 `"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"`；失败立即停止。
- 不调用、不继承旧 `$code-compose`，也不读取它的规则或缓存。
- 图片导入由固定脚本按内容 Hash 调用 `$code-image`；模拟器验证优先调用 `test-android-apps:android-emulator-qa`，不可用时才使用本文的显式 ADB 契约。
- 默认入口只有 `scripts/lanhu_pipeline.py run-fixed`。不要让模型逐项替换浏览器、资源、生成器或 Gradle 命令。

## 必需输入

首次处理只确认：

1. 蓝湖 ZIP 的本地路径；未提供时先索取。
2. 目标 Compose 文件；文件尚不存在时确认页面名、模块和包路径。

当前工作目录就是 Android 项目根目录，不单独索取根目录。缺少 `settings.gradle(.kts)` 或可用 Gradle 入口时停止，并要求用户从正确目录重新调用。目标文件不存在时，确认包名后先创建只含 package/最小 Composable 的项目内占位文件，再进入固定链路。复用用户已提供的信息，不重复询问。

## 三项固定原则

1. **证据身份稳定且失败关闭**：ZIP 完整 MD5 是来源身份；原始 HTML 起始标签注入稳定 `nodeId`，浏览器不能靠位置下标回配。可见伪元素、CSS 渐变/多重背景、缺失图片映射或证据冲突必须暂停，禁止静默丢失。
2. **先生成高保真视觉基线**：浏览器最终 bounds 是位置和尺寸事实；`BoxWithConstraints` 虚拟画布按横纵比例映射 bounds，文本、图片、背景、边框、圆角、透明度和层叠使用最终计算样式。语义化 Row/Column 重构只能在视觉基线验证后进行，不能替代首稿取证。
3. **内容寻址增量执行**：同一来源复用 DOM、浏览器解析、设计截图、解压和图片清单；同一进程缓存文件 MD5；生成内容未变时不重写 Compose，也不重复 Gradle 编译。相同 ZIP 改变目标 Compose 时保留来源证据，但重置目标绑定的资源、生成和构建阶段。

## 默认执行

```bash
python3 /Users/XJX/.codex/skills/code-lanhu-compose/scripts/lanhu_pipeline.py run-fixed \
  --zip <zip> \
  --project-root <project> \
  --compose <Compose.kt> \
  --viewport-width 1600 --viewport-height 900 --dpr 1
```

固定顺序是：

```text
inspect/parse-dom → validate → preflight → design evidence → assets → generate-compose → compile
```

先验证目标并发现唯一 Gradle 模块/variant，再启动浏览器或导入资源；首稿生成后只执行一次实际 Kotlin 编译。预检失败时报告首个可行动原因并停止，不继续改变设计或项目文件。详细状态机见 [固定编排链路契约](references/pipeline-contract.md)。

### 1. 固化 DOM 与浏览器事实

- `inspect` 保存完整 `dom.json`：元素、属性、直接文本、父子关系和本地资源引用都保留；class token 只是原始证据，不能让模型据此猜结构。
- 仅在设计缓存未命中时安全解压并启动 `127.0.0.1` 静态服务。浏览器禁用动画，等待字体、图片解码和稳定节点 bounds/style/currentSrc，随后在同一个页面实例里采集 computed style、bounds、有效透明度、文本 Range、`currentSrc`、Chrome 实际 paint order 和设计截图。
- DOM 到浏览器的映射使用注入的 `data-code-lanhu-node-id`，可抵抗浏览器自动插入 `tbody` 等 DOM 规范化；`body` 多个视觉根节点时保留完整 body 画布。
- `设计解析.json` 版本、完整 `sourceMd5`、viewport/DPR、根节点和绑定 MD5 的有效 `runs/设计截图.png` 全部匹配才算缓存命中。响应式设计通过 `run-fixed --viewport-width/--viewport-height/--dpr` 明确采集环境。字段见 [缓存与设计解析](references/cache-and-parsing.md)。

### 2. 导入图片

- 逐项解析 HTML/CSS 的真实资源路径，校验 ZIP 路径、压缩规模、重复条目、压缩比和符号链接边界；无位图设计允许生成空清单。相同内容先去重，再在同一 Python 进程中批量规划并一次写入 `$code-image` 清单。
- 仅复用项目中仍真实存在的 `$code-image` 输出。`images.json` 记录源路径、内容 MD5、真实 `outputPath` 与 `outputName`；Android 资源引用会去掉文件扩展名。
- 不把整个蓝湖 ZIP 传给 `$code-image --zip`，不按文件名模糊猜图，不用文字或临时 Canvas 替代已有切图。

### 3. 生成 Compose

- `generate_compose.py` 只读取 `dom.json`、`设计解析.json`、`images.json`、目标 Kotlin package 和目标模块 namespace/Manifest；不得修改 JSON 证据来让生成通过。
- 使用浏览器相对根画布的最终 bounds 生成 `offset + size`，并按 Chrome `DOMSnapshot.paintOrder` 排序背景、图片和文本；映射背景色、单一资源背景图、solid 边框/统一圆角、有效透明度、文本颜色/字号/字重/斜体/装饰线/行高/字距/对齐，以及 `<img>` 的浏览器最终资源、`objectFit` 和 `objectPosition`。扁平 Compose 不再重放局部 CSS `z-index`，避免子 stacking context 逃逸。
- 混合 inline 文本使用浏览器 Range 片段，不把父子文本打乱；Kotlin 字符串必须转义 `$`。图片存在时才导入正确模块的 `R` 包。
- 输出采用原子、无变化不写入策略，并返回 `composeMd5`、`changed`、样式节点、文本、`img` 和 CSS 背景图覆盖数量。再次生成得到相同 Hash 时跳过编译。
- 首稿是 bounds-first 的视觉还原，不承诺业务交互或语义组件。模型可在记录证据后适配项目主题、回调和已有组件，但不能绕过生成器手写第一版结构。

映射细节见 [DOM 到 Compose 代码生成](references/dom-to-compose.md) 和 [Compose 映射规则](references/compose-mapping.md)。

### 4. 编译、安装与截图

- `preflight` 根据目标文件和 `gradlew tasks --all` 发现唯一模块/variant 的最小 Debug Kotlin 任务；`compile` 只能复用该任务。多个候选时写入 `needs-user-input.json` 并以退出码 2 暂停；用户明确选择后用 `select-compile-task` 登记，脚本会再次验证它确实属于当前模块候选。
- `package-debug` 从同一编译任务推导 `assemble<Variant>`，只接受目标模块 `build/outputs/apk/` 下的 APK，并登记内容 Hash；`install-k80` 只接受路径、APK Hash、Compose Hash 和时间均未变化的产物。
- 所有 ADB 命令必须带 `-s <serial>`；项目约束指定 K80 时同时核验 AVD 名。截图只有在 ADB 返回成功且文件是可解码、尺寸有效的 PNG 后才推进状态；坏截图会删除，原阶段保持不变。
- 截图前仍须通过 Activity、UI 树或稳定页面标识确认目标页已显示并停止动画；脚本的 PNG 校验不能替代页面就绪检查。

### 5. 归一化、对比和修正

- `runs/设计截图.png` 是公共基准；App 截图按 `应用截图.png`、`应用截图_1.png` 递增，不覆盖历史证据。
- 保留原图，再运行 `normalize_compare_screenshot.py`。输出不能覆盖任一输入；`fit` 必须显式裁剪且裁剪宽高比与设计一致，禁止偷偷拉伸；`fill` 才允许横纵独立缩放。
- `compare-screenshots` 固定调用 `$code-image` 的独立对比脚本，并把来源 MD5、两张截图和完整 metrics 注册到状态。`mark-diff` 拒绝 `{}`、外部报告或未绑定当前截图的伪造结果。
- 模型读取指标和遮罩/热力/叠加图后才选择 `repair`、`pass` 或 `stop`。最多三轮修正；任意一轮关键指标没有改善就立即停止，不消耗剩余轮次。

完整命令和对齐标准见 [视觉验证闭环](references/visual-validation.md)。

## 模型边界

- 允许：目标页最小项目适配、已有组件/交互接线、由编译错误或截图差异直接支持的补丁。
- 禁止：任意 shell 决策、class 名推断业务结构、猜资源名、伪造对比报告、改 JSON 证据、扩大到无关文件。
- 无法确定入口、包名、variant、资源或业务语义时，脚本将问题和来源身份写入 `needs-user-input.json`；没有用户确认不得继续。
- 多个 HTML 入口可用 `select-entry-html --html <ZIP 内路径>` 登记后恢复；多个 Gradle 候选用 `select-compile-task` 恢复。
- 视觉 `stop` 后只有用户明确纠正方向，才运行 `restart-generation --reason <用户原因>`，复用来源证据并重开生成周期。

## 完成标准

完成时报告：ZIP MD5/缓存命中、DOM 与生成覆盖数量、变更文件和资源、实际 Gradle/安装/打开命令、每轮截图指标、最终停止原因及剩余差异。未执行安装或视觉回放时必须明确说明，不能用单元测试冒充端到端还原成功。

变更本 Skill 后运行全部脚本测试、官方 `quick_validate.py`、凭据扫描，再按 `$skill-common` 执行 `check_and_publish.sh`。只有可稳定复现并被测试、编译或视觉证据验证的规则才写入 Skill；项目专属数值和单次事故不沉淀。
