#!/usr/bin/env bash
# restore_skills.sh - 从统一 GitHub 仓库恢复单个或全部 skill
# 用法:
#   restore_skills.sh --skill <name> [--repo owner/repo] [--dest dir] [--force]
#   restore_skills.sh --all [--repo owner/repo] [--dest dir] [--force]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/github_network.sh"

REPO="xjxlx/skills"
DEST="${CODEX_HOME:-$HOME/.codex}/skills"
SKILL_NAME=""
RESTORE_ALL=0
FORCE=0
EXCLUDE=(".system" "android-cli")

usage() {
  cat <<'EOF'
用法:
  restore_skills.sh --skill <name> [--repo owner/repo] [--dest dir] [--force]
  restore_skills.sh --all [--repo owner/repo] [--dest dir] [--force]

选项:
  --skill <name>  恢复单个 skill
  --all           恢复仓库中的全部个人 skill
  --repo <repo>   GitHub 仓库，默认 xjxlx/skills
  --dest <dir>    目标 skills 目录，默认 ${CODEX_HOME:-$HOME/.codex}/skills
  --force         覆盖已存在的同名 skill
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill) SKILL_NAME="${2:?--skill 缺少名称}"; shift 2 ;;
    --all) RESTORE_ALL=1; shift ;;
    --repo) REPO="${2:?--repo 缺少仓库}"; shift 2 ;;
    --dest) DEST="${2:?--dest 缺少目录}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $RESTORE_ALL -eq 1 && -n "$SKILL_NAME" ]] || \
   [[ $RESTORE_ALL -eq 0 && -z "$SKILL_NAME" ]]; then
  echo "必须且只能指定 --skill <name> 或 --all" >&2
  exit 2
fi
if [[ -n "$SKILL_NAME" && ! "$SKILL_NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "skill 名称不合法: $SKILL_NAME" >&2
  exit 2
fi

command -v git >/dev/null || { echo "缺少 git" >&2; exit 2; }
command -v rsync >/dev/null || { echo "缺少 rsync" >&2; exit 2; }

if [[ "$REPO" == http://* || "$REPO" == https://* || "$REPO" == git@* || "$REPO" == /* ]]; then
  REPO_URL="$REPO"
else
  REPO_URL="https://github.com/${REPO}.git"
fi

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "拉取仓库: $REPO_URL"
github_git_clone --depth 1 "$REPO_URL" "$TEMP_DIR/repo"

is_excluded() {
  local candidate="$1"
  local excluded
  for excluded in "${EXCLUDE[@]}"; do
    [[ "$candidate" == "$excluded" ]] && return 0
  done
  return 1
}

restore_one() {
  local name="$1"
  local source="$TEMP_DIR/repo/$name"
  local target="$DEST/$name"
  local backup="$TEMP_DIR/backup-$name"

  if is_excluded "$name"; then
    echo "拒绝恢复非个人 skill: $name" >&2
    return 2
  fi
  if [[ ! -f "$source/SKILL.md" ]]; then
    echo "仓库中不存在有效 skill: $name" >&2
    return 2
  fi
  if [[ -e "$target" && $FORCE -ne 1 ]]; then
    echo "目标已存在，未覆盖: ${target}（使用 --force 覆盖）" >&2
    return 3
  fi

  if [[ -e "$target" ]]; then
    mv "$target" "$backup"
  fi
  mkdir -p "$target"
  if ! rsync -a --exclude='.git' --exclude='.DS_Store' "$source/" "$target/"; then
    rm -rf "$target"
    [[ -e "$backup" ]] && mv "$backup" "$target"
    return 1
  fi
  rm -rf "$backup"
  echo "已恢复: $name -> $target"
}

mkdir -p "$DEST"

if [[ -n "$SKILL_NAME" ]]; then
  restore_one "$SKILL_NAME"
else
  SKILLS=()
  for source in "$TEMP_DIR/repo"/*/; do
    name=$(basename "$source")
    is_excluded "$name" && continue
    [[ -f "$source/SKILL.md" ]] || continue
    SKILLS+=("$name")
  done
  [[ ${#SKILLS[@]} -gt 0 ]] || { echo "仓库中没有可恢复的 skill" >&2; exit 2; }
  if [[ $FORCE -ne 1 ]]; then
    for name in "${SKILLS[@]}"; do
      if [[ -e "$DEST/$name" ]]; then
        echo "目标已存在，全部恢复尚未开始: ${DEST}/${name}（使用 --force 覆盖）" >&2
        exit 3
      fi
    done
  fi

  RESTORED=0
  for name in "${SKILLS[@]}"; do
    restore_one "$name"
    ((RESTORED+=1))
  done
  echo "全部恢复完成，共 ${RESTORED} 个 skill"
fi

echo "请重启 Codex 以重新加载恢复的 skill。"
