# 固定编排链路契约

`scripts/lanhu_pipeline.py` 是本 Skill 唯一的流程入口。它把一次蓝湖还原拆成可重放的阶段，并在 `.code-lanhu-compose/<name>-<md5前6位>/pipeline.json` 保存状态。压缩包的完整 `sourceMd5` 是唯一输入身份；输入变化时必须重新 `inspect`，不能沿用旧状态。相同 MD5 的 `inspect` 直接返回已有阶段，不重复运行 ZIP 检查和 `detect_repeated_blocks.py`，也不重置状态；首次检查才把尺寸差不超过 `2` 的重复背景卡片写入 `repeated-block-candidates.json`。

默认入口是 `run-fixed`。它由 Python 自动串联完整 DOM 解析、设计服务/浏览器采集、资源导入、Compose 代码生成、Gradle 任务发现和编译；模型不再逐个选择这些子命令，也不再负责首稿结构转换。

## 阶段与命令

```text
inspect/parse-dom -> validate -> preflight -> assets -> generate-compose -> compile -> package-debug
        -> install-k80 -> screenshot-k80 -> normalize-screenshot -> compare-screenshots -> mark-diff -> complete
                                      \-> repair（最多三轮后回到 compile）
```

设计稿浏览器采集与截图是 `inspect` 后可执行的独立证据生命周期，不改变 Android 编译阶段：

```text
start-design-server -> 采集设计（缓存未命中时写入设计解析.json，并首次保存 runs/设计截图.png）
                    -> screenshot-design（登记并停止服务）
                    \-> stop-design-server（采集失败时清理）

完整设计缓存命中时，`start-design-server` 与 `采集设计` 都返回 `cacheHit: true`，不会启动静态服务、解压 ZIP 或启动浏览器；仍可调用 `screenshot-design` 登记公共设计图。
```

每个阶段都必须使用脚本子命令，阶段不能跳过。完整 DOM、浏览器采集、资源 Hash、图片清单、`assets` 和 `generate-compose` 均由 Python 固定执行；生成器只读取 `dom.json`、`设计解析.json`、`images.json` 和目标 package 声明。`preflight` 根据目标 Compose 路径和 `gradlew tasks --all` 自动确定模块的 Debug Kotlin 任务，`compile` 只能复用状态中的任务，`package-debug` 再由该任务推导同变体 `assemble` 任务。只有出现多个 Debug variant 或无法识别时才暂停请求用户；禁止模型传入临时 Gradle task。Gradle 在项目根目录优先运行 `./gradlew`（仅 Wrapper 缺失且系统存在 `gradle` 时回退）；设备操作只接受 `adb -s <serial>` 的固定探针、安装和截图命令。`install-k80` 只接受当前 Compose Hash 对应且时间戳不早于 Compose 文件的 `package-debug` 产物。

`validate`、`mark-generated` 和 `compile` 会自动检查目标 Compose 源码中的 `padding(...)` 参数；发现负值时在生成或编译阶段立即停止，并要求改用 `Modifier.offset` 或父级布局表达跨边界位置，保留负位移语义并避免运行时 `PaddingElement` 崩溃。

常用入口：

```bash
python3 scripts/lanhu_pipeline.py run-fixed --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py inspect --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py parse-dom --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py start-design-server --zip <zip> --project-root <project>
# 采集浏览器最终布局，并写入本次 ZIP 的 设计解析.json：
python3 scripts/lanhu_pipeline.py 采集设计 --zip <zip> --project-root <project>
# 从采集结果的 screenshotPath 取得 runs/设计截图.png 后：
python3 scripts/lanhu_pipeline.py screenshot-design --zip <zip> --project-root <project> --image <artifact>/runs/设计截图.png
# 若浏览器操作失败，仍必须执行：
python3 scripts/lanhu_pipeline.py stop-design-server --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py validate --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py preflight --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py assets --zip <zip> --project-root <project> --compose <Compose.kt> --apply
python3 scripts/lanhu_pipeline.py generate-compose --zip <zip> --project-root <project> --compose <Compose.kt>
# 旧 artifact 兼容检查（新流程不调用，不用于生成首稿）
python3 scripts/lanhu_pipeline.py mark-generated --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py compile --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py package-debug --zip <zip> --project-root <project> --apk <apk>
python3 scripts/lanhu_pipeline.py install-k80 --zip <zip> --project-root <project> --serial emulator-5554 --expected-avd K80 --apk <apk>
python3 scripts/lanhu_pipeline.py screenshot-k80 --zip <zip> --project-root <project> --serial emulator-5554 --expected-avd K80
python3 scripts/normalize_compare_screenshot.py \
  --design <artifact>/runs/设计截图.png \
  --app <artifact>/runs/应用截图_1.png \
  --output <artifact>/runs/应用截图_归一化.png \
  --mode fill
python3 scripts/lanhu_pipeline.py compare-screenshots --zip <zip> --project-root <project> --app <artifact>/runs/应用截图_归一化.png
# 已完成 compare-screenshots 时传入报告；省略 --report 会自动执行 compare-screenshots：
python3 scripts/lanhu_pipeline.py mark-diff --zip <zip> --project-root <project> --outcome pass
python3 scripts/lanhu_pipeline.py complete --zip <zip> --project-root <project>
```

截图与设计图宽高比不一致时，必须先运行 `normalize_compare_screenshot.py`；`fill` 模式分别重采样横纵尺寸，`fit` 模式必须显式传入有效画布的 `--crop x,y,width,height`。原始截图不得覆盖。`compare-screenshots --app` 只接受当前 artifact/runs 内的归一化截图。

`compare-screenshots` 只调用 `$code-image` 的独立 `scripts/compare_images.py`，不复制图片算法，也不修改 Compose。它把设计图、显式归一化 App 截图和 `diff.json` 绑定到本次 artifact；模型读取报告后再选择 `repair`、`pass` 或 `stop`。

## 模型决策契约

模型遇到需要语义判断的地方，只能通过 `record-decision --decision decision.json` 记录以下动作之一：

```json
{
  "action": "apply_patch",
  "target": "app/src/main/java/.../Test7Page.kt",
  "patch": {"kind": "replace", "old": "...", "new": "..."},
  "evidence": ["compile: receiver mismatch at line 243"]
}
```

允许的 `action` 为 `apply_patch`、`continue`、`stop`、`ask_user`。`apply_patch` 的目标只能是项目内相对路径，补丁必须是 JSON 对象；脚本不执行补丁，也不执行模型提供的 shell。模型使用 `apply_patch` 工具完成真实编辑，再调用下一个固定阶段。

当证据不足以区分多个布局语义、资源映射或业务行为时，提交：

```json
{
  "action": "ask_user",
  "question": "该节点同时存在 8dp 与 12dp 间距，是否以 computed-style 的 12dp 为准？",
  "evidence": ["..."]
}
```

脚本会写入 `needs-user-input.json` 并以退出码 `2` 暂停。没有用户确认，不得用猜测推进后续阶段。

## 可进化边界

规则、模板和测试样例可以版本化演进，但必须先新增回归样例，再修改脚本或引用文档；每次变更后运行脚本单元测试、官方 `quick_validate.py` 和 `check_and_publish.sh`。脚本不得自修改，也不得为单个页面临时复制出同职责的第二套编排器。
