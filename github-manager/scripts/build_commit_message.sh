#!/usr/bin/env bash
# 生成统一仓库和独立 skill 仓库共用的中文提交信息。

set -euo pipefail

COMMIT_TITLE=""
COMMIT_BODY=""

describe_change_path() {
  local path="$1"
  case "$path" in
    */SKILL.md|SKILL.md) echo "技能规则与使用说明" ;;
    */agents/openai.yaml|agents/openai.yaml) echo "技能发现提示与代理元数据" ;;
    */scripts/*) echo "执行脚本：${path##*/}" ;;
    */references/*) echo "参考文档：${path##*/}" ;;
    */conventions/*) echo "项目约定：${path##*/}" ;;
    */examples/*) echo "使用示例：${path##*/}" ;;
    SKILLS_CATALOG.md) echo "技能目录文档" ;;
    README.md) echo "仓库说明文档" ;;
    */README.md) echo "技能说明文档" ;;
    *) echo "文件内容" ;;
  esac
}

build_commit_message() {
  local repo_dir="${1:?缺少仓库目录}"
  local skills_root="${2:-}"
  local staged_changes
  staged_changes=$(git -C "$repo_dir" diff --cached --name-status --find-renames)
  if [[ -z "$staged_changes" ]]; then
    COMMIT_TITLE="同步仓库"
    COMMIT_BODY="本次没有可提交的文件变化。"
    return 0
  fi

  local added=0 modified=0 deleted=0 renamed=0
  local details=""
  local skill_names
  skill_names=$(printf '%s\n' "$staged_changes" | awk -F '\t' '{ split($2, parts, "/"); if (length(parts[1]) > 0 && parts[1] != "SKILLS_CATALOG.md" && parts[1] != "README.md") print parts[1]; else print "仓库文档" }' | sort -u | paste -sd '、' -)

  local status path new_path action detail display_path
  while IFS=$'\t' read -r status path new_path; do
    [[ -z "$status" ]] && continue
    case "${status:0:1}" in
      A) action="新增"; added=$((added + 1)); display_path="$path" ;;
      M) action="修改"; modified=$((modified + 1)); display_path="$path" ;;
      D) action="删除"; deleted=$((deleted + 1)); display_path="$path" ;;
      R) action="重命名"; renamed=$((renamed + 1)); display_path="$path → $new_path" ;;
      *) action="变更"; display_path="$path" ;;
    esac
    detail=$(describe_change_path "$path")
    details="${details}${details:+$'\n'}- ${action} ${display_path}（${detail}）"
  done <<< "$staged_changes"

  local summary="新增 ${added} 个文件，修改 ${modified} 个文件，删除 ${deleted} 个文件"
  [[ "$renamed" -gt 0 ]] && summary="${summary}，重命名 ${renamed} 个文件"
  COMMIT_TITLE="更新技能：${skill_names:-仓库文档}（${summary}）"
  COMMIT_BODY="本次提交的具体变化：${details}"

  if [[ -n "$skills_root" ]]; then
    # 仅确认传入路径有效；描述始终来自暂存区文件，避免把英文 frontmatter 当提交文案。
    [[ -d "$skills_root" ]] || {
      echo "Skills 根目录不存在：$skills_root" >&2
      return 2
    }
  fi
}

