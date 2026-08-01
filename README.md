# Skills

个人Skills 合集。完整目录、依赖关系和发布状态见
[SKILLS_CATALOG.md](./SKILLS_CATALOG.md)。

## 恢复单个 Skill

```bash
tmp=$(mktemp -d)
git clone --depth 1 https://github.com/xjxlx/codex-skills.git "$tmp/codex-skills"
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R "$tmp/codex-skills/code-analyzer" "${CODEX_HOME:-$HOME/.codex}/skills/"
rm -rf "$tmp"
```

将 `code-analyzer` 替换为需要恢复的 skill 名称。若目标已存在，请先确认本地修改，
再删除旧目录或使用下面的恢复脚本加 `--force`。

## 恢复全部个人 Skills

```bash
tmp=$(mktemp -d)
git clone --depth 1 https://github.com/xjxlx/codex-skills.git "$tmp/codex-skills"
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
for skill in code-analyzer code-normalize github-manager java-to-kotlin skill-common; do
  rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/$skill"
  cp -R "$tmp/codex-skills/$skill" "${CODEX_HOME:-$HOME/.codex}/skills/"
done
rm -rf "$tmp"
```

恢复后重启 Codex。

## 使用恢复脚本

已安装 `github-manager` 时，可以直接执行：

```bash
~/.codex/skills/github-manager/scripts/restore_skills.sh --skill code-analyzer
~/.codex/skills/github-manager/scripts/restore_skills.sh --all
~/.codex/skills/github-manager/scripts/restore_skills.sh --all --force
```

仓库：https://github.com/xjxlx/codex-skills
