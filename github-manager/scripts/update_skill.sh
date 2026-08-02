#!/usr/bin/env bash
# update_skill.sh — 更新已发布的 skill 到 GitHub
# 用法: update_skill.sh <skill_dir>
# 前提: skill 已通过 publish_skill.sh 首次发布

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="${1:?用法: update_skill.sh <skill_dir>}"
HASHES_FILE="$SCRIPT_DIR/../.hashes.json"

if [[ ! -d "$SKILL_DIR" ]]; then
  echo "目录不存在: $SKILL_DIR" >&2
  exit 2
fi

SKILL_NAME=$(basename "$SKILL_DIR")
PUB_MARKER="$SKILL_DIR/.github-published"

# 检查是否已发布
if [[ ! -f "$PUB_MARKER" ]]; then
  echo "$SKILL_NAME 尚未发布，请先使用 publish_skill.sh" >&2
  exit 2
fi

# 安全扫描
"$SCRIPT_DIR/scan_credentials.sh" "$SKILL_DIR" "$SCRIPT_DIR/../.allowlist"

# 检测变更
echo "🔍 检测变更..."
CHANGE_OUTPUT=$("$SCRIPT_DIR/detect_changes.sh" "$SKILL_DIR" "$HASHES_FILE" 2>&1) || {
  echo "$CHANGE_OUTPUT"
  echo ""
  echo "⏭️  $SKILL_NAME 无变更，跳过更新"
  exit 0
}

echo "$CHANGE_OUTPUT"
echo ""

# 解析变更类型
ADDED=$(echo "$CHANGE_OUTPUT" | grep -c "^A " || true)
MODIFIED=$(echo "$CHANGE_OUTPUT" | grep -c "^M " || true)
DELETED=$(echo "$CHANGE_OUTPUT" | grep -c "^D " || true)

cd "$SKILL_DIR"

# 确保在 git 仓库中
if [[ ! -d ".git" ]]; then
  echo "$SKILL_DIR 不是 git 仓库" >&2
  exit 2
fi

# 确保有远程仓库
if ! git remote get-url origin >/dev/null 2>&1; then
  REPO=$(python3 -c "import json; print(json.load(open('$PUB_MARKER'))['repo'])" 2>/dev/null || echo "")
  if [[ -n "$REPO" ]]; then
    git remote add origin "https://github.com/$REPO.git"
  else
    echo "无法确定远程仓库地址" >&2
    exit 2
  fi
fi

# 生成提交信息
COMMIT_MSG="更新: $SKILL_NAME"
if [[ $ADDED -gt 0 ]]; then COMMIT_MSG="$COMMIT_MSG (+${ADDED} new)"; fi
if [[ $MODIFIED -gt 0 ]]; then COMMIT_MSG="$COMMIT_MSG (~${MODIFIED} modified)"; fi
if [[ $DELETED -gt 0 ]]; then COMMIT_MSG="$COMMIT_MSG (-${DELETED} deleted)"; fi
CHANGE_FILES=$(printf '%s\n' "$CHANGE_OUTPUT" | grep -E "^[AMD] " | sed 's/^[AMD]  //')

# 提交并推送
echo "📁 提交变更..."
git add -A
if [[ -n "$CHANGE_FILES" ]]; then
  git commit -m "$COMMIT_MSG" -m "$CHANGE_FILES"
else
  git commit -m "$COMMIT_MSG"
fi

echo "🚀 推送到 GitHub..."
CURRENT_BRANCH=$(git branch --show-current)
[[ -n "$CURRENT_BRANCH" ]] || {
  echo "当前处于 detached HEAD，无法安全推送" >&2
  exit 2
}
git push origin "$CURRENT_BRANCH"

# 更新标记
COMMIT_SHA=$(git rev-parse HEAD)
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

python3 << PYEOF
import json
with open("$PUB_MARKER") as f:
    data = json.load(f)
data["last_publish"] = "$NOW"
data["commit"] = "$COMMIT_SHA"
with open("$PUB_MARKER", 'w') as f:
    json.dump(data, f, indent=2)
PYEOF

# 保存新 hash
"$SCRIPT_DIR/save_hashes.sh" "$SKILL_DIR" "$HASHES_FILE"

# 获取仓库地址
REPO=$(python3 -c "import json; print(json.load(open('$PUB_MARKER'))['repo'])" 2>/dev/null || echo "unknown")

echo ""
echo "✅ 更新完成！"
echo "🔄 更新发布：$SKILL_NAME"
echo "   变更："
echo "$CHANGE_OUTPUT" | grep -E "^[AMD] " | sed 's/^/     /'
echo "   提交：$COMMIT_SHA"
echo "   仓库：https://github.com/$REPO"
