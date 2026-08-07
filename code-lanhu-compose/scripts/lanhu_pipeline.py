#!/usr/bin/env python3
"""code-lanhu-compose 的固定编排器。

脚本只负责可确定、可重放的流程和状态；设计语义、Compose 代码与补丁仍由
大模型在白名单决策契约内完成，避免为了绕过流程临时生成另一套脚本。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PHASES = (
    "created",
    "inspected",
    "validated",
    "preflight",
    "assets_imported",
    "generated",
    "compiled",
    "installed",
    "screenshot",
    "diffed",
    "completed",
)
ALLOWED_ACTIONS = {"ask_user", "apply_patch", "continue", "stop"}
SAFE_TASK = re.compile(r"^:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$")
SAFE_SERIAL = re.compile(r"^[A-Za-z0-9_.:-]+$")


class PipelineError(RuntimeError):
    """可直接报告给用户的流程错误。"""


class UserInputRequired(PipelineError):
    """证据不足，需要用户决定而不是猜测。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_zip_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if normalized.startswith("/") or ".." in path.parts:
        raise PipelineError(f"ZIP 包含不安全路径：{name}")
    return normalized.lstrip("./")


def zip_entries(archive: Path) -> list[zipfile.ZipInfo]:
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise PipelineError(f"ZIP 文件不存在或扩展名不正确：{archive}")
    with zipfile.ZipFile(archive) as zipped:
        entries = []
        for info in zipped.infolist():
            safe_zip_name(info.filename)
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PipelineError(f"ZIP 不允许包含符号链接：{info.filename}")
            entries.append(info)
        return entries


def _entry_path(name: str) -> str:
    return safe_zip_name(name).lower()


def _referenced_css(html: str, names: Iterable[str]) -> list[str]:
    available = {safe_zip_name(name): safe_zip_name(name) for name in names}
    links = re.findall(r"(?:href|src)=[\"']([^\"']+\.css(?:\?[^\"']*)?)[\"']", html, re.I)
    selected: list[str] = []
    for link in links:
        clean = link.split("?", 1)[0].lstrip("./")
        for candidate in available:
            if candidate.endswith(clean) or candidate.lower().endswith(clean.lower()):
                if candidate not in selected:
                    selected.append(candidate)
    if selected:
        return selected
    return [name for name in available if name.lower().endswith(".css")]


def artifact_dir(archive: Path, project_root: Path, source_sha: str) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", archive.stem).strip("-") or "lanhu"
    return project_root / ".code-lanhu-compose" / f"{stem}-{source_sha[:6]}"


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def new_state(source_sha: str, compose_file: str | None) -> dict[str, Any]:
    return {
        "version": 1,
        "sourceSha256": source_sha,
        "composeFile": compose_file,
        "phase": "created",
        "attempts": {"compile": 0, "repair": 0},
        "history": [],
    }


