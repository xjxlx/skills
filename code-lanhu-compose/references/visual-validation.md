# 视觉验证闭环

## 证据目录

```text
<artifact>/runs/
├── 设计截图.png
├── 应用截图.png
├── 应用截图_1.png
├── 应用截图_归一化.png
├── diff.json
├── diff-mask.png
├── diff-heatmap.png
└── diff-overlay.png
```

不创建时间戳子目录。设计图同一来源只保留一个公共基准；App 截图按后缀递增，永不覆盖原始证据。`pipeline.json` 记录最近一次截图和对比输入。

## 设计截图

设计缓存未命中时，固定脚本：

1. 安全解压到 artifact 内的本地服务缓存；
2. 注入稳定 DOM ID 并绑定 `127.0.0.1` 随机端口；
3. 在本机 Chrome 等待字体、图片和布局稳定；
4. 在同一 page 采集最终事实并按根节点截图；
5. 原子写入版本 5 的 `设计解析.json`、截图 MD5 并回收服务。

根节点候选会过滤 script/noscript/template 和零 bounds 节点；唯一视觉根使用其稳定 `data-code-lanhu-node-id` selector，多个顶层视觉兄弟使用完整 `body`。viewport 和 DPR 会写入证据并参与缓存键；响应式设计通过 `run-fixed --viewport-width <px> --viewport-height <px> --dpr <倍数>` 改变环境并强制重新采集。

## App 截图有效性

优先使用 `test-android-apps:android-emulator-qa` 做页面启动与稳定性验证。回退到本 Skill 的 ADB 命令时：

- 始终指定 `adb -s <serial>`，并核验项目要求的 AVD 名；
- 先确认目标 Activity resumed、UI 树/页面标识正确、加载与动画已稳定；
- 确认语言、字体缩放、density、主题、测试数据和滚动位置；
- 避免键盘、Toast、弹窗和系统过渡遮挡。

`screenshot-k80` 只负责设备身份与 PNG 完整性：截图不可解码、不是 PNG 或尺寸无效时删除该文件并保持原状态。它不会判断截图内容是不是目标页面，因此页面就绪证据仍需由 QA 流程或调用方记录。

## 归一化后再比较

保留原始 App 截图，随后运行：

```bash
python3 scripts/normalize_compare_screenshot.py \
  --design <artifact>/runs/设计截图.png \
  --app <artifact>/runs/应用截图_1.png \
  --output <artifact>/runs/应用截图_归一化.png \
  --mode fill
```

- `fill`：明确允许横纵独立缩放到设计画布，适用于全屏填充契约。
- `fit --crop x,y,width,height`：裁剪区域宽高比必须与设计稿在 0.1% 内一致，再做等比重采样；不一致立即失败。
- 输出路径不能等于设计图或 App 原图；写入使用同目录临时文件和原子替换。
- 同名 `.normalization.json` sidecar 保存输入/输出 MD5、原尺寸、有效区域、`scaleX/scaleY` 和宽高比误差；`compare-screenshots` 会验证这份绑定。

系统栏、安全区或信箱留白必须通过真实 crop 处理。禁止用 `--aspect-tolerance` 放行不同宽高比，也禁止直接覆盖原图。

## 对比与修正顺序

```bash
python3 scripts/lanhu_pipeline.py compare-screenshots \
  --zip <zip> --project-root <project> \
  --app <artifact>/runs/应用截图_归一化.png
```

命令调用 `$code-image` 的独立算法，生成 `diff.json`、遮罩、热力图和叠加图，并将当前 `sourceMd5`、设计图、App 图和 metrics 注册到状态。`mark-diff` 只接受这份已注册且字段完整的报告。

按以下顺序修正，避免局部数值掩盖根因：

1. 根边界、系统栏、整体横纵缩放；
2. 主要容器和背景/资源覆盖；
3. 节点 bounds、层叠、裁剪和遮挡；
4. 文本基线、字号、字重、行高、字距；
5. 颜色、透明度、圆角、边框、阴影等细节。

每轮只改有 bounds、编译错误或差异图支持的属性，并重新执行同一 variant 的编译、打包、安装、截图和比较。

## 三轮上限与提前停止

初稿不计修正次数，最多三轮。满足任一条件立即停止：

- 关键布局、文字和资源达到可接受范围；
- 任意一次已完成的修正没有改善关键 metrics 或证据图；
- 三轮用尽；
- 缺失字体、图片、数据、页面入口或设计状态；
- 编译、设备或外部依赖阻塞；
- 继续需要破坏公共组件或修改未授权文件。

停止时报告当前指标、剩余差异和具体原因。只有 `pass` 可进入 `complete`；`stop` 不是成功完成。
