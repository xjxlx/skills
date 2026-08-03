#!/usr/bin/env bash
# publish_unified.sh - 发布/更新统一仓库
# 用法: publish_unified.sh [--repo-name name] [--skills-root dir] [--repo-dir dir]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_ROOT="$HOME/.codex/skills"
UNIFIED_DIR="$SCRIPT_DIR/../codex-skills"
HASHES_FILE="$SCRIPT_DIR/../.hashes.json"
REPO_NAME="codex-skills"
EXCLUDE=(".system" "android-cli")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-name) REPO_NAME="${2:?--repo-name 缺少值}"; shift 2 ;;
    --skills-root) SKILLS_ROOT="${2:?--skills-root 缺少值}"; shift 2 ;;
    --repo-dir) UNIFIED_DIR="${2:?--repo-dir 缺少值}"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

command -v git >/dev/null || { echo "缺少 git" >&2; exit 2; }
command -v gh >/dev/null || { echo "缺少 gh CLI" >&2; exit 2; }
command -v rsync >/dev/null || { echo "缺少 rsync" >&2; exit 2; }
[[ -d "$SKILLS_ROOT" ]] || { echo "Skills 目录不存在: $SKILLS_ROOT" >&2; exit 2; }

echo "发布统一仓库: $REPO_NAME"
echo "源目录: $SKILLS_ROOT"
echo "目标目录: $UNIFIED_DIR"

"$SCRIPT_DIR/scan_all.sh" "$SKILLS_ROOT"

mkdir -p "$UNIFIED_DIR"
if [[ ! -d "$UNIFIED_DIR/.git" ]]; then
  git -C "$UNIFIED_DIR" init
  git -C "$UNIFIED_DIR" checkout -b main
fi

if ! git -C "$UNIFIED_DIR" remote get-url origin >/dev/null 2>&1; then
  if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
    OWNER=$(gh api user -q .login)
    git -C "$UNIFIED_DIR" remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
  else
    gh repo create "$REPO_NAME" --public --source="$UNIFIED_DIR" --remote=origin
  fi
fi

REPO_FULL=$(gh repo view "$(git -C "$UNIFIED_DIR" remote get-url origin)" \
  --json nameWithOwner -q .nameWithOwner)
UPDATED=()
NOCHANGE=()
MANAGED=()

is_excluded() {
  local candidate="$1"
  local excluded
  for excluded in "${EXCLUDE[@]}"; do
    [[ "$candidate" == "$excluded" ]] && return 0
  done
  return 1
}

for skill_dir in "$SKILLS_ROOT"/*/; do
  skill_name=$(basename "$skill_dir")
  is_excluded "$skill_name" && continue
  [[ -f "$skill_dir/SKILL.md" ]] || continue
  MANAGED+=("$skill_name")

  if ! "$SCRIPT_DIR/detect_changes.sh" "$skill_dir" "$HASHES_FILE" >/dev/null 2>&1 \
      && [[ -d "$UNIFIED_DIR/$skill_name" ]]; then
    NOCHANGE+=("$skill_name")
    continue
  fi

  echo "同步: $skill_name"
  mkdir -p "$UNIFIED_DIR/$skill_name"
  RSYNC_EXCLUDES=(
    --exclude='.git'
    --exclude='.github-published'
    --exclude='.hashes.json'
    --exclude='.allowlist'
    --exclude='.check-and-publish.lock'
    --exclude='.DS_Store'
    --exclude='__pycache__'
  )
  if [[ "$skill_name" == "github-manager" ]]; then
    RSYNC_EXCLUDES+=(--exclude='codex-skills' --exclude='SKILLS_CATALOG.md')
  fi
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$skill_dir" "$UNIFIED_DIR/$skill_name/"
  UPDATED+=("$skill_name")
done

# 清理不再管理的旧目录，仅处理包含 SKILL.md 的 skill 目录。
for target_dir in "$UNIFIED_DIR"/*/; do
  target_name=$(basename "$target_dir")
  [[ -f "$target_dir/SKILL.md" ]] || continue
  keep=0
  for managed_name in "${MANAGED[@]}"; do
    [[ "$target_name" == "$managed_name" ]] && keep=1
  done
  if [[ $keep -eq 0 ]]; then
    echo "移除非管理 skill: $target_name"
    rm -rf "$target_dir"
  fi
done
rm -rf "$UNIFIED_DIR/android-cli"

GITHUB_MANAGER_UNIFIED_REPO="$REPO_FULL" \
  "$SCRIPT_DIR/generate_catalog.sh" "$SKILLS_ROOT" "$UNIFIED_DIR/SKILLS_CATALOG.md"
cp "$UNIFIED_DIR/SKILLS_CATALOG.md" "$SCRIPT_DIR/../SKILLS_CATALOG.md"

cat > "$UNIFIED_DIR/README.md" << README
# Codex Skills

个人 Codex Skills 合集。完整目录、依赖关系和发布状态见
[SKILLS_CATALOG.md](./SKILLS_CATALOG.md)。

## 恢复单个 Skill

