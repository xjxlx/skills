---
name: code-compose
description: 生成符合当前项目规范的 Android Compose 代码，并随使用持续积累项目约定。接收从蓝湖（Lanhu）复制的设计信息（尺寸、颜色、字号、间距、布局、切图清单或代码），解析后按项目既有的命名、目录结构、组件、配色、字体、间距和屏幕适配约定直接产出 Composable 代码。触发场景：用户要求根据蓝湖信息生成 Compose 代码、把设计稿/标注转成 Compose 布局、按项目既有风格编写或优化 Composable、粘贴蓝湖复制内容要求生成代码、或要求记录与复用当前项目的 Compose 规范。
---

# Code Compose

遵循 `$skill-common` 基础规范。本技能只负责 Compose UI 代码生成与项目约定积累；深度逻辑分析、命名规范化和 Java 转 Kotlin 分别交给 `$code-analyzer`、`$code-normalize`、`$java-to-kotlin`，本技能不复制其流程。

## 强制入口

每次调用必须先执行：

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"
```

有变更时等待自动发布成功再处理任务，失败立即停止；无变化或嵌套检测被锁跳过后继续。

## 专属职责

- 把蓝湖复制的设计信息解析并映射为 Compose 代码
- 严格遵循当前项目已沉淀的约定（`conventions/`）；约定未覆盖处先查项目源码再生成
- 维护约定库：只有用户确认或代码可验证的新规范才写入 `conventions/<project>.md`

## 触发场景与流程路由

用户触发本技能时，先判断意图，再走对应流程：

### 场景 A：分析 Compose 布局（不需要 zip）

用户说"分析这个布局"、"帮我看看这个 Compose 文件"、"对比一下设计图和代码"等**分析类请求**时：

- 直接读取指定的 Compose 文件和相关设计图/截图
- 逐区块对比分析，输出差异报告
- **不询问 zip 地址**，不走解压流程
- 如用户后续要求修复/更新，则转入场景 B

### 场景 B：使用 code-compose 生成/更新 Compose 布局（必须走完整流程）

用户明确说"**使用 code-compose** 生成/更新 xxx.kt 的布局"时，严格按以下固定流程执行：

1. **询问 zip 资源地址**（第一步，唯一的第一步）→ 不读代码、不分析、不跳过
2. **解压并分析设计稿** → 解压 zip → 读取 index.html → 解析页面结构、切图、尺寸、颜色、字号、间距
3. **读取现有 Compose 文件** → 文件不存在则从零新建；文件存在则完整读取，逐区块与设计稿对比
4. **差异分析** → 列出设计稿与现有代码的每一处差异
5. **修复/更新代码** → 根据差异逐项修改 Compose 代码
6. **验证** → 编译验证，编译失败则读取错误并修复

### 禁止事项（场景 B）

- 禁止跳过"询问 zip 地址"直接去读代码
- 禁止没有设计稿凭记忆或推测修改布局
- 同一会话已确认过的 zip 地址可以复用，但需向用户确认"复用之前的资源地址"

---

## 设计稿资源获取（仅限场景 B：生成/更新流程）

**使用 code-compose 生成或更新 Compose 布局时，必须先获取蓝湖设计稿资源。** 此步骤为生成/更新流程的前置条件，未完成则不得继续。分析类场景（场景 A）不需要此步骤。

### 规则

1. **主动询问资源地址**：生成流程开始时，必须向用户询问蓝湖设计稿的 zip 资源地址（URL 或本地路径），等待用户提供后再继续。
2. **无资源则停止**：用户未提供资源地址时，**立即停止后续流程**，并主动说明原因："需要蓝湖设计稿 zip 资源才能进行精确的 Compose 生成，请提供资源地址后继续。"
3. **复用已有资源**：同一任务/会话中，若已成功获取过 zip 资源地址，则**直接复用**，不再重复询问用户。
4. **资源缓存**：成功获取的 zip 地址记录到会话上下文中，后续步骤直接引用，避免重复输入。

### 资源地址格式

支持以下格式：
- 本地路径：`/Users/xxx/Downloads/xxx.zip`
- 网络 URL：`https://xxx.com/xxx.zip`（自动下载到本地）
- 用户口头描述：`Downloads 目录下的 xxx.zip`（自动补全路径）

## 资源解压与准备

### 规则

1. **解压目录**：将 zip 资源解压到 `~/Downloads/<解压目录名>/`，目录名取 zip 文件名（去掉 `.zip` 后缀）。
2. **验证内容**：解压后检查目录内容，必须包含 `index.html` 文件；若缺失则停止并提示用户。
3. **资源索引**：自动读取 `index.html` 内容，识别页面结构、图片资源路径、CSS 引用等信息，作为后续生成的参考依据。

### 解压命令

```bash
mkdir -p ~/Downloads/<目录名> && unzip -o <zip路径> -d ~/Downloads/<目录名>/
```

