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

## 工作流

### 1. 加载项目约定

1. 读取 `conventions/index.md`，按当前项目名（cwd 目录名或用户指定）找到约定文件 `conventions/<project>.md`。
2. 存在则通读约定；不存在则执行 `python3 scripts/conventions.py init <project>` 生成模板，再扫描项目现有 Compose 源码，把可验证的基础约定（目录结构、命名、设计稿基准、编译命令、常用组件）填入模板并请用户确认。

### 2. 收集输入

用户粘贴蓝湖复制内容后，确认或获取：目标页面/组件用途、目标文件路径或包名、设计稿基准宽度。输入不完整时标注缺失项并采用项目默认值，明确告知假设。

### 3. 解析与映射

按 [references/lanhu-to-compose.md](references/lanhu-to-compose.md) 解析尺寸、颜色、字号、间距、布局和切图信息。转换前先查约定库：颜色映射到项目色板、字号映射到项目 Typography、间距映射到项目 spacing 体系、组件优先复用项目已有 Composable。

### 4. 生成代码

- 遵循项目命名与目录约定（如 `XxxLayout.kt` / `XxxPage.kt`）
- 布局结构、Modifier 顺序、状态管理按项目约定；单函数保持小而内聚，拆分私有 Composable
- 默认写入项目对应 compose 目录；用户指定路径时写入指定位置
- 蓝湖切图可能漏传：设计引用的资源在项目中缺失时，先用同尺寸空白区域占位，不阻塞布局生成，并在交付说明中列出待补资源清单

### 5. 验证

按约定文件中的编译命令编译（如 `./gradlew :app:compileDebugKotlin`；多 flavor 项目使用显式 variant 任务）。编译失败时读取真实错误并修复，复跑直到通过；无法编译验证时在报告中明确说明。

### 6. 复盘与进化

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

任务结束必须调用 `$skill-common` 复盘：记录观察到的问题、接受/拒绝的候选经验与实际动作；没有新增证据时明确记录“无变更”。
