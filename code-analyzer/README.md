---
name: code-analyzer
description: 仅在用户明确点名 code-analyzer，或明确要求“使用本技能”进行 Java/Kotlin 代码分析、注释或审查时使用；普通代码阅读、逻辑分析、注释和代码审查不得主动触发。
---

# 代码分析器

分析代码文件的逻辑结构，添加结构化中文注释，检测潜在 bug。

## 触发边界

- 只有用户明确点名 `code-analyzer`，或明确要求“使用本技能/这个 skill”完成 Java/Kotlin 代码分析、注释或审查时，才加载并执行本技能。
- 不得仅因为任务属于代码阅读、逻辑分析、添加注释或代码审查，就主动调用本技能；未明确触发时使用通用能力或其他更匹配的 Skill 即可。
- 本技能被明确触发后，才适用下面的强制约束和步骤 0 到步骤 8；未触发时不得执行其中的缓存、规范化、源码写入或技能进化流程。

## 强制约束

- 必须遵循 `$skill-common` 的基础规范，所有面向用户的分析、报告和代码注释使用中文。
- 本技能已明确触发时，任务范围内的代码阅读、逻辑分析、注释和代码审查必须遵循本技能，禁止改用通用能力或其他 Skill 替代。
- 必须为每个方法添加准确的中文注释，并检测明显 Bug 与性能复杂度问题。
- 本技能不得自行处理成员命名、类注释和关键成员注释；读取目标文件后必须先调用 `$code-normalize` 完成规范化。
- 必须连续完成步骤 0 到步骤 8，并管理 `.codex/analysis/` 缓存；遇到困难应先尝试解决，不得无故中止。

## 职责路由

- Java 转 Kotlin 请求必须交给 `$java-to-kotlin`，本技能不得手动转换语言。
- 代码规范化必须交给 `$code-normalize`，本技能不得复制其命名、外部契约和重命名流程。
- `$code-normalize` 作为本技能的子流程运行时，不得反向重新调用 `$code-analyzer`。

## 分析缓存机制

### 缓存的目的

1. **锁定分析结果** — 同一段代码多次分析可能产生不同结果（LLM 非确定性），缓存确保结果一致
2. **加速后续操作** — 修改已分析过的类时，直接读取缓存摘要，无需重新全量分析
3. **跨对话持久化** — 上下文 compact 后，缓存文件仍在磁盘上，新对话可直接加载

### 缓存位置

每个项目根目录下的 `.codex/analysis/` 目录：

```
<project-root>/
├── .codex/analysis/
│   ├── manifest.json                    ← 全局索引
│   └── <hash>_<ClassName>.json          ← 单个文件的分析缓存
├── app/
├── build.gradle.kts
```

### 缓存文件格式

**manifest.json** — 全局索引，记录所有已分析文件：

```json
{
  "files": {
    "app/src/main/java/com/example/MyClass.kt": {
      "hash": "sha256值",
      "cacheFile": "a1b2c3_MyClass.json",
      "analyzedAt": "2026-06-13T10:30:00",
      "annotationVersion": 1
    }
  }
}
```

**单文件缓存** — `<hash>_<ClassName>.json`：

```json
{
  "filePath": "app/src/main/java/com/example/MyClass.kt",
  "hash": "sha256值",
  "analyzedAt": "2026-06-13T10:30:00",
  "classSummary": "护眼模式单例工具类，管理验证码弹窗和时长设置",
  "designPattern": "双重检查锁单例",
  "dependencies": ["GsyApplication", "DialogUtil", "ScreenUtil"],
  "methods": [
    {
      "name": "setDialogView1",
      "signature": "(Activity, TextView?, Int, OnClickListener?)",
      "isPublic": true,
      "summary": "初始化验证弹窗，配置数字键盘和时长选择器",
      "params": {
        "mContext": "当前 Activity 上下文",
        "textView": "显示当前时长的 TextView",
        "type": "1=设置密码，2=解锁",
        "listener": "解锁成功回调"
      },
      "bugs": [
        "不安全 as 转换可能导致 ClassCastException",
        "saveList 直接索引访问可能越界"
      ],
      "complexity": []
    }
  ],
  "openBugs": [
    "单例持有 Activity 强引用，未在 onDestroy 中置空，内存泄漏"
  ],
  "complexityIssues": []
}
```

