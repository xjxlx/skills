#!/usr/bin/env bash
# GitHub 网络命令共享回退层。
# 该文件由发布/恢复脚本 source，不直接执行。

github_system_proxy() {
  local proxy
  proxy="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}"
  if [[ -n "$proxy" ]]; then
    printf '%s\n' "$proxy"
    return 0
  fi

  command -v scutil >/dev/null 2>&1 || return 1

  local settings
  settings=$(scutil --proxy 2>/dev/null) || return 1

  local http_enabled http_host http_port
  http_enabled=$(printf '%s\n' "$settings" | awk '$1 == "HTTPEnable" { print $3; exit }')
  http_host=$(printf '%s\n' "$settings" | awk '$1 == "HTTPProxy" { print $3; exit }')
  http_port=$(printf '%s\n' "$settings" | awk '$1 == "HTTPPort" { print $3; exit }')
  if [[ "$http_enabled" == "1" && -n "$http_host" && -n "$http_port" ]]; then
    printf 'http://%s:%s\n' "$http_host" "$http_port"
    return 0
  fi

  local https_enabled https_host https_port
  https_enabled=$(printf '%s\n' "$settings" | awk '$1 == "HTTPSEnable" { print $3; exit }')
  https_host=$(printf '%s\n' "$settings" | awk '$1 == "HTTPSProxy" { print $3; exit }')
  https_port=$(printf '%s\n' "$settings" | awk '$1 == "HTTPSPort" { print $3; exit }')
  if [[ "$https_enabled" == "1" && -n "$https_host" && -n "$https_port" ]]; then
    printf 'http://%s:%s\n' "$https_host" "$https_port"
    return 0
  fi

  local socks_enabled socks_host socks_port
  socks_enabled=$(printf '%s\n' "$settings" | awk '$1 == "SOCKSEnable" { print $3; exit }')
  socks_host=$(printf '%s\n' "$settings" | awk '$1 == "SOCKSProxy" { print $3; exit }')
  socks_port=$(printf '%s\n' "$settings" | awk '$1 == "SOCKSPort" { print $3; exit }')
  if [[ "$socks_enabled" == "1" && -n "$socks_host" && -n "$socks_port" ]]; then
    printf 'socks5h://%s:%s\n' "$socks_host" "$socks_port"
    return 0
  fi

  return 1
}

github_gh() {
  local direct_status=0
  if gh "$@"; then
    return 0
  else
    direct_status=$?
  fi

  local proxy
  proxy=$(github_system_proxy 2>/dev/null || true)
  [[ -n "$proxy" ]] || return "$direct_status"

  echo "GitHub CLI 直连失败，使用系统代理重试: $proxy" >&2
  HTTPS_PROXY="$proxy" \
    HTTP_PROXY="$proxy" \
    ALL_PROXY="$proxy" \
    https_proxy="$proxy" \
    http_proxy="$proxy" \
    all_proxy="$proxy" \
    gh "$@"
}

github_git() {
  local direct_status=0
  if git "$@"; then
    return 0
  else
    direct_status=$?
  fi

  local proxy
  proxy=$(github_system_proxy 2>/dev/null || true)
  [[ -n "$proxy" ]] || return "$direct_status"

  echo "Git 直连失败，使用系统代理重试: $proxy" >&2
  git -c "http.proxy=$proxy" "$@"
}

github_git_clone() {
  local destination="${!#}"
  local destination_preexisting=0
  [[ -e "$destination" ]] && destination_preexisting=1

  local direct_status=0
  if git clone "$@"; then
    return 0
  else
    direct_status=$?
  fi

  local proxy
  proxy=$(github_system_proxy 2>/dev/null || true)
  [[ -n "$proxy" ]] || return "$direct_status"

  # 只删除本次失败的 clone 新建目录，不触碰调用前已存在的路径。
  if [[ "$destination_preexisting" -eq 0 && -e "$destination" ]]; then
    rm -rf -- "$destination"
  fi
  echo "Git 克隆直连失败，使用系统代理重试: $proxy" >&2
  git -c "http.proxy=$proxy" clone "$@"
}
