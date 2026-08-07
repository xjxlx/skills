#!/usr/bin/env bash
# generate_catalog.sh - 生成 SKILLS_CATALOG.md
# 用法: generate_catalog.sh [skills_root] [output_file]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_ROOT="${1:-$HOME/.codex/skills}"
OUTPUT_FILE="${2:-$SCRIPT_DIR/../SKILLS_CATALOG.md}"

GITHUB_NETWORK_SCRIPT="$SCRIPT_DIR/github_network.sh" \
  env -u PYTHONINSPECT python3 \
  "$SCRIPT_DIR/_gen_catalog.py" "$SKILLS_ROOT" "$OUTPUT_FILE"
