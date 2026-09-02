# 缓存与设计解析

## Artifact 结构

```text
<project>/.code-lanhu-compose/<zip-stem>-<md5前6位>/
├── source.json
├── pipeline.json
├── dom.json
├── 设计解析.json
├── images.json
├── entry-selection.json        # 仅多 HTML 已明确选择时存在
├── needs-user-input.json       # 仅暂停等待确认时存在
├── design-server-source/       # 安全解压的本地设计页缓存
├── logs/
└── runs/
    ├── 设计截图.png
    ├── 应用截图.png
    └── 应用截图_1.png
```

目录名便于人读，完整 `sourceMd5` 才是身份。`source.json`、`pipeline.json`、`dom.json`、`设计解析.json` 和 `images.json` 都要绑定同一个完整 MD5；不同完整 MD5 即使前六位碰撞也不得复用内容。

## 缓存命中矩阵

| 产物 | 复用条件 | 失效后的动作 |
|---|---|---|
| `source.json` / `dom.json` | ZIP 完整 MD5 一致，DOM 文件可解析 | 重新 inspect/parse-dom |
| 静态服务解压目录 | MD5 标记一致；每个文件存在、尺寸一致且无符号链接 | 重新安全解压 |
| `设计解析.json` | MD5、版本 5、viewport/DPR、paint order、根节点和设计 PNG 内容 Hash 全部匹配 | 同一浏览器页重新采集与截图 |
| 图片导入记录 | 源图 MD5 一致，记录的项目资源仍真实存在 | 仅重新调用缺失项的 `$code-image` |
| Compose 生成 | 输入一致且新源码 Hash 与目标文件一致 | 不写文件，返回 `changed:false` |
| 编译 | 当前 Compose、目标模块源码、图片资源、图片清单、Gradle 配置和 task 的完整指纹等于最近成功编译指纹 | 返回 `unchanged`，不调用 Gradle |

同一进程内的文件 MD5 以绝对路径、inode、size、mtime 和 ctime 为缓存键；文件任一身份字段变化都重新计算。缓存最多保留 64 项，避免长进程无界增长。

相同 ZIP 改变目标 Compose 文件时，DOM、浏览器解析和设计截图仍是来源证据，可以复用；`pipeline.json` 必须回到 `inspected`，清除旧目标的 preflight、资源生成和编译绑定，并在 `targetHistory` 记录旧目标。

## DOM IR

`parse_html_dom.py` 使用 HTML 解析器保存整个文档，不只抽取 class：

- `nodeId`、`parentId`、`childrenIds`；
- 标签、完整属性、原始 class token；
- 直接文本、注释和 doctype；
- `img/src/srcset`、CSS URL 等经过 ZIP 边界校验的本地资源引用。

浏览器采集前，固定脚本按原始起始标签顺序注入 `data-code-lanhu-node-id`。该属性只写入服务缓存中的隐藏入口文件，不修改 ZIP 或 `dom.json`。浏览器自动插入 `tbody`、规范化缺失标签或调整 DOM 层级时，仍按该属性与 DOM IR 对齐；重复、缺失或标签冲突立即失败。

## `设计解析.json` 版本 5

版本 5 至少记录：

- 来源名称、路径、完整 MD5、入口 HTML 与 CSS；
- 根选择器、根 `nodeId`、根边界和设计画布；
- 浏览器 user agent、viewport 与 DPR；
- 每个稳定 `nodeId` 的最终 bounds、可见性、有效祖先透明度和 computed style；
- 每个节点和直接文本 Range 的 Chrome 实际 `paintOrder`、bounds 与最终文字样式；
- `<img>` 的 `currentSrc`、天然尺寸、最终 bounds 和 `objectFit`；
- 可见伪元素元数据；
- 同一页面实例生成的 `runs/设计截图.png` 及其 MD5。

浏览器禁用 CSS 动画/transition，等待 `document.fonts.ready` 和全部图片完成/解码，再比较稳定 nodeId 的 bounds、关键样式与 `currentSrc`，连续三帧一致才采集。布局采集与截图必须复用同一 browser/page，避免二次启动产生字体、DPR、响应式资源或时序差异。viewport/DPR 是缓存键的一部分。

## 图片清单与解压安全

`import_zip_images.py` 拒绝绝对路径、`..`、重复规范化路径、异常单文件/总解压大小、异常压缩比、预先存在的符号链接父目录或目标。每张图片按内容 MD5 去重；无位图设计合法写入 `images: []`。

每项 `images.json` 至少保存 `sourcePath`、内容 `md5`、真实 `outputPath`、`outputName` 和资源清单路径。项目级 `$code-image` 资源清单固定为 `.code-image/image.json`，每个成功批次会覆盖其记录；artifact 自身的 `images.json` 仍按设计 ZIP 独立保存。生成器只接受目标 Compose 模块中仍存在的输出文件，不根据旧记录或文件名猜资源。固定链路复用 artifact 私有解压目录，并在一个 Python 进程内批量调用 `$code-image` 的规划/落盘 API。