def transition(state: dict[str, Any], phase: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    if phase not in PHASES:
        raise PipelineError(f"未知流程阶段：{phase}")
    current_index = PHASES.index(state.get("phase", "created"))
    next_index = PHASES.index(phase)
    if next_index != current_index + 1 and next_index != current_index:
        raise PipelineError(f"阶段顺序不允许：{state.get('phase')} -> {phase}")
    state["phase"] = phase
    state.setdefault("history", []).append({"phase": phase, "at": utc_now(), "detail": detail or {}})
    return state


def _write_state(artifact: Path, state: dict[str, Any]) -> None:
    atomic_json(artifact / "pipeline.json", state)


def inspect_archive(archive: Path, project_root: Path, compose_file: Path | None = None) -> dict[str, Any]:
    archive = archive.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    entries = zip_entries(archive)
    html_entries = [info for info in entries if _entry_path(info.filename).endswith((".html", ".htm"))]
    if len(html_entries) != 1:
        raise PipelineError(f"ZIP 必须恰好包含一个入口 HTML，实际发现多个 HTML：{len(html_entries)}")
    html_info = html_entries[0]
    source_sha = sha256_file(archive)
    artifact = artifact_dir(archive, project_root, source_sha)
    artifact.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        html_text = zipped.read(html_info).decode("utf-8", errors="replace")
    names = [safe_zip_name(info.filename) for info in entries]
    css_files = _referenced_css(html_text, names)
    if not css_files:
        raise PipelineError("ZIP 未找到 CSS，无法建立可重放的设计输入")
    source_manifest = {
        "version": 1,
        "sourceName": archive.name,
        "sourcePath": str(archive),
        "sourceSha256": source_sha,
        "artifactPath": str(artifact),
        "html": {"path": safe_zip_name(html_info.filename)},
        "css": [{"path": path} for path in css_files],
        "assets": [{"path": name} for name in names if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"))],
        "createdAt": utc_now(),
    }
    atomic_json(artifact / "source.json", source_manifest)
    state = new_state(source_sha, str(compose_file.resolve()) if compose_file else None)
    transition(state, "inspected", {"html": source_manifest["html"], "cssCount": len(css_files)})
    _write_state(artifact, state)
    return {**source_manifest, "phase": state["phase"]}


def load_source(archive: Path, project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    source_sha = sha256_file(archive.expanduser().resolve())
    artifact = artifact_dir(archive.expanduser().resolve(), project_root.expanduser().resolve(), source_sha)
    source_path = artifact / "source.json"
    state_path = artifact / "pipeline.json"
    if not source_path.is_file() or not state_path.is_file():
        raise PipelineError("尚未 inspect，缺少 source.json 或 pipeline.json")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if source.get("sourceSha256") != source_sha or state.get("sourceSha256") != source_sha:
        raise PipelineError("输入 ZIP 已变化，不能复用旧状态；请重新 inspect")
    return artifact, source, state


def validate_project(archive: Path, project_root: Path, compose_file: Path | None = None) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] not in {"inspected", "validated"}:
        raise PipelineError(f"当前阶段不能 validate：{state['phase']}")
    target = compose_file or (Path(state["composeFile"]) if state.get("composeFile") else None)
    if target is not None:
        target = target.expanduser().resolve()
        root = project_root.expanduser().resolve()
        if root not in target.parents and target != root:
            raise PipelineError(f"Compose 目标必须位于项目根目录内：{target}")
        if not target.is_file():
            raise PipelineError(f"Compose 目标不存在：{target}")
        state["composeFile"] = str(target)
    transition(state, "validated", {"composeFile": state.get("composeFile")})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "sourceSha256": source["sourceSha256"]}


def validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict) or decision.get("action") not in ALLOWED_ACTIONS:
        raise PipelineError(f"决策 action 必须属于 {sorted(ALLOWED_ACTIONS)}，禁止执行任意 shell")
    action = decision["action"]
    if action == "ask_user":
        question = decision.get("question")
        if not isinstance(question, str) or not question.strip():
            raise PipelineError("ask_user 必须提供 question")
    if action == "apply_patch":
        target = decision.get("target")
        patch = decision.get("patch")
        if not isinstance(target, str) or not target or not isinstance(patch, dict):
            raise PipelineError("apply_patch 必须提供 target 和结构化 patch")
        if any(token in target for token in ("..", "\\")) or target.startswith("/"):
            raise PipelineError("apply_patch target 必须是项目内相对路径")
    return decision


def validate_device_name(actual: str, expected: str = "K80") -> bool:
    if actual != expected:
        raise PipelineError(f"当前模拟器为 {actual!r}，项目约束要求 {expected!r}")
    return True


def _run_fixed(command: list[str], cwd: Path, log_path: Path) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    log_path.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    return completed


def record_decision(archive: Path, project_root: Path, decision_path: Path) -> dict[str, Any]:
    artifact, _, state = load_source(archive, project_root)
    decision = validate_decision(json.loads(decision_path.read_text(encoding="utf-8")))
    index = len(list(artifact.glob("decision-*.json"))) + 1
    atomic_json(artifact / f"decision-{index:02d}.json", {**decision, "recordedAt": utc_now(), "phase": state["phase"]})
    if decision["action"] == "ask_user":
        atomic_json(artifact / "needs-user-input.json", {**decision, "recordedAt": utc_now()})
        raise UserInputRequired(decision["question"])
    return {"artifactPath": str(artifact), "action": decision["action"], "phase": state["phase"]}


def compile_project(archive: Path, project_root: Path, task: str) -> dict[str, Any]:
    if not SAFE_TASK.fullmatch(task):
        raise PipelineError(f"Gradle task 不在白名单中：{task}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"generated", "compiled"}:
        raise PipelineError(f"当前阶段不能 compile：{state['phase']}")
    gradlew = project_root / "gradlew"
    if not gradlew.is_file():
        raise PipelineError(f"项目缺少 gradlew：{gradlew}")
    state["attempts"]["compile"] = state["attempts"].get("compile", 0) + 1
    log = artifact / "logs" / f"compile-{state['attempts']['compile']:02d}.log"
    result = _run_fixed([str(gradlew), task, "--console=plain"], project_root, log)
    if result.returncode != 0:
        raise PipelineError(f"编译失败，日志已写入：{log}")
    if state["phase"] != "compiled":
        transition(state, "compiled", {"task": task, "log": str(log)})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "log": str(log)}


