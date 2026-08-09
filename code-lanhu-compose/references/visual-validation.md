# 视觉验证闭环

## 证据目录

同一 ZIP 共用一个证据目录：

```text
<project>/.code-lanhu-compose/<zip-stem>-<md5前6位>/runs/
├── 设计截图.png
├── 应用截图.png
├── 应用截图_1.png
├── 差异.json
└── 差异_1.json
```

把公共设计截图复制到 `~/Downloads/设计截图.png`，最近一次 App 截图复制到 `~/Downloads/应用截图.png`。下载目录文件允许覆盖，`runs/` 内已有证据不得覆盖。

`runs/` 下不创建任何时间戳子目录。设计稿截图固定为 `设计截图.png`：同一 ZIP 首次采集后即作为公共基准图复用，后续采集不得重复截取。App 截图从 `应用截图.png` 开始按顺序递增为 `应用截图_1.png`、`应用截图_2.png`……；多轮修正不得覆盖已有截图。差异报告也直接放在 `runs/` 下，按 `差异.json`、`差异_1.json`……递增。

创建本目录前必须确认当前 ZIP 专属目录中的 `设计解析.json` 已完成，且其完整 `sourceMd5` 与当前 ZIP 一致；只有运行目录而没有设计解析文件的结果属于不完整证据，必须先回到设计解析阶段补齐。

## 设计稿截图

本地 `file://` 地址可能被 Codex 浏览器策略拒绝。仅在完整设计缓存未命中时，由固定管线启动仅本机可访问的静态服务；不能手动启动一个无法追溯的服务：

```bash
python3 scripts/lanhu_pipeline.py start-design-server --zip <zip> --project-root <project>
```

随后执行 `采集设计`。该命令使用本机 Chrome 等待页面资源完成，采集最终 DOM、计算样式与有效边界，写入 `设计解析.json`，并仅在公共设计图缺失时按其中的设计根节点自动保存 `runs/设计截图.png`。同一 ZIP 的完整缓存命中时，这两个命令均返回 `cacheHit: true`，不会启动服务或浏览器。

根节点选择器必须来自解析结果，`.page` 只是蓝湖常见示例。去掉预览外壳的缩小 `transform`，保留设计元素自身的 transform；固定 viewport、背景和 `deviceScaleFactor`。

截图保存后立即登记并回收服务；即使图片路径、选择器或浏览器操作失败，也必须执行 `stop-design-server`：

```bash
python3 scripts/lanhu_pipeline.py screenshot-design --zip <zip> --project-root <project> --image <artifact>/runs/设计截图.png
# 浏览器截图失败时改为执行：
python3 scripts/lanhu_pipeline.py stop-design-server --zip <zip> --project-root <project>
```

服务固定绑定 `127.0.0.1`，端口默认由系统自动分配。`screenshot-design` 会校验图片位于本次 artifact 的 `runs/` 目录且命名为 `设计截图.png`，随后停止脚本自身启动且已核验的 `http.server` PID；它不会终止用户手动启动的其他服务。

## App 截图

优先使用 `test-android-apps:android-emulator-qa`。回退到 ADB 时必须指定设备：

```bash
adb -s <serial> shell screencap -p /sdcard/lanhu_compose_screen.png
adb -s <serial> pull /sdcard/lanhu_compose_screen.png <artifact>/runs/应用截图.png
```

截图前必须完成启动稳定性检查：等待启动页/启动图标消失，确认目标 Activity 已处于 resumed 状态，并通过 UI 树、页面标识或稳定的目标节点确认目标页面已显示；连续两次检查结果一致后，才允许截图。空白加载态、启动图、首页或过渡动画截图必须标记为无效证据，不得用于视觉对比。

同时确认目标数据和滚动位置正确，动画已经稳定，并且没有键盘、Toast 或弹窗遮挡。把启动稳定性检查结果和目标页面标识写入本轮 `logs/`，便于追溯截图是否有效。

## 对齐后再比较

比较前统一：

- 有效内容裁剪区域。
- 画布宽高和缩放比例。
- 状态栏、导航栏及安全区处理。
- 背景色、透明通道和颜色空间。
- 设计状态、文本内容、语言、字体缩放和测试数据。

禁止直接比较两个未经归一化的整屏截图。

## 差异顺序

按以下顺序定位和修正：

1. 页面根边界、系统栏和整体缩放。
2. 容器层级、方向、尺寸和父级 padding/gap。
3. 子项位置、特殊 margin、对齐和图片裁剪。
4. 文本基线、字号、字重、行高和字距。
5. 颜色、透明度、圆角、边框、阴影和遮挡。

每轮生成结构化差异，至少记录区域、属性、设计值、App 值、偏差和证据截图。

## 三轮上限和停止条件

初次生成不计入修正次数，之后最多修正三轮。每轮都必须重新编译、安装或运行、截图并对比。

满足任一条件立即停止：

- 关键布局、文本和资源差异已达到可接受范围。
- 已完成三轮修正。
- 连续两轮没有改善或差异变大。
- 缺失字体、图片、测试数据或设计状态，无法可靠复现。
- 编译、设备、页面入口或外部依赖阻塞。
- 继续修正需要破坏公共组件或修改未授权文件。

停止时列出剩余差异和具体原因，不用猜测性代码填补信息缺口。
