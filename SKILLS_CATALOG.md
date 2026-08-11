# 个人 Skills 目录

> 自动生成于 2026-08-11 18:03:42，由 github-manager 维护
> GitHub 账号：xjxlx

## 概览

| Skill | 用途 | 依赖 | 状态 | 最后更新 |
|---|---|---|---|---|
| [code-analyzer](https://github.com/xjxlx/skills/tree/main/code-analyzer) | 仅在用户明确点名 code-analyzer，或明确要求“使用本技能”进行 Java/Kotlin 代码分析、注释或审查时使用；普通代码阅读、逻辑分析、注... | code-normalize, skill-common | 已发布 | 2026-08-11 |
| [code-image](https://github.com/xjxlx/skills/tree/main/code-image) | Use when 需要导入 Android 图片资源，或明确要求比较设计图与应用截图的视觉差异。 | 无 | 已发布 | 2026-08-11 |
| [code-lanhu-compose](https://github.com/xjxlx/skills/tree/main/code-lanhu-compose) | Use when 用户提供或准备提供蓝湖导出的 HTML/CSS ZIP，需要在 Android 项目中高保真生成或还原 Jetpack Compose ... | code-image | 已发布 | 2026-08-11 |
| [code-normalize](https://github.com/xjxlx/skills/tree/main/code-normalize) | 检测并安全规范 Java、Kotlin 类中的成员变量命名，更新全部引用，补充缺失的类注释，并为关键成员添加作用说明；发现已启用 ViewBinding ... | skill-common | 已发布 | 2026-08-11 |
| [github-manager](https://github.com/xjxlx/skills/tree/main/github-manager) | 实现个人 Codex Skills 的变更检测、凭据扫描、GitHub 发布、目录维护和本地恢复。当用户要求检查发布状态、发布或更新 skill、扫描敏感... | 无 | 已发布 | 2026-08-11 |
| [java-to-kotlin](https://github.com/xjxlx/skills/tree/main/java-to-kotlin) | 将 Android 项目中的 Java 类转换为 Kotlin。用于将 Java 文件迁移到 Kotlin、用惯用 Kotlin 重写 Java 类、或现... | code-analyzer, code-normalize, skill-common | 已发布 | 2026-08-11 |
| [skill-common](https://github.com/xjxlx/skills/tree/main/skill-common) | 作为个人 Skill 的强制基础规范，统一启动时变更检测与自动发布、中文输出、职责路由、依赖去重和持续进化。除明确声明例外的 Skill 外，每个个人 S... | 无 | 已发布 | 2026-08-11 |

## 依赖关系

```mermaid
graph LR
  code-analyzer --> code-normalize
  code-analyzer --> skill-common
  code-lanhu-compose --> code-image
  code-normalize --> skill-common
  java-to-kotlin --> code-analyzer
  java-to-kotlin --> code-normalize
  java-to-kotlin --> skill-common
```

## 各 Skill 详情

### code-analyzer

- **目录名**：`code-analyzer`
- **用途**：仅在用户明确点名 code-analyzer，或明确要求“使用本技能”进行 Java/Kotlin 代码分析、注释或审查时使用；普通代码阅读、逻辑分析、注...
- **依赖**：code-normalize, skill-common
- **文件数**：3
- **UI 元数据**：缺少
- **路径**：`~/.codex/skills/code-analyzer/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/code-analyzer
- **状态**：已发布
- **最后更新**：2026-08-11

### code-image

- **目录名**：`code-image`
- **用途**：Use when 需要导入 Android 图片资源，或明确要求比较设计图与应用截图的视觉差异。
- **依赖**：无
- **文件数**：11
- **UI 元数据**：有 agents/openai.yaml
- **路径**：`~/.codex/skills/code-image/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/code-image
- **状态**：已发布
- **最后更新**：2026-08-11

### code-lanhu-compose

- **目录名**：`code-lanhu-compose`
- **用途**：Use when 用户提供或准备提供蓝湖导出的 HTML/CSS ZIP，需要在 Android 项目中高保真生成或还原 Jetpack Compose ...
- **依赖**：code-image
- **文件数**：17
- **UI 元数据**：有 agents/openai.yaml
- **路径**：`~/.codex/skills/code-lanhu-compose/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/code-lanhu-compose
- **状态**：已发布
- **最后更新**：2026-08-11

### code-normalize

- **目录名**：`code-normalize`
- **用途**：检测并安全规范 Java、Kotlin 类中的成员变量命名，更新全部引用，补充缺失的类注释，并为关键成员添加作用说明；发现已启用 ViewBinding ...
- **依赖**：skill-common
- **文件数**：5
- **UI 元数据**：有 agents/openai.yaml
- **路径**：`~/.codex/skills/code-normalize/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/code-normalize
- **状态**：已发布
- **最后更新**：2026-08-11

### github-manager

- **目录名**：`github-manager`
- **用途**：实现个人 Codex Skills 的变更检测、凭据扫描、GitHub 发布、目录维护和本地恢复。当用户要求检查发布状态、发布或更新 skill、扫描敏感...
- **依赖**：无
- **文件数**：27
- **UI 元数据**：有 agents/openai.yaml
- **路径**：`~/.codex/skills/github-manager/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/github-manager
- **状态**：已发布
- **最后更新**：2026-08-11

### java-to-kotlin

- **目录名**：`java-to-kotlin`
- **用途**：将 Android 项目中的 Java 类转换为 Kotlin。用于将 Java 文件迁移到 Kotlin、用惯用 Kotlin 重写 Java 类、或现...
- **依赖**：code-analyzer, code-normalize, skill-common
- **文件数**：5
- **UI 元数据**：有 agents/openai.yaml
- **路径**：`~/.codex/skills/java-to-kotlin/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/java-to-kotlin
- **状态**：已发布
- **最后更新**：2026-08-11

### skill-common

- **目录名**：`skill-common`
- **用途**：作为个人 Skill 的强制基础规范，统一启动时变更检测与自动发布、中文输出、职责路由、依赖去重和持续进化。除明确声明例外的 Skill 外，每个个人 S...
- **依赖**：无
- **文件数**：5
- **UI 元数据**：有 agents/openai.yaml
- **路径**：`~/.codex/skills/skill-common/`
- **仓库**：https://github.com/xjxlx/skills/tree/main/skill-common
- **状态**：已发布
- **最后更新**：2026-08-11

---

共 **7** 个 skill，其中 **7** 个已发布，**0** 个未发布。
