# 配置与运行

在目标 Android 项目根目录执行。设计包、截图、报告和日志统一写入：

```text
<PROJECT_ROOT>/.code-compose-v2/
```

个人技能目录只保存脚本、规则和测试，不得写入设计包、图片、APK 或运行产物。

## 前置条件

- HTML 设计稿固定为 `1334px × 750px`。
- 目标 Activity 已配置横屏，并由项目 `BaseV3Page` 包裹生成页面。
- 模拟器已经由用户旋转为横屏。
- 代码有改动时，应用已通过命令行 Debug 安装任务刷新；不得依赖 IDE Run 或 Apply Changes。
- `scripts/node_modules` 已存在且依赖有效。正常页面任务不执行 `npm ci`；依赖缺失时先通知用户。

## 必填变量

```bash
export PROJECT_ROOT="$PWD"
export COMPOSE_KOTLIN_DIR="app/src/main/java/com/example/app/ui/generated"
export COMPOSE_RES_DIR="app/src/main/res"
export COMPOSE_PACKAGE="com.example.app.ui.generated"
export COMPOSE_R_IMPORT="import com.example.app.R"
export COMPOSE_IMAGE_IMPORTS=$'import com.example.widget.ImageItem\nimport com.example.widget.ImageParameter'
```

`COMPOSE_TEXT_IMPORT` 必须由目标项目提供：

```bash
export COMPOSE_TEXT_IMPORT="import com.example.widget.TextItem"
```

## 可选变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `PAGE_NAME` | `GeneratedPage` | 页面任务名、生成的 Kotlin 文件和 Composable 名 |
| `CODE_COMPOSE_V2_TASK_ID` | 同 `PAGE_NAME` | 任务目录名，非法路径字符会替换为 `-` |
| `CODE_COMPOSE_V2_WORK_DIR` | `<PROJECT_ROOT>/.code-compose-v2/<TASK_ID>` | 显式覆盖任务工作目录 |
| `COMPOSE_ACTIVITY` | 自动查找 `TestActivity` | 指定测试 Activity，格式为 `applicationId/.Activity` 或 `applicationId/full.Activity` |
| `COMPOSE_ACTIVITY_MODE` | `existing` | `launcher` 要求 MAIN/LAUNCHER；`existing` 允许已有测试 Activity |
| `COMPOSE_INSTALL_COMMAND` | `./gradlew installDebug` | 命令行构建安装命令 |
| `COMPOSE_START_ARGS` | 无 | 追加给 `am start` 的页面路由参数，例如 `--es codeComposePage NavigationRevisePage` |
| `COMPOSE_REFERENCE_MANIFEST` | 无 | 主页面和通用状态片段的 JSON 清单 |
| `COMPOSE_RESOURCE_MODE` | `reuse` | `reuse` 优先 code-image；`copy` 先从设计包复制；`existing` 只接受显式映射 |
| `COMPOSE_RESOURCE_MAP` | 无 | 设计图片文件到现有 `R` 资源的映射 |
| `ADB_SERIAL` | `emulator-5554` | 验证目标模拟器 |
| `VALIDATE_PIXEL_PASS` | `0.95` | 整页像素相似度阈值 |
| `VALIDATE_STRUCT_PASS` | `0.95` | 元素边界通过率阈值 |
| `VALIDATE_SPOT_PASS` | `0.8` | 局部抽查通过率阈值 |
| `VALIDATE_TOL_XY` | `4` | 元素位置容差，设计 px |
| `VALIDATE_TOL_WH` | `4` | 普通元素尺寸容差，设计 px |
| `VALIDATE_TOL_TEXT_WH` | `6` | 文本尺寸容差，设计 px |
| `VALIDATE_SPOT_DIST` | `0.18` | 局部平均色差阈值 |
| `VALIDATE_READY_ATTEMPTS` | `10` | 等待 `testTag` 出现的最多轮数 |
| `VALIDATE_READY_INTERVAL_MS` | `200` | 两轮就绪检查间隔 |

以下变量不再支持：

