#!/usr/bin/env python3
"""code-compose 约定库管理脚本。

用法:
  conventions.py init <project> [--root DIR]
  conventions.py list [--root DIR]
  conventions.py get <project> [--root DIR]
  conventions.py add <project> --section <章节> --rule <规则> [--source <来源>] [--root DIR]

约定文件为 Markdown，按 "## 章节" 组织；每条规则格式：
  - YYYY-MM-DD: 规则（来源：xxx）
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path


TEMPLATE = """# {project} Compose 约定

> 由 code-compose 维护，最后更新：{today}
> 来源标记：用户确认 / 源码证据 / 编译修复

## 基础信息

- 项目名：
- 设计稿基准：
- Compose 源码目录：
- 编译验证命令：

## 颜色

## 字体

## 间距与尺寸

## 组件

## 适配

## 命名与结构

## 其他
"""


def sanitize(name: str) -> str:
    value = name.strip().replace("/", "_").replace("\\", "_")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise SystemExit(f"非法项目名: {name}")
    return value


def conventions_dir(root: str | None) -> Path:
    if root:
        return Path(root).expanduser()
    return Path(__file__).resolve().parent.parent / "conventions"


def project_file(conv_dir: Path, project: str) -> Path:
    return conv_dir / f"{sanitize(project)}.md"


def write_index(conv_dir: Path) -> None:
    files = sorted(p.name for p in conv_dir.glob("*.md") if p.name != "index.md")
    lines = ["# Compose 约定库索引", "", "> 由 code-compose 自动维护，最后更新：" + date.today().isoformat(), ""]
    if not files:
        lines.append("（暂无项目约定）")
    else:
        lines.append("| 项目 | 最后更新 |")
        lines.append("|---|---|")
        for name in files:
            updated = "见文件"
            text = (conv_dir / name).read_text(encoding="utf-8")
            match = re.search(r"最后更新：(\S+)", text)
            if match:
                updated = match.group(1)
            lines.append(f"| {name[:-3]} | {updated} |")
    (conv_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_timestamp(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"> 由 code-compose 维护，最后更新：\S+",
        "> 由 code-compose 维护，最后更新：" + date.today().isoformat(),
        text,
        count=1,
    )
    path.write_text(text, encoding="utf-8")


def cmd_init(conv_dir: Path, project: str) -> None:
    conv_dir.mkdir(parents=True, exist_ok=True)
    target = project_file(conv_dir, project)
    if target.exists():
        raise SystemExit(f"约定文件已存在: {target}")
    target.write_text(
        TEMPLATE.format(project=sanitize(project), today=date.today().isoformat()),
        encoding="utf-8",
    )
    write_index(conv_dir)
    print(f"已创建约定文件: {target}")


def cmd_list(conv_dir: Path) -> None:
    projects = sorted(p.name[:-3] for p in conv_dir.glob("*.md") if p.name != "index.md")
    if not projects:
        print("（暂无项目约定）")
        return
    for name in projects:
        print(name)


def cmd_get(conv_dir: Path, project: str) -> None:
    target = project_file(conv_dir, project)
    if not target.exists():
        raise SystemExit(f"未找到约定文件: {target}（可先执行 init）")
    print(target)
    print("---")
    print(target.read_text(encoding="utf-8"))


def cmd_add(conv_dir: Path, project: str, section: str, rule: str, source: str) -> None:
    target = project_file(conv_dir, project)
    if not target.exists():
        raise SystemExit(f"未找到约定文件: {target}（可先执行 init）")
    text = target.read_text(encoding="utf-8")
    if rule in text:
        print(f"规则已存在，跳过: {rule}")
        return
    today = date.today().isoformat()
    line = f"- {today}: {rule}"
    if source:
        line += f"（来源：{source}）"
    section_header = f"## {section}"
    if section_header in text:
        text = text.replace(section_header, section_header + "\n\n" + line, 1)
    else:
        text = text.rstrip("\n") + f"\n\n{section_header}\n\n{line}\n"
    target.write_text(text, encoding="utf-8")
    update_timestamp(target)
    write_index(conv_dir)
    print(f"已写入 {target}: {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description="code-compose 约定库管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="生成项目约定模板")
    p_init.add_argument("project")

    p_list = sub.add_parser("list", help="列出所有项目")

    p_get = sub.add_parser("get", help="读取项目约定")
    p_get.add_argument("project")

    p_add = sub.add_parser("add", help="追加一条约定")
    p_add.add_argument("project")
    p_add.add_argument("--section", required=True)
    p_add.add_argument("--rule", required=True)
    p_add.add_argument("--source", default="")

    for p in (p_init, p_list, p_get, p_add):
        p.add_argument("--root", default=None, help="约定库目录（默认 skill 自带 conventions/）")

    args = parser.parse_args()
    conv_dir = conventions_dir(args.root)
    if args.command == "init":
        cmd_init(conv_dir, args.project)
    elif args.command == "list":
        cmd_list(conv_dir)
    elif args.command == "get":
        cmd_get(conv_dir, args.project)
    elif args.command == "add":
        cmd_add(conv_dir, args.project, args.section, args.rule, args.source)
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code:
            print(str(exc), file=sys.stderr)
        sys.exit(exc.code if isinstance(exc.code, int) else 1)
