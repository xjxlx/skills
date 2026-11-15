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
- 应用已经通过 IDE Running、Run 或 Apply Changes 刷新。
- `scripts/node_modules` 已存在且依赖有效。正常页面任务不执行 `npm ci`；依赖缺失时先通知用户。

## 必填变量

```bash
export PROJECT_ROOT="$PWD"
export COMPOSE_KOTLIN_DIR="app/src/main/java/com/example/app/ui/generated"
export COMPOSE_RES_DIR="app/src/main/res"
export COMPOSE_PACKAGE="com.example.app.ui.generated"
export COMPOSE_R_IMPORT="import com.example.app.R"
export COMPOSE_IMAGE_IMPORTS=$'import com.example.widget.ImageItem\nimport com.example.widget.ImageParameter'
export COMPOSE_ACTIVITY="com.example.app/.TestActivity"
export COMPOSE_ACTIVITY_MODE="existing"
```

`COMPOSE_TEXT_IMPORT` 必须由目标项目提供：

```bash
export COMPOSE_TEXT_IMPORT="import com.example.widget.TextItem"
```

## 可选变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `CODE_COMPOSE_V2_WORK_DIR` | `<PROJECT_ROOT>/.code-compose-v2` | 运行产物目录 |
| `PAGE_NAME` | `GeneratedPage` | 生成的 Kotlin 文件和 Composable 名 |
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
4. 需要 adb 启动时保留 `MAIN + LAUNCHER`；若项目已有真实导航入口，可设置 `COMPOSE_ACTIVITY_MODE=existing`。
5. 不创建第二套测试 Activity，不在生成页面内部再次添加尺寸缩放包装。

任务开始时由 `run.js` 扫描一次 Manifest，并写入：

```text
<PROJECT_ROOT>/.code-compose-v2/out/runtime-context.json
```

后续脚本只读取该文件。

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

生成后通过 IDE 刷新应用，再执行：

```bash
node <技能目录>/scripts/compose-validate.js
```

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

- 生成与验证脚本不执行 `assembleDebug`、`installDebug` 或 `adb install -r`。
- 不修改模拟器 `wm size`、`wm density`、旋转锁定或系统栏。
- 不轮询固定 6 秒；只通过 `am start -W` 和短轮询等待页面标签。
- 验证失败时返回非零退出码，并保留统一报告和差异图。