def preflight_project(archive: Path, project_root: Path, task: str) -> dict[str, Any]:
    if not SAFE_TASK.fullmatch(task):
        raise PipelineError(f"Gradle task 不在白名单中：{task}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"validated", "preflight"}:
        raise PipelineError(f"当前阶段不能 preflight：{state['phase']}")
    gradlew = project_root / "gradlew"
    if not gradlew.is_file():
        raise PipelineError(f"项目缺少 gradlew：{gradlew}")
    log = artifact / "logs" / "preflight.log"
    result = _run_fixed([str(gradlew), task, "--console=plain"], project_root, log)
    if result.returncode != 0:
        raise PipelineError(f"预检编译失败，日志已写入：{log}")
    if state["phase"] != "preflight":
        transition(state, "preflight", {"task": task, "log": str(log)})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "log": str(log)}


def install_k80(archive: Path, project_root: Path, serial: str, expected_avd: str, apk: Path) -> dict[str, Any]:
    if not SAFE_SERIAL.fullmatch(serial):
        raise PipelineError(f"ADB serial 不安全：{serial}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"compiled", "installed"}:
        raise PipelineError(f"当前阶段不能 install：{state['phase']}")
    if not apk.is_file():
        raise PipelineError(f"APK 不存在：{apk}")
    probe = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise PipelineError(f"无法读取模拟器名称：{probe.stderr.strip()}")
    validate_device_name(probe.stdout.strip(), expected_avd)
    installed = subprocess.run(["adb", "-s", serial, "install", "-r", str(apk.resolve())], text=True, capture_output=True, check=False)
    if installed.returncode != 0:
        raise PipelineError(f"安装 APK 失败：{installed.stdout.strip()} {installed.stderr.strip()}")
    if state["phase"] != "installed":
        transition(state, "installed", {"serial": serial, "avd": expected_avd, "apk": str(apk.resolve())})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "serial": serial, "avd": expected_avd}


def screenshot_k80(archive: Path, project_root: Path, serial: str, run_dir: Path | None = None) -> dict[str, Any]:
    if not SAFE_SERIAL.fullmatch(serial):
        raise PipelineError(f"ADB serial 不安全：{serial}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"installed", "screenshot"}:
        raise PipelineError(f"当前阶段不能 screenshot：{state['phase']}")
    destination = run_dir or artifact / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=True)
    image = destination / "app-screenshot.png"
    with image.open("wb") as output:
        result = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise PipelineError(f"截图失败：{result.stderr.decode(errors='replace').strip()}")
    if state["phase"] != "screenshot":
        transition(state, "screenshot", {"serial": serial, "image": str(image)})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "image": str(image)}


def mark_diff(archive: Path, project_root: Path, report: Path, outcome: str) -> dict[str, Any]:
    if outcome not in {"pass", "repair", "stop"}:
        raise PipelineError("diff outcome 必须是 pass、repair 或 stop")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] != "screenshot":
        raise PipelineError(f"当前阶段不能 mark-diff：{state['phase']}")
    if not report.is_file():
        raise PipelineError(f"差异报告不存在：{report}")
    state["lastDiffOutcome"] = outcome
    if outcome == "repair":
        state["attempts"]["repair"] = state["attempts"].get("repair", 0) + 1
        if state["attempts"]["repair"] > 3:
            raise PipelineError("视觉修正已达到最多三轮")
        state["phase"] = "generated"
        state.setdefault("history", []).append({"phase": "repair_requested", "at": utc_now(), "detail": {"report": str(report), "round": state["attempts"]["repair"]}})
    else:
        transition(state, "diffed", {"report": str(report), "outcome": outcome})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "outcome": outcome, "report": str(report)}


