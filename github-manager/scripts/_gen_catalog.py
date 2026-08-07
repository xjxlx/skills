#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


skills_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".codex" / "skills"
output_file = (
    Path(sys.argv[2])
    if len(sys.argv) > 2
    else Path(__file__).resolve().parent.parent / "SKILLS_CATALOG.md"
)
unified_repo = os.environ.get("GITHUB_MANAGER_UNIFIED_REPO", "")
github_network_script = os.environ.get("GITHUB_NETWORK_SCRIPT", "")

EXCLUDE = {".system", "android-cli"}
NEGATIVE_WORDS = ("不得", "禁止", "不负责", "不复制", "无需", "无明确", "避免", "除外")
POSITIVE_WORDS = ("必须调用", "调用 `$", "交给 `$", "使用 `$", "引用 `$")
REFERENCE_PATTERN = re.compile(r"\$([a-z][a-z0-9-]+)")


def frontmatter(content: str) -> tuple[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return "", ""
    block = match.group(1)
    name_match = re.search(r"^name:\s*(.+)$", block, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", block, re.MULTILINE)
    return (
        name_match.group(1).strip() if name_match else "",
        description_match.group(1).strip() if description_match else "",
    )


def dependencies(content: str, skill_name: str) -> list[str]:
    result = set()
    body = content.split("---", 2)[-1]
    for line in body.splitlines():
        if any(word in line for word in NEGATIVE_WORDS):
            continue
        if not any(word in line for word in POSITIVE_WORDS):
            continue
        for reference in REFERENCE_PATTERN.findall(line):
            if reference != skill_name and reference not in {"skill-name", "skill-x"}:
                result.add(reference)
    return sorted(result)


def github_user() -> str:
    try:
        command = ["gh", "api", "user", "-q", ".login"]
        if github_network_script:
            command = [github_network_script, "gh", *command[1:]]
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def publication(skill_dir: Path) -> tuple[str, str, str]:
    marker = skill_dir / ".github-published"
    data = {}
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return "", "标记异常", "-"

    repo = unified_repo or data.get("unified_repo") or data.get("repo", "")
    if not repo:
        return "", "未发布", "-"
    last_update = data.get("last_publish", "-")[:10]
    return f"https://github.com/{repo}", "已发布", last_update


skills = []
for directory in sorted(skills_root.iterdir()):
    if not directory.is_dir() or directory.name in EXCLUDE or directory.name.startswith("."):
        continue
    skill_md = directory / "SKILL.md"
    if not skill_md.exists():
        continue

    content = skill_md.read_text(encoding="utf-8")
    name, description = frontmatter(content)
    name = name or directory.name
    if len(description) > 80:
        description = description[:77] + "..."
    repo_url, status, last_update = publication(directory)
    file_count = sum(
        1
        for path in directory.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "codex-skills" not in path.parts
        and path.name not in {".github-published", ".hashes.json", ".DS_Store"}
    )
    skills.append(
        {
            "name": name,
            "dir": directory.name,
            "description": description,
            "deps": dependencies(content, directory.name),
            "repo_url": repo_url,
            "status": status,
            "last_update": last_update,
            "file_count": file_count,
            "has_agents": (directory / "agents" / "openai.yaml").exists(),
        }
    )

generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
if output_file.exists():
    previous = output_file.read_text(encoding="utf-8")
    match = re.search(r"> 自动生成于 ([^，]+)，由 github-manager 维护", previous)
    if match:
        generated_at = match.group(1)

lines = [
    "# 个人 Skills 目录\n",
    f"> 自动生成于 {generated_at}，由 github-manager 维护",
    f"> GitHub 账号：{github_user()}\n",
    "## 概览\n",
    "| Skill | 用途 | 依赖 | 状态 | 最后更新 |",
    "|---|---|---|---|---|",
]

for skill in skills:
    deps = ", ".join(skill["deps"]) if skill["deps"] else "无"
    label = (
        f"[{skill['name']}]({skill['repo_url']}/tree/main/{skill['dir']})"
        if skill["repo_url"]
        else skill["name"]
    )
    lines.append(
        f"| {label} | {skill['description']} | {deps} | "
        f"{skill['status']} | {skill['last_update']} |"
    )

lines.extend(["\n## 依赖关系\n", "```mermaid", "graph LR"])
has_dependencies = False
for skill in skills:
    for dependency in skill["deps"]:
        lines.append(f"  {skill['dir']} --> {dependency}")
        has_dependencies = True
if not has_dependencies:
    lines.append("  %% 无跨 skill 依赖")
lines.append("```\n")

lines.append("## 各 Skill 详情\n")
for skill in skills:
    lines.extend(
        [
            f"### {skill['name']}\n",
            f"- **目录名**：`{skill['dir']}`",
            f"- **用途**：{skill['description']}",
            f"- **依赖**：{', '.join(skill['deps']) if skill['deps'] else '无'}",
            f"- **文件数**：{skill['file_count']}",
            f"- **UI 元数据**：{'有 agents/openai.yaml' if skill['has_agents'] else '缺少'}",
            f"- **路径**：`~/.codex/skills/{skill['dir']}/`",
        ]
    )
    if skill["repo_url"]:
        lines.append(f"- **仓库**：{skill['repo_url']}/tree/main/{skill['dir']}")
    lines.extend(
        [
            f"- **状态**：{skill['status']}",
            f"- **最后更新**：{skill['last_update']}\n",
        ]
    )

published = sum(1 for skill in skills if skill["status"] == "已发布")
lines.extend(
    [
        "---\n",
        f"共 **{len(skills)}** 个 skill，其中 **{published}** 个已发布，"
        f"**{len(skills) - published}** 个未发布。",
    ]
)

content = "\n".join(lines) + "\n"
if output_file.exists():
    previous = output_file.read_text(encoding="utf-8")
    previous_normalized = re.sub(
        r"> 自动生成于 [^，]+，由 github-manager 维护",
        "> 自动生成于 <timestamp>，由 github-manager 维护",
        previous,
    )
    content_normalized = re.sub(
        r"> 自动生成于 [^，]+，由 github-manager 维护",
        "> 自动生成于 <timestamp>，由 github-manager 维护",
        content,
    )
    if previous_normalized != content_normalized:
        content = content.replace(generated_at, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 1)

output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(content, encoding="utf-8")
print(f"已生成目录文档: {output_file}")
print(f"共 {len(skills)} 个 skill")
