#!/usr/bin/env python3
"""按标准接口描述执行项目中的 .http 请求并保存 JSON 响应。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


class RunnerError(Exception):
    pass


VARIABLE_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
HEADING_PATTERN = re.compile(r"^###\s*(.*?)\s*$")
REQUEST_PATTERN = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(.+?)\s*$", re.I)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().replace("课程", "课")
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value, flags=re.UNICODE).replace("_", "").lower()


def parse_description(description: str) -> tuple[str, str]:
    match = re.match(r"^\s*(.+?)\s*-\s*([A-Za-z][A-Za-z0-9_-]*)\s*$", description)
    if not match:
        raise RunnerError(
            "接口描述格式无法识别。请按以下格式提供：\n"
            "接口：L6789课程- getDayContent\n"
            "ViewModel：V2ViewModel"
        )
    return match.group(1), match.group(2)


def parse_blocks(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if HEADING_PATTERN.match(line)]
    blocks: list[dict[str, object]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        title = HEADING_PATTERN.match(lines[start]).group(1).strip()
        request_index = next(
            (index for index in range(start + 1, end) if REQUEST_PATTERN.match(lines[index].strip())),
            None,
        )
        if request_index is None:
            continue
        request = REQUEST_PATTERN.match(lines[request_index].strip())
        blank_index = next(
            (index for index in range(request_index + 1, end) if not lines[index].strip()),
            end,
        )
        headers: dict[str, str] = {}
        for line in lines[request_index + 1 : blank_index]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        body_lines = [line.strip() for line in lines[blank_index + 1 : end] if line.strip()]
        blocks.append(
            {
                "title": title,
                "method": request.group(1).upper(),
                "url": request.group(2).strip(),
                "headers": headers,
                "body": " ".join(body_lines),
            }
        )
    return blocks


def find_request(project_root: Path, course: str, method_name: str) -> tuple[Path, dict[str, object]]:
    files = sorted(path for path in project_root.rglob("*.http") if ".git" not in path.parts)
    course_key = normalized(course)
    file_candidates = [path for path in files if normalized(path.stem) == course_key]
    if not file_candidates:
        file_candidates = [
            path
            for path in files
            if any(
                normalized(str(block["title"]).split("-", 1)[0]) == course_key
                and str(block["title"]).rsplit("-", 1)[-1].strip() == method_name
                for block in parse_blocks(path)
            )
        ]
    if not file_candidates:
        raise RunnerError(f"未找到与接口描述匹配的 .http 文件：{course}-{method_name}")
    if len(file_candidates) > 1:
        paths = "\n".join(f"- {path}" for path in file_candidates)
        raise RunnerError(f"找到多个候选 .http 文件，请明确选择：\n{paths}")

    matches = [
        block
        for block in parse_blocks(file_candidates[0])
        if str(block["title"]).rsplit("-", 1)[-1].strip() == method_name
        and normalized(str(block["title"]).split("-", 1)[0]) == course_key
    ]
    if len(matches) != 1:
        raise RunnerError(
            f"文件 {file_candidates[0]} 中未能唯一定位请求：### {course}-{method_name}"
        )
    return file_candidates[0], matches[0]


def load_environment(request_file: Path, project_root: Path, requested: str | None) -> dict[str, object]:
    candidates = []
    current = request_file.parent
    while True:
        candidate = current / "http-client.env.json"
        if candidate.is_file():
            candidates.append(candidate)
        if current == project_root or current.parent == current:
            break
        current = current.parent
    if not candidates:
        raise RunnerError(f"未找到 http-client.env.json：{request_file.parent}")
    data = json.loads(candidates[0].read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RunnerError(f"环境文件不是 JSON 对象：{candidates[0]}")
    environments = data if all(isinstance(value, dict) for value in data.values()) else {"default": data}
    if requested:
        if requested not in environments:
            raise RunnerError(f"环境文件中不存在环境：{requested}")
        return environments[requested]
    if "dev" in environments:
        return environments["dev"]
    if len(environments) == 1:
        return next(iter(environments.values()))
    names = ", ".join(sorted(environments))
    raise RunnerError(f"环境选择有歧义，请指定环境（可选：{names}）")


def resolve(value: str, environment: dict[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name not in environment:
            raise RunnerError(f"环境变量未定义：{name}")
        return str(environment[name])

    return VARIABLE_PATTERN.sub(replace, value)


def form_parameters(body: str, environment: dict[str, object]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for item in body.split("&"):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise RunnerError(f"无法解析表单字段：{item}")
        key, value = item.split("=", 1)
        parameters[key.strip()] = resolve(value.strip(), environment)
    return parameters


def execute(project_root: Path, request_file: Path, block: dict[str, object], environment: dict[str, object]) -> Path:
    url = resolve(str(block["url"]), environment)
    headers = {str(key): resolve(str(value), environment) for key, value in dict(block["headers"]).items()}
    body = resolve(str(block["body"]), environment)
    if "application/x-www-form-urlencoded" in headers.get("content-type", ""):
        payload = urlencode(form_parameters(body, environment))
    else:
        payload = body

    with tempfile.NamedTemporaryFile() as response_file:
        command = ["curl", "-sS", "-X", str(block["method"]), url, "-o", response_file.name, "-w", "%{http_code}"]
        for key, value in headers.items():
            command.extend(["-H", f"{key}: {value}"])
        if payload:
            command.extend(["--data-raw", payload])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RunnerError(f"请求执行失败：{result.stderr.strip()}")
        status = result.stdout.strip()[-3:]
        if not status.isdigit():
            raise RunnerError(f"无法读取 HTTP 状态码：{result.stdout.strip()}")
        response_body = Path(response_file.name).read_bytes()

    output_dir = project_root / ".idea" / "httpRequests"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{datetime.now().strftime('%Y-%m-%dT%H%M%S')}.{status}.json"
    output_path.write_bytes(response_body)
    try:
        json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunnerError(f"响应已保存但不是合法 JSON：{output_path}（{error}）") from error
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="执行项目中的标准 .http 请求并保存 JSON 响应")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--description", required=True, help="例如：L6789课程- getDayContent")
    parser.add_argument("--environment", help="http-client.env.json 中的环境名")
    parser.add_argument("--dry-run", action="store_true", help="只解析请求，不发送网络请求")
    args = parser.parse_args()
    try:
        course, method_name = parse_description(args.description)
        request_file, block = find_request(args.project_root, course, method_name)
        environment = load_environment(request_file, args.project_root, args.environment)
        if args.dry_run:
            print(f"请求文件：{request_file}")
            print(f"请求块：### {block['title']}")
            print(f"请求方法：{block['method']}")
            print(f"请求字段：{', '.join(form_parameters(resolve(str(block['body']), environment), environment))}")
            return 0
        output_path = execute(args.project_root, request_file, block, environment)
        print(f"请求文件：{request_file}")
        print(f"响应路径：{output_path}")
        print("响应文件已保存。")
        print(f"> {output_path.name}")
        return 0
    except (OSError, json.JSONDecodeError, RunnerError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