def complete_pipeline(archive: Path, project_root: Path) -> dict[str, Any]:
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] != "diffed" or state.get("lastDiffOutcome") != "pass":
        raise PipelineError("只有差异报告 outcome=pass 时才能完成流程")
    transition(state, "completed", {"reason": "visual-diff-pass"})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="固定执行 code-lanhu-compose 的可重放流程")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--zip", required=True, type=Path)
    inspect.add_argument("--project-root", required=True, type=Path)
    inspect.add_argument("--compose", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--zip", required=True, type=Path)
    validate.add_argument("--project-root", required=True, type=Path)
    validate.add_argument("--compose", type=Path)
    assets = subparsers.add_parser("assets")
    assets.add_argument("--zip", required=True, type=Path)
    assets.add_argument("--project-root", required=True, type=Path)
    assets.add_argument("--compose", required=True, type=Path)
    assets.add_argument("--apply", action="store_true")
    generated = subparsers.add_parser("mark-generated")
    generated.add_argument("--zip", required=True, type=Path)
    generated.add_argument("--project-root", required=True, type=Path)
    generated.add_argument("--compose", required=True, type=Path)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--zip", required=True, type=Path)
    preflight.add_argument("--project-root", required=True, type=Path)
    preflight.add_argument("--task", required=True)
    compile_command = subparsers.add_parser("compile")
    compile_command.add_argument("--zip", required=True, type=Path)
    compile_command.add_argument("--project-root", required=True, type=Path)
    compile_command.add_argument("--task", required=True)
    install = subparsers.add_parser("install-k80")
    install.add_argument("--zip", required=True, type=Path)
    install.add_argument("--project-root", required=True, type=Path)
    install.add_argument("--serial", required=True)
    install.add_argument("--expected-avd", default="K80")
    install.add_argument("--apk", required=True, type=Path)
    screenshot = subparsers.add_parser("screenshot-k80")
    screenshot.add_argument("--zip", required=True, type=Path)
    screenshot.add_argument("--project-root", required=True, type=Path)
    screenshot.add_argument("--serial", required=True)
    screenshot.add_argument("--run-dir", type=Path)
    diff = subparsers.add_parser("mark-diff")
    diff.add_argument("--zip", required=True, type=Path)
    diff.add_argument("--project-root", required=True, type=Path)
    diff.add_argument("--report", required=True, type=Path)
    diff.add_argument("--outcome", required=True, choices=("pass", "repair", "stop"))
    complete = subparsers.add_parser("complete")
    complete.add_argument("--zip", required=True, type=Path)
    complete.add_argument("--project-root", required=True, type=Path)
    decision = subparsers.add_parser("record-decision")
    decision.add_argument("--zip", required=True, type=Path)
    decision.add_argument("--project-root", required=True, type=Path)
    decision.add_argument("--decision", required=True, type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("--zip", required=True, type=Path)
    status.add_argument("--project-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_archive(args.zip, args.project_root, args.compose)
        elif args.command == "validate":
            result = validate_project(args.zip, args.project_root, args.compose)
        elif args.command == "assets":
            artifact, _, state = load_source(args.zip, args.project_root)
            if state["phase"] not in {"preflight", "assets_imported"}:
                raise PipelineError(f"当前阶段不能 assets：{state['phase']}")
            command = [sys.executable, str(Path(__file__).with_name("import_zip_images.py")), "--zip", str(args.zip), "--compose", str(args.compose), "--project-root", str(args.project_root)]
            if args.apply:
                command.append("--apply")
            completed = subprocess.run(command, cwd=args.project_root, text=True, capture_output=True, check=False)
            (artifact / "logs").mkdir(exist_ok=True)
            (artifact / "logs" / "assets.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
            if completed.returncode != 0:
                raise PipelineError(f"资源导入失败，日志已写入：{artifact / 'logs' / 'assets.log'}")
            if state["phase"] != "assets_imported":
                transition(state, "assets_imported", {"composeFile": str(args.compose.resolve()), "apply": args.apply})
            _write_state(artifact, state)
            result = {"artifactPath": str(artifact), "phase": state["phase"]}
        elif args.command == "mark-generated":
            artifact, _, state = load_source(args.zip, args.project_root)
            if state["phase"] not in {"assets_imported", "generated"}:
                raise PipelineError(f"当前阶段不能 mark-generated：{state['phase']}")
            target = args.compose.resolve()
            if not target.is_file() or args.project_root.resolve() not in target.parents:
                raise PipelineError(f"Compose 目标不存在或不在项目内：{target}")
            state["composeFile"] = str(target)
            if state["phase"] != "generated":
                transition(state, "generated", {"composeFile": str(target)})
            _write_state(artifact, state)
            result = {"artifactPath": str(artifact), "phase": state["phase"], "composeFile": str(target)}
        elif args.command == "preflight":
            result = preflight_project(args.zip, args.project_root, args.task)
        elif args.command == "compile":
            result = compile_project(args.zip, args.project_root, args.task)
        elif args.command == "install-k80":
            result = install_k80(args.zip, args.project_root, args.serial, args.expected_avd, args.apk)
        elif args.command == "screenshot-k80":
            result = screenshot_k80(args.zip, args.project_root, args.serial, args.run_dir)
        elif args.command == "mark-diff":
            result = mark_diff(args.zip, args.project_root, args.report, args.outcome)
        elif args.command == "complete":
            result = complete_pipeline(args.zip, args.project_root)
        elif args.command == "record-decision":
            result = record_decision(args.zip, args.project_root, args.decision)
        elif args.command == "status":
            artifact, source, state = load_source(args.zip, args.project_root)
            result = {"artifactPath": str(artifact), "sourceSha256": source["sourceSha256"], **state}
        else:
            raise PipelineError(f"未知命令：{args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except UserInputRequired as error:
        print(json.dumps({"status": "needs_user_input", "question": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except PipelineError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
