#!/usr/bin/env bash
# publish_skill.sh — 首次发布 skill 到 GitHub 公开仓库
# 用法: publish_skill.sh <skill_dir> [--repo-name <name>] [--org <org>]
# 依赖: gh (GitHub CLI)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/github_network.sh"
SKILL_DIR="${1:?用法: publish_skill.sh <skill_dir> [--repo-name name] [--org org]}"
shift

REPO_NAME=""
ORG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-name) REPO_NAME="$2"; shift 2 ;;
    --org) ORG="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d "$SKILL_DIR" ]]; then
  echo "目录不存在: $SKILL_DIR" >&2
  exit 2
fi

SKILL_NAME=$(basename "$SKILL_DIR")
[[ -z "$REPO_NAME" ]] && REPO_NAME="codex-skill-${SKILL_NAME}"

echo "📦 首次发布：$SKILL_NAME"
echo "   仓库名：$REPO_NAME"
echo "   路径：  $SKILL_DIR"
echo ""

# 1. 安全扫描
"$SCRIPT_DIR/scan_credentials.sh" "$SKILL_DIR" "$SCRIPT_DIR/../.allowlist"

# 2. 初始化 git（如需要）
cd "$SKILL_DIR"
if [[ ! -d ".git" ]]; then
  echo "初始化 Git 仓库..."
  git init
  git checkout -b main
fi

# 3. 创建 .gitignore
cat > .gitignore << 'GITIGNORE'
.hashes.json
.github-published
.allowlist
codex-skills/
__pycache__/
*.pyc
.DS_Store
.idea/
*.swp
*.swo
GITIGNORE

# 4. 确保有 README.md
if [[ ! -f "README.md" ]]; then
  echo "生成 README.md..."
  if [[ -f "SKILL.md" ]]; then
    cp SKILL.md README.md
  fi
fi

# 5. 提交
echo "添加文件..."
git add -A
if ! git diff --cached --quiet; then
  git commit -m "feat: initial release of $SKILL_NAME"
fi
git rev-parse --verify HEAD >/dev/null

# 6. 创建 GitHub 仓库并推送
echo "创建 GitHub 公开仓库..."
if [[ -n "$ORG" ]]; then
  github_gh repo create "$ORG/$REPO_NAME" --public --source=. --remote=origin --push
else
  github_gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
fi

# 6. 获取仓库信息
REPO_FULL=$(github_gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "$REPO_NAME")
COMMIT_SHA=$(git rev-parse HEAD)
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# 7. push 成功后写入发布标记和 hash
cat > .github-published << PUBEOF
{
  "repo": "$REPO_FULL",
  "last_publish": "$NOW",
  "commit": "$COMMIT_SHA"
}
PUBEOF

HASHES_FILE="$SCRIPT_DIR/../.hashes.json"
"$SCRIPT_DIR/save_hashes.sh" "$SKILL_DIR" "$HASHES_FILE"

echo ""
echo "✅ 发布完成！"
echo "   仓库：https://github.com/$REPO_FULL"
echo "   提交：$COMMIT_SHA"
echo "   时间：$NOW"
echo ""
echo "📊 文件统计："
FILE_COUNT=$(find . -type f \
  -not -path './.git/*' \
  -not -path './codex-skills/*' \
  -not -name '.gitignore' \
  -not -name '.github-published' \
  -not -name '.hashes.json' | wc -l | tr -d ' ')
echo "   总文件数：$FILE_COUNT"
echo "   包含："
ls -1 | grep -v '^\.' | head -20 | sed 's/^/     /'