- `DESIGN_WIDTH`
- `DESIGN_HEIGHT`
- `DP_PER_PX`
- `Z_STRATEGY`

## 全屏测试 Activity

优先复用项目已有 `TestActivity.kt`：

1. 继承项目已有的全屏 Compose Activity 封装。
2. Manifest 使用 `FullScreenTheme` 和 `screenOrientation="landscape"`。
3. `InitView()` 内只调用一次 `BaseV3Page { 生成页面() }`。
4. 默认从源 Manifest 查找名称以 `TestActivity` 结尾的 Activity，并从同名 Gradle 模块读取 `applicationId` 与 `namespace`。
5. 指定其他页面时设置 `COMPOSE_ACTIVITY`；后续命令直接复用解析结果，不重复扫描项目。
6. 不创建第二套测试 Activity，不在生成页面内部再次添加尺寸缩放包装。

任务开始时由 `run.js` 扫描一次 Manifest，并写入：

```text
<PROJECT_ROOT>/.code-compose-v2/<PAGE_NAME>/out/runtime-context.json
```

后续脚本只读取该文件。

文件至少包含：

```json
{
  "taskId": "NavigationRevisePage",
  "pageName": "NavigationRevisePage",
  "packageName": "com.example.app",
  "activity": "com.example.app/com.example.app.TestActivity",
  "activityClass": "com.example.app.TestActivity"
}
```

指定其他测试 Activity：

```bash
export COMPOSE_ACTIVITY="com.example.app/.compose.activity.SpecificTestActivity"
```

## 参考清单

主页面和附加状态片段使用：

```json
{
  "primary": { "zip": "/绝对路径/主页面.zip", "scope": "primary-page" },
  "fragments": [
    { "zip": "/绝对路径/状态片段.zip", "scope": "state-reference" }
  ]
}
```

只有 `primary-page` 参与整页视觉验收。`state-reference` 只提供局部状态和行为证据，不追加到主页面坐标树中。

## 命令

```bash
node <技能目录>/scripts/run.js /绝对路径/设计包.zip
```

该命令完成：

1. 单次 Activity/Manifest 检查。
2. 解压设计包。
3. 单次 DOM 解析和原始截图。
4. 生成 Compose 页面。

代码有改动时，先执行安装脚本：

```bash
export COMPOSE_INSTALL_COMMAND="./gradlew :app:installDebug"
node <技能目录>/scripts/install-app.js
```

然后执行验证：

```bash
node <技能目录>/scripts/compose-validate.js
```

指定单次测试页面时可直接传入 Activity 组件：

```bash
node <技能目录>/scripts/compose-validate.js \
  "com.example.app/.compose.activity.SpecificTestActivity"
```

命令参数只覆盖本次验证，不修改 `runtime-context.json` 中缓存的默认 `TestActivity`。

如果 TestActivity 通过 Intent 路由目标页面：

```bash
export COMPOSE_START_ARGS="--es codeComposePage NavigationRevisePage"
node <技能目录>/scripts/compose-validate.js
```

TestActivity 可使用稳定的路由参数：

```kotlin
val targetPage = intent.getStringExtra("codeComposePage")
```

由 TestActivity 根据 `targetPage` 选择页面，不在每次验收前修改默认状态。

分阶段命令：

```bash
DESIGN_DIR="/绝对路径/解压目录" node <技能目录>/scripts/normalize.js
DESIGN_DIR="/绝对路径/解压目录" node <技能目录>/scripts/html-to-compose.js
node <技能目录>/scripts/compose-validate.js
```

脚本测试：

```bash
npm test --prefix <技能目录>/scripts
```

## 运行边界

- 不得点击 IDE Run 或 Apply Changes 刷新应用；代码变更后通过命令行 Debug 安装任务完成部署。
- `compose-validate.js` 只读取缓存并用 ADB 启动 Activity，不重复解析包名，也不执行构建或安装。
- 不修改模拟器 `wm size`、`wm density`、旋转锁定或系统栏。
- 使用 `adb shell am start -W` 和短轮询等待页面标签，不轮询固定长等待。
- 验证失败时返回非零退出码，并保留统一报告和差异图。
