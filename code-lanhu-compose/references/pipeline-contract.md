# 固定编排链路契约

`scripts/lanhu_pipeline.py` 是本 Skill 唯一的流程入口。它把一次蓝湖还原拆成可重放的阶段，并在 `.code-lanhu-compose/<name>-<sha6>/pipeline.json` 保存状态。压缩包的完整 `sourceSha256` 是唯一输入身份；输入变化时必须重新 `inspect`，不能沿用旧状态。

## 阶段与命令

```text
inspect -> validate -> preflight -> assets -> mark-generated -> compile
        -> install-k80 -> screenshot-k80 -> mark-diff -> complete
                                      \-> repair（最多三轮后回到 compile）
```

每个阶段都必须使用脚本子命令，阶段不能跳过。`assets` 只调用现有的 `import_zip_images.py`；Gradle 只接受明确的 `:module:task`；设备操作只接受 `adb -s <serial>` 的固定探针、安装和截图命令。

常用入口：

```bash
python3 scripts/lanhu_pipeline.py inspect --zip <zip> --project-root <project>
python3 scripts/lanhu_pipeline.py validate --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py preflight --zip <zip> --project-root <project> --task :app:compileDebugKotlin
python3 scripts/lanhu_pipeline.py assets --zip <zip> --project-root <project> --compose <Compose.kt> --apply
python3 scripts/lanhu_pipeline.py mark-generated --zip <zip> --project-root <project> --compose <Compose.kt>
python3 scripts/lanhu_pipeline.py compile --zip <zip> --project-root <project> --task :app:compileDebugKotlin
python3 scripts/lanhu_pipeline.py install-k80 --zip <zip> --project-root <project> --serial emulator-5554 --expected-avd K80 --apk <apk>
python3 scripts/lanhu_pipeline.py screenshot-k80 --zip <zip> --project-root <project> --serial emulator-5554
python3 scripts/lanhu_pipeline.py mark-diff --zip <zip> --project-root <project> --report <diff.json> --outcome pass
python3 scripts/lanhu_pipeline.py complete --zip <zip> --project-root <project>
```

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