### 缓存校验规则

- 使用 SHA-256 对源文件内容计算 hash
- hash 匹配 → 缓存有效，直接复用
- hash 不匹配 → 缓存失效，重新分析并覆盖缓存
- manifest.json 不存在 → 视为首次分析，创建目录和文件

## 工作流程

> ⚠️ 重要：所有步骤必须连续执行，中间不得暂停或等待用户输入。从步骤 0 开始，逐步完成到步骤 8 后才能结束任务。

0. **检查分析缓存** — 读取 manifest.json，对比文件 hash，决定是否复用缓存
1. **读取目标文件** — 理解整体结构
2. **代码规范化** — 调用 `$code-normalize` 处理命名、类注释和关键成员注释
3. **分析每个方法** — 从上到下分析功能、参数、返回值和副作用
4. **检测潜在 bug** — 逐项检查常见问题模式
5. **写入注释** — 使用 apply_patch 或等效方式添加
6. **交叉验证** — 确认方法注释准确反映代码行为
7. **生成/更新分析缓存** — 将分析结果写入 `.codex/analysis/` 缓存文件
8. **技能进化** — 按 `$skill-common` 的证据门槛复盘本次执行

## 步骤 0：检查分析缓存

**这是加速后续分析的关键步骤。** 在读取源文件之前，先检查是否存在有效缓存。

### 执行流程

1. 确定项目根目录（向上查找 `build.gradle.kts` 或 `settings.gradle.kts`）
2. 检查 `<项目根目录>/.codex/analysis/manifest.json` 是否存在
3. 如果存在，读取 manifest，查找当前文件的缓存条目
4. 如果找到条目，读取源文件并计算 SHA-256 hash
5. 对比 hash：
   - **匹配** → 缓存有效，加载缓存文件，记录缓存内容供后续步骤使用
   - **不匹配** → 缓存失效，标记需要重新分析
   - **未找到条目** → 首次分析，标记需要生成缓存

### 缓存有效时的行为

缓存有效时，**仍然执行步骤 1-6 的注释写入流程**（因为注释可能被意外删除），但可以：
- 跳过深度分析，直接参考缓存中的方法摘要和 bug 列表
- 将缓存内容作为上下文，加速理解
- 如果源文件中已有完整注释且未被修改，可以跳过注释写入

### 缓存无效时的行为

按完整流程执行步骤 1-7，最后在步骤 7 中更新缓存。

### 缓存目录初始化

如果 `.codex/analysis/` 目录不存在，使用以下命令创建：

```bash
mkdir -p <项目根目录>/.codex/analysis
```

## 步骤 1：读取目标文件

读取完整的代码文件，先获得整体印象：
- 文件中有多少个类/对象
- 类之间的关系（继承、组合、依赖）
- 主要的 public API 是什么
- 使用了哪些设计模式
- 识别性能敏感路径：循环、集合操作、I/O 调用、数据查询

> 如果步骤 0 加载了有效缓存，此步骤可以重点关注缓存中标记为有 bug 或复杂度问题的方法，而非逐行扫描。

## 步骤 2：代码规范化

调用 `$code-normalize` 处理目标文件及受影响调用方：

- 规范不合规成员命名并保护序列化、数据库、反射和公共 API 契约。
- 补充缺失的类注释和关键成员注释。
- 完成旧名称扫描、编译和相关验证。
- 作为本技能的子流程运行，不得反向调用 `$code-analyzer`。

规范化完成后重新读取目标文件，再基于最终名称和类结构执行方法分析。禁止在本技能中复制 `$code-normalize` 的命名、类注释、成员注释或外部契约规则。

## 步骤 3：方法级别注释

为每个方法（包括 private）添加 KDoc/JavaDoc 注释：

### 普通方法