## 工作流

### 1. 加载项目约定

1. 读取 `conventions/index.md`，按当前项目名（cwd 目录名或用户指定）找到约定文件 `conventions/<project>.md`。
2. 存在则通读约定；不存在则执行 `python3 scripts/conventions.py init <project>` 生成模板，再扫描项目现有 Compose 源码，把可验证的基础约定（目录结构、命名、设计稿基准、编译命令、常用组件）填入模板并请用户确认。

### 2. 设计稿资源获取（见上方强制前置章节）

- 主动询问 zip 资源地址
- 有地址则解压到 `~/Downloads/` 并读取 `index.html` 内容
- 无地址则停止并说明原因
- 同一会话已有地址则复用，不再询问

### 3. 收集输入

用户粘贴蓝湖复制内容后，确认或获取：目标页面/组件用途、目标文件路径或包名、设计稿基准宽度。输入不完整时标注缺失项并采用项目默认值，明确告知假设。

### 4. 解析与映射

按 [references/lanhu-to-compose.md](references/lanhu-to-compose.md) 解析尺寸、颜色、字号、间距、布局和切图信息。转换前先查约定库：颜色映射到项目色板、字号映射到项目 Typography、间距映射到项目 spacing 体系、组件优先复用项目已有 Composable。

- 可见性判定：按图层/兄弟节点顺序检查不透明背景遮挡，只实现最终可见的元素；被不透明面板背景盖住的隐藏层（如顶部目标条）不得渲染

### 5. 生成代码

- 遵循项目命名与目录约定（如 `XxxLayout.kt` / `XxxPage.kt`）
- 布局结构、Modifier 顺序、状态管理按项目约定；单函数保持小而内聚，拆分私有 Composable
- 默认写入项目对应 compose 目录；用户指定路径时写入指定位置

### 6. 设计稿截图验证（强制步骤）

代码生成完成后，**必须**进行设计稿截图验证，确保实现与设计稿一致。

#### 截图流程

1. **打开设计稿**：用 Playwright 或 `open` 命令打开 `~/Downloads/<目录名>/index.html`，截取页面有效内容区域的截图，保存到 `/tmp/lanhu_design.png`。
2. **运行 App**：在模拟器上运行 App，导航到对应页面，截取模拟器屏幕截图，保存到 `/tmp/app_screenshot.png`。
3. **对比验证**：逐项对比两张截图的布局结构、元素位置、颜色、字号、间距等，列出差异点。
4. **修复迭代**：发现差异时修改代码，重新运行 App 截图对比。**最多迭代 3 次**。
5. **结果判定**：
   - 3 次内一致：验证通过，输出对比结果。
   - 3 次后仍有差异：列出剩余差异点，说明原因（如图片资源缺失、字体差异等），交由用户确认。

#### 截图技术方案

```javascript
// Playwright 截取设计稿有效内容
const el = await page.$(".page");
if (el) {
  await el.screenshot({ path: "/tmp/lanhu_design.png" });
}
```

```bash
# 模拟器截图
adb shell screencap -p /sdcard/screen.png && adb pull /sdcard/screen.png /tmp/app_screenshot.png
```

### 7. 验证

按约定文件中的编译命令编译（如 `./gradlew :app:compileDebugKotlin`；多 flavor 项目使用显式 variant 任务）。编译失败时读取真实错误并修复，复跑直到通过；无法编译验证时在报告中明确说明。

### 8. 复盘与进化

任务完成后按 `$skill-common` 复盘。候选约定（命名、结构、组件复用点、适配规则等）只有用户确认或代码可验证时才写入约定库。

## 约定库

目录：`conventions/`

- `index.md`：项目索引
- `<project>.md`：单项目约定

```bash
python3 scripts/conventions.py list                        # 列出所有项目
python3 scripts/conventions.py get <project>               # 读取项目约定
python3 scripts/conventions.py add <project> --section <章节> --rule <规则> [--source <来源>]
python3 scripts/conventions.py init <project>              # 生成项目约定模板
```

写入规则：

- 每条规则带日期和来源（用户确认 / 源码证据 / 编译修复）
- 只写能降低未来同类问题概率的最小规则；单次特例、猜测、未验证内容不写入
- 与 `$skill-common` 的进化门槛保持一致

## 与其他 Skill 的边界

- `$code-analyzer`：深度逻辑分析、Bug 检测、方法注释
- `$code-normalize`：成员命名与注释规范化
- `$java-to-kotlin`：Java 转 Kotlin

生成的 Compose 代码同样须符合上述技能的标准，但执行流程由对应技能负责，不在此重复。

## 进化入口

任务结束必须调用 `$skill-common` 复盘：记录观察到的问题、接受/拒绝的候选经验与实际动作；没有新增证据时明确记录"无变更"。