\`\`\`bash
tmp=\$(mktemp -d)
git clone --depth 1 https://github.com/$REPO_FULL.git "\$tmp/codex-skills"
mkdir -p "\${CODEX_HOME:-\$HOME/.codex}/skills"
cp -R "\$tmp/codex-skills/code-analyzer" "\${CODEX_HOME:-\$HOME/.codex}/skills/"
rm -rf "\$tmp"
\`\`\`

将 \`code-analyzer\` 替换为需要恢复的 skill 名称。若目标已存在，请先确认本地修改，
再删除旧目录或使用下面的恢复脚本加 \`--force\`。

## 恢复全部个人 Skills

\`\`\`bash
tmp=\$(mktemp -d)
git clone --depth 1 https://github.com/$REPO_FULL.git "\$tmp/codex-skills"
mkdir -p "\${CODEX_HOME:-\$HOME/.codex}/skills"
for skill in code-analyzer code-normalize github-manager java-to-kotlin skill-common; do
  rm -rf "\${CODEX_HOME:-\$HOME/.codex}/skills/\$skill"
  cp -R "\$tmp/codex-skills/\$skill" "\${CODEX_HOME:-\$HOME/.codex}/skills/"
done
rm -rf "\$tmp"
\`\`\`

恢复后重启 Codex。

## 使用恢复脚本

已安装 \`github-manager\` 时，可以直接执行：

\`\`\`bash
~/.codex/skills/github-manager/scripts/restore_skills.sh --skill code-analyzer
~/.codex/skills/github-manager/scripts/restore_skills.sh --all
~/.codex/skills/github-manager/scripts/restore_skills.sh --all --force
\`\`\`

仓库：https://github.com/$REPO_FULL
README

# --- 提交信息增强：包含 skill 名称和功能描述 ---
extract_skill_desc() {
  local skill_md="$1"
  [[ -f "$skill_md" ]] || { echo ""; return; }
  # 从 YAML front-matter 的 description 字段提取，取前 80 字符
  local desc
  desc=$(sed -n '/^---$/,/^---$/{ /^description:/{ s/^description: *//; p; q; } }' "$skill_md" 2>/dev/null || true)
  [[ -z "$desc" ]] && desc=$(head -5 "$skill_md" | grep -v '^---' | grep -v '^#' | head -1 | sed 's/^[[:space:]]*//')
  # 截断到 80 字符
  echo "${desc:0:80}"
}

git -C "$UNIFIED_DIR" add -A
if git -C "$UNIFIED_DIR" diff --cached --quiet; then
  echo "无仓库变更，跳过提交"
else
  # 提取变更的 skill 列表
  CHANGED_SKILLS=$(git -C "$UNIFIED_DIR" diff --cached --name-only | awk -F/ '{print ($1 == "") ? $0 : $1}' | sort -u | grep -v '^$')
  CHANGED_FILES=$(git -C "$UNIFIED_DIR" diff --cached --name-status)

  # 构建 commit 标题和正文
  COMMIT_TITLE=""
  COMMIT_BODY=""

  if [[ -n "$CHANGED_SKILLS" ]]; then
    # 为每个变更的 skill 提取功能描述
    while IFS= read -r skill_name; do
      [[ -z "$skill_name" ]] && continue
      skill_desc=$(extract_skill_desc "$SKILLS_ROOT/$skill_name/SKILL.md")
      if [[ -n "$skill_desc" ]]; then
        COMMIT_TITLE="${COMMIT_TITLE:+$COMMIT_TITLE, }$skill_name"
        COMMIT_BODY="${COMMIT_BODY}${COMMIT_BODY:+\n\n}[$skill_name] $skill_desc"
      else
        COMMIT_TITLE="${COMMIT_TITLE:+$COMMIT_TITLE, }$skill_name"
      fi
    done <<< "$CHANGED_SKILLS"
  fi

  # 补充文件变更清单到正文
  if [[ -n "$CHANGED_FILES" ]]; then
    COMMIT_BODY="${COMMIT_BODY}${COMMIT_BODY:+\n\n}变更文件:\n$CHANGED_FILES"
  fi

  # 回退：无有效标题时使用默认值
  [[ -z "$COMMIT_TITLE" ]] && COMMIT_TITLE="同步技能"
  [[ -z "$COMMIT_BODY" ]] && COMMIT_BODY="$CHANGED_FILES"

  git -C "$UNIFIED_DIR" commit -m "$COMMIT_TITLE" -m "$COMMIT_BODY"
fi
CURRENT_BRANCH=$(git -C "$UNIFIED_DIR" branch --show-current)
[[ -n "$CURRENT_BRANCH" ]] || {
  echo "统一仓库处于 detached HEAD，无法安全推送" >&2
  exit 2
}
git -C "$UNIFIED_DIR" push -u origin "$CURRENT_BRANCH"

# 只有远端同步成功后，才更新本地发布状态。
COMMIT_SHA=$(git -C "$UNIFIED_DIR" rev-parse HEAD)
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
for skill_name in "${MANAGED[@]}"; do
  skill_dir="$SKILLS_ROOT/$skill_name"
  env -u PYTHONINSPECT python3 - \
    "$skill_dir/.github-published" "$REPO_FULL" "$NOW" "$COMMIT_SHA" << 'PYEOF'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
data.update({
    "unified_repo": sys.argv[2],
    "mode": "unified",
    "last_publish": sys.argv[3],
    "commit": sys.argv[4],
})
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PYEOF
done
for skill_name in "${UPDATED[@]}"; do
  "$SCRIPT_DIR/save_hashes.sh" "$SKILLS_ROOT/$skill_name" "$HASHES_FILE"
done

echo "发布完成: https://github.com/$REPO_FULL"
echo "提交: $COMMIT_SHA"
