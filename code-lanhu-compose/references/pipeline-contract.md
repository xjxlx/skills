# 固定编排链路契约

`scripts/lanhu_pipeline.py` 是唯一编排器；状态写入本次 ZIP 的 `pipeline.json`，所有阶段绑定完整 `sourceMd5`。

## 状态机

```text
created → inspected → validated → preflight → assets_imported → generated → compiled
       → installed → screenshot → diffed → completed
                              ↖ repair（最多三轮）
```

`package-debug` 在 compiled 状态登记 APK，不伪造新阶段；APK 必须来自目标 Compose 模块的 `build/outputs/apk/`，安装前复核路径、Compose Hash 与 APK 内容 Hash。只有当前已注册的视觉报告 `outcome=pass` 才能 `complete`；`stop` 保留为未完成的证据终点。用户明确纠正方向后，可从 `stop` 运行 `restart-generation --reason ...`，复用同一来源证据并把修正计数归零。

## `run-fixed` 顺序

```text
inspect/parse-dom → validate → preflight → ensure_design_evidence → assets
                  → generate-compose → compile
```

- validate 与 preflight 必须先于浏览器和资源写入，错误项目/目标不产生昂贵副作用。
- preflight 从目标 Compose 路径确定模块，并从 `tasks --all` 找唯一 Debug Kotlin 任务；它只做任务发现，不在生成前重复执行完整编译。
- 设计缓存未命中时，布局采集与截图只启动一次浏览器；命中时不解压、不启动服务/浏览器。
- 图片清单、生成器、源码检查和 Gradle 均由 Python 调用；模型不能手工标记 generated。图片按内容 Hash 去重后单进程批量导入。
- 当前 Compose、目标模块源码、图片资源/清单、Gradle 配置和 task 的编译指纹与最近成功值一致时，热重跑返回 `unchanged`；任一输入变化都会失效下游证据并重新编译。

相同 ZIP、相同目标只复用当前阶段。相同 ZIP 换目标时，来源证据保留，目标绑定阶段重置为 `inspected`；禁止沿用旧模块 `preflightTask`。

## 常用命令

```bash
# 默认自动链路
python3 scripts/lanhu_pipeline.py run-fixed --zip <zip> --project-root <project> --compose <Compose.kt> \
  --viewport-width 1600 --viewport-height 900 --dpr 1

# 调试固定产物
python3 scripts/lanhu_pipeline.py inspect --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py parse-dom --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py generate-compose --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py status --zip <zip> --project-root <project>

# 构建与设备
python3 scripts/lanhu_pipeline.py compile --zip <zip> --project-root <project>
# 多 variant 暂停且用户明确选择后：
python3 scripts/lanhu_pipeline.py select-compile-task --zip <zip> --project-root <project> --task <报告中的候选>
# 多 HTML 暂停且用户明确选择后：
python3 scripts/lanhu_pipeline.py select-entry-html --zip <zip> --project-root <project> --html <ZIP内路径>
python3 scripts/lanhu_pipeline.py package-debug --zip <zip> --project-root <project> --apk <apk>
python3 scripts/lanhu_pipeline.py install-k80 --zip <zip> --project-root <project> --serial emulator-5554 --expected-avd K80 --apk <apk>
python3 scripts/lanhu_pipeline.py screenshot-k80 --zip <zip> --project-root <project> --serial emulator-5554 --expected-avd K80

# 视觉证据
python3 scripts/lanhu_pipeline.py compare-screenshots --zip <zip> --project-root <project> --app <normalized.png>
python3 scripts/lanhu_pipeline.py mark-diff --zip <zip> --project-root <project> --outcome pass
python3 scripts/lanhu_pipeline.py complete --zip <zip> --project-root <project>
```

设计服务的 `start-design-server`、`采集设计`、`screenshot-design`、`stop-design-server` 是诊断子命令；默认由 `run-fixed` 管理。服务固定绑定 `127.0.0.1`，无论登记成功失败都回收脚本启动的 PID。

## 错误与用户输入

- `PipelineError`：退出码 1，状态不越级，日志保留。
- `UserInputRequired`：退出码 2；尽力写入 `needs-user-input.json`，包含命令、问题、来源路径、完整 MD5 和时间。
- 预检失败、输入损坏、资源冲突或用户既有源码错误不进入自动修复。
- 生成模板产生的明确编译错误可在固定规则中修复，最多重跑同一任务三次；attempt 在运行外部命令前持久化，失败日志不会被覆盖。先补回归测试，不做页面特判。

`record-decision` 只接受 `ask_user`、`apply_patch`、`continue`、`stop`。补丁目标必须是项目内相对路径且是结构化 JSON；脚本只登记，不执行模型提供的 shell 或补丁。

## 发布门禁

脚本变更必须先有 RED 测试，再实现 GREEN；发布前运行：全部 `test_*.py`、Python 语法检查、官方 `quick_validate.py` 和凭据扫描。最后才执行 `$skill-common` 的 `check_and_publish.sh`，不能把发布脚本当测试门禁。
