# 配置与运行

在目标 Android 项目根目录执行。所有脚本的临时文件、截图、JSON 报告和经验状态默认写入：

```text
<PROJECT_ROOT>/.code-html-compose/
```

个人技能目录只保存脚本和文档；不得在其中保存设计包、图片、APK、`node_modules` 或执行产物。

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
| `CODE_HTML_COMPOSE_WORK_DIR` | `<PROJECT_ROOT>/.code-html-compose` | 自定义运行产物目录 |
| `PAGE_NAME` | `Test1Page` | 生成的 Kotlin 文件和 Composable 名 |
| `DP_PER_PX` | `0.5` | 设计 px 转 dp；@1x 设计图设为 `1` |
| `APK_PATH` | `app/build/outputs/apk/debug/app-debug.apk` | 待安装 APK 路径 |
| `ADB_SERIAL` | `emulator-5554` | 模拟器序列号 |
| `CHROME_BIN` | macOS Chrome 路径 | Puppeteer 使用的 Chrome 可执行文件 |
| `VALIDATE_STRUCT_PASS` | `0.95` | 结构通过率阈值 |
| `VALIDATE_SPOT_PASS` | `0.8` | 局部抽查通过率阈值 |

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