```kotlin
/**
 * 显示护眼模式验证弹窗
 *
 * 流程：
 * 1. 从 GsyApplication 获取已设置的总时长，映射为可读文本
 * 2. 根据屏幕方向选择横屏/竖屏布局，创建 DialogUtil 弹窗
 * 3. 初始化所有视图引用，设置字体样式
 * 4. 配置数字适配器（第一页）和时长选择适配器（第二页）
 * 5. 注册点击事件：数字验证通过后切换到时长选择页
 *
 * @param mContext 当前 Activity 上下文
 * @param textView 用于显示当前已设置时长的 TextView（可为空，为空时不更新）
 * @param type 操作类型：1=设置密码，2=解锁
 * @param listener 解锁成功后的回调监听器
 */
fun setDialogView1(mContext: Activity, textView: TextView?, type: Int, listener: View.OnClickListener?) {
```

### 简单方法

如果方法逻辑极简（一行），可用单行注释：
```kotlin
/** 关闭护眼模式弹窗 */
fun dismiss() { dialogUtil?.dismiss() }
```

对状态切换、持久化、计时器启停、页面跳转和回调转发等关键业务调用，在调用前添加简洁行内注释，说明调用原因或调用后的状态；不要只复述方法名，也不要求为显而易见的 getter、赋值和普通视图查找逐行注释。

## 步骤 4：Bug 检测与复杂度分析

**这是本技能的核心价值。** 在分析每个方法时，主动检测以下常见问题模式（包括 bug 和性能复杂度问题）：

### 检测清单

#### 空安全问题
- 链式调用 `getXxx().getYyy()` — 🔴 中间任一环节为 null 即 NPE
- `getIntent().getXxxExtra()` 后未判空 — 🔴 Intent extra 可能不存在
- `Activity`/`Fragment` 上下文在异步回调中使用 — 🔴 回调时可能已销毁
- `synchronized` 块外访问可变共享状态 — 🟡 多线程竞态条件
- 不安全的类型转换 `as` 而非 `as?` — 🔴 ClassCastException 运行时崩溃（Kotlin 中 `as` 不做空安全检查）

#### 逻辑错误
- `switch/case` 缺少 break 导致 fall-through — 🔴 可能是遗漏
- 循环中修改集合（增删元素） — 🔴 ConcurrentModificationException
- 整数溢出风险（大数运算） — 🟡 int 相乘可能溢出
- 除法前未检查除数为零 — 🔴 ArithmeticException
- 资源未关闭 — 🔴 资源泄漏

#### Android 特定
- 非 UI 线程更新 View — 🔴 崩溃
- Handler 泄漏 Activity 引用 — 🔴 内存泄漏
- 注册监听器但未在 onDestroy 中取消 — 🟡 内存泄漏
- 单例持有 Activity 引用 — 🔴 Activity 无法被回收
- Adapter 成员变量持有 View/LayoutParams 实例并在 onBindViewHolder 中共享赋值 — 🔴 RecyclerView 复用时所有 View 共享同一对象，布局参数互相覆盖
- onBindViewHolder 闭包中直接捕获 position 而非使用 adapterPosition/absoluteAdapterPosition — 🟡 列表增删后点击事件指向错误位置

#### 并发与线程
- 非线程安全的单例实现 — 🔴 多实例
- volatile 字段被复合操作使用（如 i++） — 🟡 原子性问题
- RxJava 订阅未在生命周期结束时取消 — 🔴 内存泄漏

#### 代码质量
- 同一段逻辑重复出现 3 次以上 — 🟡 应提取为私有方法，降低维护成本
- 私有方法中重复的多行重置/清理逻辑 — 🟡 提取为辅助方法（如 resetClickList）
- Kotlin/Java 混合项目的包路径包含 `new`、`class` 等 Java 保留关键字 — 🔴 Kotlin 源码可能可通过转义使用，但 Java 调用方无法正常 import 或使用全限定名。应改用 `v2`、`newmode` 等合法包段，并扫描全部跨语言调用方。
- 跨 Activity 生命周期运行的循环计时器仅通过弱引用保存当前 Activity — 🟡 Activity 可能已 finish 但尚未被回收，弱引用仍非空，导致后续跳转被 `isFinishing` 拦截且没有兜底。应同时保存 application context，并在 Activity 无效时使用 `FLAG_ACTIVITY_NEW_TASK` 继续流程。

