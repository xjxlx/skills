# GitHub 发布工作流参考

## 仓库命名规范

- 单独仓库：`codex-skill-{skill-name}`（如 `codex-skill-code-analyzer`）
- 统一仓库：`codex-skills`（所有 skill 在子目录中）

## 调用时自动检测

各个人 Skill 按 `$skill-common` 的启动规则运行：

```bash
scripts/check_and_publish.sh
```

本 reference 只说明实现：脚本检测全部个人 skill，任一 hash 变化时调用
`publish_unified.sh`，全部无变化时不创建提交。

检测期间使用 `.check-and-publish.lock` 防止并发或嵌套调用重复发布；锁目录不参与 hash、
安全扫描和仓库同步。

## 首次发布流程

```
1. 安全扫描通过
2. git init（如未初始化）
3. 创建 .gitignore
4. 生成/更新 README.md
5. git add -A && git commit
6. gh repo create --public --source=. --push
7. 写入 .github-published 标记
8. push 成功后计算并保存 hash
```

## 更新发布流程

```
1. 安全扫描通过
2. hash 对比检测变更
3. 有变更：列出变更文件
4. git add -A && git commit（带变更摘要）
5. git push
6. 更新 .github-published 标记
7. push 成功后保存新 hash
```

## GitHub 代理与分支同步

当浏览器可以打开 GitHub，但 Git 的 `push` 或 `pull` 卡住、连接超时或出现
`HTTP2 framing` 错误时，先执行 `scutil --proxy` 检查系统代理。若 HTTP/HTTPS
代理已启用，使用实际代理地址显式执行 Git 操作：

```bash
git -c http.proxy=http://<代理地址>:<端口> fetch origin
git -c http.proxy=http://<代理地址>:<端口> pull --rebase origin main
git -c http.proxy=http://<代理地址>:<端口> push origin main
```

若推送提示 `fetch first` 或远端分支领先，先 `fetch`，再 `pull --rebase` 并解决冲突，确认本地历史正确后再推送。未经用户明确确认，不得使用 `--force` 覆盖远端提交；代理地址和端口必须以当前机器检测结果为准。

## 恢复流程

```
1. 浅克隆统一仓库到临时目录
2. 验证目标子目录存在 SKILL.md
3. 默认拒绝覆盖本地同名目录
4. 使用 --force 时先移动旧目录作为临时备份
5. 完整复制目标 skill，成功后删除备份
6. 删除临时仓库并提示重启 Codex
```

- 单个恢复：`scripts/restore_skills.sh --skill <name>`
- 全部恢复：`scripts/restore_skills.sh --all`
- 覆盖恢复：追加 `--force`
- 自举恢复：本地 `github-manager` 缺失时，使用仓库根 README 中的 Git 命令

## 提交信息规范

- 首次发布：`feat: initial release of {skill_name}`
- 更新：`update: {skill_name} (+N new, ~M modified, -D deleted)`
- 修复：`fix: {skill_name} - {description}`

## README.md 结构

```markdown
# {Skill Display Name}

{一句话描述}

## 功能

- 功能点 1
- 功能点 2

## 使用方法

（从 SKILL.md 提取关键信息）

## 依赖

- 其他 skill 依赖
- 系统依赖（如 gh CLI）

## 目录结构

（列出 scripts/, references/, assets/ 等）
```

## 常见问题

**Q: push 被拒绝？**
A: 确认远程仓库地址正确；若网页可访问但 Git 卡住，先按“GitHub 代理与分支同步”使用代理，再执行 `git pull --rebase origin main` 后重新 push。

**Q: 仓库已存在？**
A: 使用 `--repo-name` 参数指定不同的名称，或先删除已有仓库。

**Q: hash 对比总是报变更？**
A: 确认计算与检测使用同一脚本，并排除 `.DS_Store` 等系统文件。
