#!/usr/bin/env bash
# 验证 GitHub CLI/Git 在直连失败后会读取系统代理并重试。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT
MOCK_BIN="$TEST_ROOT/bin"
mkdir -p "$MOCK_BIN"

cat > "$MOCK_BIN/scutil" <<'MOCK_SCUTIL'
#!/usr/bin/env bash
cat <<'PROXY'
<dictionary> {
  HTTPEnable : 1
  HTTPProxy : 127.0.0.1
  HTTPPort : 12000
  HTTPSEnable : 1
  HTTPSProxy : 127.0.0.1
  HTTPSPort : 12000
}
PROXY
MOCK_SCUTIL

cat > "$MOCK_BIN/gh" <<'MOCK_GH'
#!/usr/bin/env bash
if [[ "${HTTPS_PROXY:-}" == "http://127.0.0.1:12000" ]]; then
  echo "gh proxy success"
  exit 0
fi
echo "gh direct failure" >&2
exit 7
MOCK_GH

cat > "$MOCK_BIN/git" <<'MOCK_GIT'
#!/usr/bin/env bash
for argument in "$@"; do
  if [[ "$argument" == "http.proxy=http://127.0.0.1:12000" ]]; then
    echo "git proxy success"
    exit 0
  fi
done
echo "git direct failure" >&2
exit 8
MOCK_GIT

chmod +x "$MOCK_BIN/scutil" "$MOCK_BIN/gh" "$MOCK_BIN/git"
PATH="$MOCK_BIN:$PATH"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

# shellcheck source=/dev/null
source "$SCRIPT_DIR/github_network.sh"

[[ "$(github_system_proxy)" == "http://127.0.0.1:12000" ]]
github_gh api user >/dev/null
"$SCRIPT_DIR/github_network.sh" gh api user >/dev/null
github_git push origin main >/dev/null
github_git_clone --depth 1 https://github.com/xjxlx/skills.git "$TEST_ROOT/repo" >/dev/null

echo "github network fallback tests passed"
