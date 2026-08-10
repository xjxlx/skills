#!/usr/bin/env bash
# build_commit_message.sh 的最小回归测试。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/build_commit_message.sh"

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT
REPO_DIR="$TEMP_DIR/repo"
SKILLS_ROOT="$TEMP_DIR/skills"
mkdir -p "$REPO_DIR/github-manager/scripts" "$SKILLS_ROOT/github-manager"
git -C "$REPO_DIR" init -q
git -C "$REPO_DIR" config user.email test@example.com
git -C "$REPO_DIR" config user.name "提交测试"
printf '%s\n' '旧规则' > "$REPO_DIR/github-manager/SKILL.md"
printf '%s\n' '旧脚本' > "$REPO_DIR/github-manager/scripts/old.sh"
git -C "$REPO_DIR" add -A
git -C "$REPO_DIR" commit -q -m "初始化测试"

printf '%s\n' '新规则' > "$REPO_DIR/github-manager/SKILL.md"
printf '%s\n' '新脚本' > "$REPO_DIR/github-manager/scripts/publish_unified.sh"
rm "$REPO_DIR/github-manager/scripts/old.sh"
git -C "$REPO_DIR" add -A

build_commit_message "$REPO_DIR" "$SKILLS_ROOT"
[[ "$COMMIT_TITLE" == "更新技能：github-manager（新增 1 个文件，修改 1 个文件，删除 1 个文件）" ]]
[[ "$COMMIT_BODY" == *"修改 github-manager/SKILL.md（技能规则与使用说明）"* ]]
[[ "$COMMIT_BODY" == *"新增 github-manager/scripts/publish_unified.sh（执行脚本：publish_unified.sh）"* ]]
[[ "$COMMIT_BODY" == *"删除 github-manager/scripts/old.sh（执行脚本：old.sh）"* ]]
if [[ "$COMMIT_BODY" == *"Use when"* || "$COMMIT_BODY" == *"updated"* ]]; then
  echo "提交信息不应包含英文泛化描述" >&2
  exit 1
fi

echo "build_commit_message 测试通过"
