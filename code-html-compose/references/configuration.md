# 配置与运行

在目标 Android 项目根目录执行。所有脚本的临时文件、截图、JSON 报告和经验状态默认写入：

```text
<PROJECT_ROOT>/.code-html-compose/
```

个人技能目录只保存脚本和文档；不得在其中保存设计包、图片、APK、`node_modules` 或执行产物。

## 执行前置检查

技能会在总入口以及直接 Compose 生成/验收入口读取 `COMPOSE_ACTIVITY`，定位当前页面实际使用的 Activity 或 Activity-alias。默认只接受该声明自己的同一个 `<intent-filter>` 同时包含：

这里的“启动标签”指 Launcher intent-filter，不是 `android:launchMode` 属性。

```xml
<action android:name="android.intent.action.MAIN" />
<category android:name="android.intent.category.LAUNCHER" />
```

已有页面 Activity 不是 Launcher 时，可以显式配置 `COMPOSE_ACTIVITY_MODE=existing`；这仅允许复用既有声明，脚本不会创建 Activity、补写 `MAIN`/`LAUNCHER`，也不会绕过 `exported=false` 的启动限制。目标 Activity 未配置或未找到时仍会停止。通过前置检查后，横向设计稿只会在已找到的目标 Activity 源声明上写入或更新 `android:screenOrientation="landscape"`。

## 首次安装依赖

```bash
npm ci --prefix <技能目录>/scripts
```

## 必填变量

```bash
export PROJECT_ROOT="$PWD"
export COMPOSE_KOTLIN_DIR="app/src/main/java/com/example/app/ui/generated"
export COMPOSE_RES_DIR="app/src/main/res"
export COMPOSE_PACKAGE="com.example.app.ui.generated"
export COMPOSE_R_IMPORT="import com.example.app.R"
export COMPOSE_IMAGE_IMPORTS=$'import com.example.widget.ImageItem\nimport com.example.widget.ImageParameter'
export COMPOSE_ACTIVITY="com.example.app/.MainActivity"
# 已有非 Launcher 页面时使用 existing；默认 launcher 会严格检查 MAIN + LAUNCHER
export COMPOSE_ACTIVITY_MODE="launcher"
# 主页面 + 行为状态片段的 JSON 清单
export COMPOSE_REFERENCE_MANIFEST="$PROJECT_ROOT/.code-html-compose/references.json"
# existing 模式不复制 ZIP 图片，直接引用 code-image 已导入资源
export COMPOSE_RESOURCE_MODE="existing"
export COMPOSE_RESOURCE_MAP="$PROJECT_ROOT/.code-html-compose/resource-map.json"
```

`COMPOSE_IMAGE_IMPORTS` 由生成的 Kotlin 直接插入图片组件所需的 import。若目标项目不使用 `ImageItem` / `ImageParameter`，先调整 `html-to-compose.js` 的图片模板及测试，再执行生成。

## 可选变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `DESIGN_DIR` | 一键流程自动传入 | 直接包含 `index.html` 的解压设计目录 |
| `DESIGN_WIDTH` / `DESIGN_HEIGHT` | 禁止设置 | 本技能固定使用 `1334 × 750`；尺寸不匹配时应停止并报告，不得覆盖基准 |
| `CODE_HTML_COMPOSE_WORK_DIR` | `<PROJECT_ROOT>/.code-html-compose` | 自定义运行产物目录 |
| `PAGE_NAME` | `Test1Page` | 生成的 Kotlin 文件和 Composable 名 |
| `DP_PER_PX` | `0.5` | 固定按 2 倍 HTML 设计稿换算 Android dp；不得改为其他倍率 |
| `APK_PATH` | `app/build/outputs/apk/debug/app-debug.apk` | 待安装 APK 路径 |
| `ADB_SERIAL` | `emulator-5554` | 模拟器序列号 |
| `COMPOSE_ACTIVITY_MODE` | `launcher` | `launcher` 严格要求目标 Activity 自带 Launcher；`existing` 允许复用已有非 Launcher Activity，但不会替它创建启动入口 |
| `COMPOSE_REFERENCE_MANIFEST` | 无 | 主页面和行为片段的 JSON 清单；主页面必须为 `scope=primary-page` |
| `COMPOSE_RESOURCE_MODE` | `copy` | `copy` 复制设计包图片；`existing` 要求每个图片文件在映射中对应已有 Android 资源 |
| `COMPOSE_RESOURCE_MAP` | 无 | JSON 资源映射，可直接写文件名到 `icon_xxx`、`R.mipmap.icon_xxx` 或 `@mipmap/icon_xxx` |
| `CHROME_BIN` | macOS Chrome 路径 | Puppeteer 使用的 Chrome 可执行文件 |
| `VALIDATE_STRUCT_PASS` | `0.95` | 结构通过率阈值 |
| `VALIDATE_SPOT_PASS` | `0.8` | 局部抽查通过率阈值 |

主页面设计稿必须校验为 `1334px × 750px`。参考清单中声明为 `vertical-list-state` 或 `popup-state` 的片段可以有不同 CSS 高度，但只能用于提取局部状态和行为，不能参与主页面尺寸校验。

横向设计稿依赖目标 Activity 的静态 `android:screenOrientation="landscape"` 配置，并要求用户先将模拟器旋转到横向。脚本只重启 Activity 和读取截图，不执行 `wm size`、`wm density`、`policy_control`、`accelerometer_rotation` 或 `user_rotation`，也不旋转截图数据；坐标校验按当前横屏截图实际尺寸缩放。若截图仍为竖屏，验收直接失败，请手动旋转模拟器后重试。

## 常用命令

```bash
node <技能目录>/scripts/run.js /绝对路径/设计包.zip

# 分阶段排查
DESIGN_DIR="/绝对路径/解压目录/设计目录" \
  node <技能目录>/scripts/normalize.js
DESIGN_DIR="$DESIGN_DIR" \
  node <技能目录>/scripts/iterate.js
DESIGN_DIR="$DESIGN_DIR" \
  node <技能目录>/scripts/html-to-compose.js
node <技能目录>/scripts/compose-validate.js
```

脚本测试：

```bash
npm test --prefix <技能目录>/scripts
```