#### 性能与复杂度问题

分析目标方法及其直接调用路径，检查嵌套遍历与重复查找/排序、循环内 I/O 或主线程阻塞，以及全量刷新和绑定/绘制阶段重复分配等 Android 热路径开销。

只有输入规模和调用频率足以产生实际影响时才使用 `⚠️ [性能问题: 类型]` 标注，并说明当前复杂度或开销、具体优化方式及优化后收益；可能改变顺序、对象身份、缓存一致性或业务语义时增加 `[需评估]`。

### Bug 标注格式

在方法注释的最顶部，使用醒目的标记：

```kotlin
/**
 * ⚠️ [潜在Bug: NPE风险] context 可能为 null，但后续未做空检查，
 *    若 Activity 已销毁时调用此方法将导致空指针异常。建议增加 context?.let {} 保护。
 *
 * 显示护眼模式验证弹窗
 * ...
 */
```

Bug 标注规则：
- 放在注释的**第一行**，确保最先被看到
- 使用 `⚠️ [潜在Bug: 类型]` 格式
- 紧跟一行**具体描述**：哪里有问题、什么条件下触发、可能的后果
- 如果可能，给出**修复建议**

## 步骤 5：写入方法注释

使用 apply_patch 将注释写入文件。对于大文件（>300 行），按以下顺序分批处理：
1. 先处理 public 方法的注释
2. 再处理 private 方法的注释
3. 最后补充关键业务调用前的必要行内注释
4. 交叉检查是否有遗漏的方法

## 步骤 6：交叉验证

写入注释后，重新读取文件验证：
- 注释是否与代码行为一致
- 是否有遗漏的方法未加注释
- Bug 标注是否准确（不要误报）
- 注释是否干扰代码的可读性
- `$code-normalize` 生成的类注释和成员注释是否仍然完整

## 步骤 7：生成/更新分析缓存

**分析完成后必须执行此步骤。** 将分析结果写入缓存文件，供后续修改操作复用。

### 执行流程

1. 计算当前源文件的 SHA-256 hash
2. 生成缓存 JSON 内容（参考"缓存文件格式"章节）
3. 确保 `.codex/analysis/` 目录存在
4. 写入（或覆盖）单文件缓存 `<hash>_<ClassName>.json`
5. 更新 `manifest.json` 中对应文件的条目

### 缓存内容提取规则

- `classSummary`：从类注释的"职责"部分提取，压缩为一行
- `designPattern`：从类注释的"设计"部分提取
- `dependencies`：从 import 语句中提取项目内依赖（排除标准库和 Android SDK）
- `methods`：逐个方法提取 name、signature、summary、params、bugs、complexity
- `openBugs`：从类级别的 bug 标注中提取（不属于某个特定方法的 bug）
- `complexityIssues`：从类级别的性能标注中提取

### 使用 shell 命令计算 hash

```bash
# macOS
shasum -a 256 <文件路径> | awk '{print $1}'

# Linux
sha256sum <文件路径> | awk '{print $1}'
```

### 更新 manifest.json

读取现有 manifest（如果存在），更新或新增当前文件的条目，然后写回。如果 manifest 不存在，创建新文件。

## 步骤 8：技能进化

任务完成并验证后，必须调用 `$skill-common` 复盘本技能；本技能不重复保存进化门槛和依赖去重策略。

## 注释质量标准

好的注释应该：
- **说明"为什么"而非"做了什么"**：`// 验证用户输入的三位数字` 优于 `// 获取 clickList 的三个元素`
- **指出非显而易见的逻辑**：对于明显的 getter/setter 可以省略或简化
- **Bug/复杂度标注要具体可操作**：指出具体位置、触发条件、修复方向、复杂度对比
- **保持简洁**：方法注释通常控制在 1-10 行，复杂流程按实际需要展开
- **使用一致的格式**：全项目统一使用本技能定义的注释格式
