# 配置与运行

在目标 Android 项目根目录执行。所有脚本的临时文件、截图、JSON 报告和经验状态默认写入：

```text
<PROJECT_ROOT>/.code-html-compose/
```

个人技能目录只保存脚本和文档；不得在其中保存设计包、图片、APK、`node_modules` 或执行产物。

## 执行前置检查

技能会在总入口以及直接 Compose 生成/验收入口读取 `COMPOSE_ACTIVITY`，定位当前生成布局实际使用的 Activity 或 Activity-alias，并只检查该声明自己的同一个 `<intent-filter>` 是否同时包含：

这里的“启动标签”指 Launcher intent-filter，不是 `android:launchMode` 属性。

```xml
<action android:name="android.intent.action.MAIN" />
<category android:name="android.intent.category.LAUNCHER" />
```

未配置、未找到目标 Activity 或缺少标签时，脚本会提示用户并以失败状态停止，不会用其他 Launcher Activity 替代，也不会创建新的 Activity、补写 `MAIN`/`LAUNCHER` 标签、编译、安装或启动模拟器。通过前置检查后，横向设计稿只会在已找到的目标 Activity 源声明上写入或更新 `android:screenOrientation="landscape"`。

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
| `CHROME_BIN` | macOS Chrome 路径 | Puppeteer 使用的 Chrome 可执行文件 |
| `VALIDATE_STRUCT_PASS` | `0.95` | 结构通过率阈值 |
| `VALIDATE_SPOT_PASS` | `0.8` | 局部抽查通过率阈值 |

设计稿必须校验为 `1334px × 750px`。不得从 CSS、目录名或其他来源推断并替换尺寸；校验不一致时流程直接失败。

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
