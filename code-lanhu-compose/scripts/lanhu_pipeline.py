#!/usr/bin/env python3
"""code-lanhu-compose 的固定编排器。

脚本只负责可确定、可重放的流程和状态；设计语义、Compose 代码与补丁仍由
大模型在白名单决策契约内完成，避免为了绕过流程临时生成另一套脚本。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from detect_repeated_blocks import detect_repeated_blocks


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
SAFE_TASK = re.compile(r"^:(?:[A-Za-z0-9_.-]+:)*[A-Za-z0-9_.-]+$")
GRADLE_COMPILE_TASK = re.compile(
    r"^\s*((?::?[A-Za-z0-9_.-]+:)*compile[A-Za-z0-9_.-]*Kotlin)\s+-"
)
SAFE_SERIAL = re.compile(r"^[A-Za-z0-9_.:-]+$")
DESIGN_SERVER_PROCESSES: dict[int, subprocess.Popen[Any]] = {}
DESIGN_DOCUMENT_NAME = "设计解析.json"
DESIGN_DOCUMENT_VERSION = 1
CHROME_EXECUTABLE = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


class PipelineError(RuntimeError):
    """可直接报告给用户的流程错误。"""


class UserInputRequired(PipelineError):
    """证据不足，需要用户决定而不是猜测。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
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


def _referenced_css(html: str, names: Iterable[str], html_name: str) -> list[str]:
    available = {safe_zip_name(name): safe_zip_name(name) for name in names}
    links = re.findall(r"(?:href|src)=[\"']([^\"']+\.css(?:\?[^\"']*)?)[\"']", html, re.I)
    selected: list[str] = []
    for link in links:
        clean = link.split("?", 1)[0]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(html_name), clean))
        candidates = [candidate for candidate in available if candidate == resolved]
        if len(candidates) != 1:
            raise PipelineError(f"HTML 引用的 CSS 无法唯一解析：{link} -> {resolved}")
        if candidates[0] not in selected:
            selected.append(candidates[0])
    if not selected:
        raise UserInputRequired("HTML 未声明 CSS 引用，请确认要采用哪个 CSS 文件")
    return selected


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
        "sourceMd5": source_sha,
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


def _load_cached_inspection(artifact: Path, source_sha: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """读取同一 ZIP 的已验证检查结果，避免重置后续阶段。"""
    source_path = artifact / "source.json"
    state_path = artifact / "pipeline.json"
    if not source_path.is_file() or not state_path.is_file():
        return None
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if source.get("sourceMd5") != source_sha or state.get("sourceMd5") != source_sha:
        return None
    if state.get("phase") not in PHASES:
        return None
    return source, state


def inspect_archive(archive: Path, project_root: Path, compose_file: Path | None = None) -> dict[str, Any]:
    archive = archive.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    source_sha = md5_file(archive)
    artifact = artifact_dir(archive, project_root, source_sha)
    cached = _load_cached_inspection(artifact, source_sha)
    if cached is not None:
        source_manifest, state = cached
        return {**source_manifest, "phase": state["phase"], "cacheHit": True}

    entries = zip_entries(archive)
    html_entries = [info for info in entries if _entry_path(info.filename).endswith((".html", ".htm"))]
    if len(html_entries) != 1:
        raise PipelineError(f"ZIP 必须恰好包含一个入口 HTML，实际发现多个 HTML：{len(html_entries)}")
    html_info = html_entries[0]
    artifact.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        html_text = zipped.read(html_info).decode("utf-8", errors="replace")
    names = [safe_zip_name(info.filename) for info in entries]
    css_files = _referenced_css(html_text, names, safe_zip_name(html_info.filename))
    repeated_blocks = detect_repeated_blocks(archive, css_files, safe_zip_name(html_info.filename))
    repeated_blocks["sourceMd5"] = source_sha
    repeated_blocks_path = artifact / "repeated-block-candidates.json"
    atomic_json(repeated_blocks_path, repeated_blocks)
    source_manifest = {
        "version": 1,
        "sourceName": archive.name,
        "sourcePath": str(archive),
        "sourceMd5": source_sha,
        "artifactPath": str(artifact),
        "html": {"path": safe_zip_name(html_info.filename)},
        "css": [{"path": path} for path in css_files],
        "repeatedBlockCandidates": {
            "path": repeated_blocks_path.name,
            "candidateCount": repeated_blocks["candidateCount"],
            "tolerance": repeated_blocks["tolerance"],
        },
        "assets": [{"path": name} for name in names if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"))],
        "createdAt": utc_now(),
    }
    atomic_json(artifact / "source.json", source_manifest)
    state = new_state(source_sha, str(compose_file.resolve()) if compose_file else None)
    transition(state, "inspected", {"html": source_manifest["html"], "cssCount": len(css_files)})
    _write_state(artifact, state)
    return {**source_manifest, "phase": state["phase"], "cacheHit": False}


def load_source(archive: Path, project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    source_sha = md5_file(archive.expanduser().resolve())
    artifact = artifact_dir(archive.expanduser().resolve(), project_root.expanduser().resolve(), source_sha)
    source_path = artifact / "source.json"
    state_path = artifact / "pipeline.json"
    if not source_path.is_file() or not state_path.is_file():
        raise PipelineError("尚未 inspect，缺少 source.json 或 pipeline.json")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if source.get("sourceMd5") != source_sha or state.get("sourceMd5") != source_sha:
        raise PipelineError("输入 ZIP 已变化，不能复用旧状态；请重新 inspect")
    return artifact, source, state


def _compose_call_arguments(source: str, open_index: int) -> tuple[str, int]:
    """读取 Compose 函数调用参数，支持 padding 内部的 dp(...) 嵌套调用。"""
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(open_index, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"\"", "'"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return source[open_index + 1 : index], index
    raise PipelineError("Compose 中存在未闭合的 padding(...) 调用")


def validate_compose_source(compose_path: Path) -> None:
    """在 Gradle/运行前拒绝 Compose padding 中的负值，避免运行时 PaddingElement 崩溃。"""
    try:
        source = compose_path.read_text(encoding="utf-8")
    except OSError as error:
        raise PipelineError(f"无法读取 Compose 文件：{compose_path}") from error

    for match in re.finditer(r"\bpadding\s*\(", source):
        arguments, _ = _compose_call_arguments(source, match.end() - 1)
        negative = re.search(r"(?<![\w.])-\s*(?:[A-Za-z_][\w.]*|\d+(?:\.\d+)?(?:[fFdD])?)", arguments)
        if negative is None:
            continue
        absolute_index = match.end() - 1 + 1 + negative.start()
        line = source.count("\n", 0, absolute_index) + 1
        preceding_argument = arguments[: negative.start()]
        parameter_match = re.search(r"(?:^|,)\s*([A-Za-z_]\w*)\s*=\s*[^,]*$", preceding_argument, re.DOTALL)
        parameter = parameter_match.group(1) if parameter_match else "未命名参数"
        axis = "y" if parameter in {"top", "bottom"} else "x" if parameter in {"start", "end"} else "x/y"
        raise PipelineError(
            f"Compose 文件 {compose_path}:{line} 的 padding({parameter}) 包含负值；"
            f"Compose padding 参数必须非负，请将该设计位移改为 Modifier.offset({axis} = ...) "
            "或使用父级布局表达，保留原有视觉位移"
        )


def design_server_state_path(artifact: Path) -> Path:
    """返回本次 ZIP 专属的本地设计稿服务状态文件。"""
    return artifact / "design-server.json"


def design_server_source_state_path(artifact: Path) -> Path:
    """返回设计静态服务解压缓存的身份记录。"""
    return artifact / "design-server-source.json"


def _load_cached_design(artifact: Path, source: dict[str, Any]) -> tuple[dict[str, Any], Path] | None:
    """仅复用与当前 ZIP 匹配且包含公共截图的完整设计产物。"""
    design_path = artifact / DESIGN_DOCUMENT_NAME
    screenshot_path = artifact / "runs" / "设计截图.png"
    try:
        design = json.loads(design_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    root = design.get("设计根节点")
    if (
        design.get("版本") != DESIGN_DOCUMENT_VERSION
        or design.get("sourceMd5") != source["sourceMd5"]
        or not isinstance(root, dict)
        or not isinstance(root.get("选择器"), str)
        or not root["选择器"]
        or not screenshot_path.is_file()
    ):
        return None
    return design, screenshot_path


def is_pid_alive(pid: int) -> bool:
    """判断 PID 是否仍然存在，不把权限错误误判为服务已停止。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe_extract_archive(archive: Path, destination: Path) -> None:
    """安全解压 ZIP，供仅本机的静态服务读取。"""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for info in zip_entries(archive):
            relative = safe_zip_name(info.filename)
            target = (root / relative).resolve()
            if root not in target.parents:
                raise PipelineError(f"ZIP 解压路径越界：{relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _has_complete_design_server_source(archive: Path, destination: Path, source_sha: str) -> bool:
    """仅在来源一致且所有 ZIP 文件均完整落盘时复用设计服务解压目录。"""
    marker = design_server_source_state_path(destination.parent)
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if cached.get("sourceMd5") != source_sha:
        return False
    root = destination.resolve()
    for info in zip_entries(archive):
        if info.is_dir():
            continue
        candidate = root / safe_zip_name(info.filename)
        target = candidate.resolve()
        if root not in target.parents or candidate.is_symlink() or not target.is_file():
            return False
        if target.stat().st_size != info.file_size:
            return False
    return True


def _wait_for_loopback_server(port: int, process: subprocess.Popen[bytes]) -> None:
    """确认 http.server 已能接受本机连接，避免浏览器读到尚未启动的页面。"""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PipelineError(f"本地静态服务启动失败，退出码：{process.returncode}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.1)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise PipelineError("本地静态服务在 3 秒内未就绪")


def _server_command_matches(pid: int, serving_root: Path) -> bool:
    """macOS 上只终止由本脚本启动且仍指向该解压目录的 http.server。"""
    inspected = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        text=True,
        capture_output=True,
        check=False,
    )
    command = inspected.stdout.strip()
    return (
        inspected.returncode == 0
        and "http.server" in command
        and "--bind 127.0.0.1" in command
        and str(serving_root) in command
    )


def stop_design_server(archive: Path, project_root: Path) -> dict[str, Any]:
    """停止本次 ZIP 启动的静态服务，不触碰其他本地进程。"""
    artifact, _, _ = load_source(archive, project_root)
    state_path = design_server_state_path(artifact)
    if not state_path.is_file():
        return {"artifactPath": str(artifact), "status": "not_running"}
    try:
        server_state = json.loads(state_path.read_text(encoding="utf-8"))
        pid = int(server_state["pid"])
        serving_root = Path(server_state["servingRoot"]).resolve()
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise PipelineError(f"静态服务状态文件无效：{state_path}") from error

    if is_pid_alive(pid):
        if not _server_command_matches(pid, serving_root):
            raise PipelineError(f"拒绝终止未验证的进程 PID {pid}；请手动检查：{state_path}")
        process = DESIGN_SERVER_PROCESSES.pop(pid, None)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        else:
            deadline = time.monotonic() + 2
            while is_pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            if is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    state_path.unlink(missing_ok=True)
    return {"artifactPath": str(artifact), "status": "stopped", "pid": pid}


def start_design_server(archive: Path, project_root: Path, port: int = 0) -> dict[str, Any]:
    """启动只监听 127.0.0.1 的设计稿静态服务，并记录可安全回收的 PID。"""
    if not 0 <= port <= 65535:
        raise PipelineError(f"端口必须在 0 到 65535 之间：{port}")
    artifact, source, _ = load_source(archive, project_root)
    state_path = design_server_state_path(artifact)
    if state_path.is_file():
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        previous_pid = int(previous.get("pid", -1))
        if is_pid_alive(previous_pid):
            raise PipelineError(f"设计稿静态服务已在运行（PID {previous_pid}）；请先执行 stop-design-server")
        state_path.unlink()

    cached_design = _load_cached_design(artifact, source)
    if cached_design is not None:
        design, screenshot_path = cached_design
        return {
            "artifactPath": str(artifact),
            "designPath": str(artifact / DESIGN_DOCUMENT_NAME),
            "screenshotPath": str(screenshot_path),
            "设计根节点": design["设计根节点"],
            "cacheHit": True,
            "sourceReused": True,
        }

    serving_root = artifact / "design-server-source"
    source_reused = _has_complete_design_server_source(archive, serving_root, source["sourceMd5"])
    if not source_reused:
        if serving_root.exists():
            shutil.rmtree(serving_root)
        _safe_extract_archive(archive.expanduser().resolve(), serving_root)
        atomic_json(
            design_server_source_state_path(artifact),
            {"version": 1, "sourceMd5": source["sourceMd5"], "createdAt": utc_now()},
        )
    html_path = serving_root / source["html"]["path"]
    if not html_path.is_file():
        raise PipelineError(f"解压后找不到设计入口 HTML：{html_path}")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", port))
    selected_port = listener.getsockname()[1]
    listener.close()
    command = [sys.executable, "-m", "http.server", str(selected_port), "--bind", "127.0.0.1", "--directory", str(serving_root)]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    DESIGN_SERVER_PROCESSES[process.pid] = process
    try:
        _wait_for_loopback_server(selected_port, process)
    except Exception:
        if is_pid_alive(process.pid):
            os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
        DESIGN_SERVER_PROCESSES.pop(process.pid, None)
        raise
    state = {
        "version": 1,
        "pid": process.pid,
        "port": selected_port,
        "url": f"http://127.0.0.1:{selected_port}/{source['html']['path']}",
        "servingRoot": str(serving_root.resolve()),
        "sourceMd5": source["sourceMd5"],
        "startedAt": utc_now(),
    }
    atomic_json(state_path, state)
    return {"artifactPath": str(artifact), "statePath": str(state_path), "cacheHit": False, "sourceReused": source_reused, **state}


def capture_rendered_design(archive: Path, project_root: Path) -> dict[str, Any]:
    """读取本机浏览器最终渲染结果，并原子写入可追溯的设计解析文件。"""
    artifact, source, _ = load_source(archive, project_root)
    cached_design = _load_cached_design(artifact, source)
    if cached_design is not None:
        design, screenshot_path = cached_design
        return {
            "artifactPath": str(artifact),
            "designPath": str(artifact / DESIGN_DOCUMENT_NAME),
            "screenshotPath": str(screenshot_path),
            "设计根节点": design["设计根节点"],
            "cacheHit": True,
        }
    state_path = design_server_state_path(artifact)
    if not state_path.is_file():
        raise PipelineError("尚未启动设计稿静态服务，请先执行 start-design-server")
    try:
        server = json.loads(state_path.read_text(encoding="utf-8"))
        if server.get("sourceMd5") != source["sourceMd5"]:
            raise PipelineError("设计稿静态服务与当前 ZIP 不匹配")
        if not is_pid_alive(int(server["pid"])):
            raise PipelineError("设计稿静态服务已停止，请重新执行 start-design-server")
        url = str(server["url"])
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise PipelineError(f"静态服务状态文件无效：{state_path}") from error

    if not CHROME_EXECUTABLE.is_file():
        raise PipelineError(f"未找到本机 Google Chrome，无法采集最终布局：{CHROME_EXECUTABLE}")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise PipelineError("缺少 Playwright，无法采集浏览器最终布局") from error

    script = """
        () => {
          const root = document.querySelector('.page');
          if (!root) return null;
          const rect = (node) => {
            const value = node.getBoundingClientRect();
            return { x: value.x, y: value.y, width: value.width, height: value.height };
          };
          const visible = (style, bounds) =>
            style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 &&
            bounds.width > 0 && bounds.height > 0;
          const styleData = (style) => ({
            display: style.display, flexDirection: style.flexDirection, justifyContent: style.justifyContent,
            alignItems: style.alignItems, gap: style.gap, padding: style.padding, margin: style.margin,
            overflow: style.overflow, color: style.color, backgroundColor: style.backgroundColor,
            backgroundImage: style.backgroundImage, border: style.border, borderRadius: style.borderRadius,
            boxShadow: style.boxShadow, opacity: style.opacity, zIndex: style.zIndex, transform: style.transform,
            fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight,
            lineHeight: style.lineHeight, letterSpacing: style.letterSpacing, textAlign: style.textAlign,
            objectFit: style.objectFit
          });
          const nodes = [];
          const walk = (node, parentIndex) => {
            const bounds = rect(node);
            const style = getComputedStyle(node);
            const index = nodes.length;
            nodes.push({
              parentIndex, tag: node.tagName.toLowerCase(), id: node.id || null,
              classNames: Array.from(node.classList), text: Array.from(node.childNodes)
                .filter((child) => child.nodeType === Node.TEXT_NODE)
                .map((child) => child.textContent.trim()).filter(Boolean).join(' '),
              bounds, visible: visible(style, bounds), style: styleData(style)
            });
            Array.from(node.children).forEach((child) => walk(child, index));
          };
          walk(root, null);
          return {
            root: { selector: '.page', bounds: rect(root) },
            browser: { userAgent: navigator.userAgent, viewport: { width: window.innerWidth, height: window.innerHeight } },
            nodes,
            images: Array.from(root.querySelectorAll('img')).map((image) => ({
              source: image.currentSrc || image.src, naturalWidth: image.naturalWidth,
              naturalHeight: image.naturalHeight, bounds: rect(image), objectFit: getComputedStyle(image).objectFit
            }))
          };
        }
    """
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True, executable_path=str(CHROME_EXECUTABLE))
            try:
                page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
                page.goto(url, wait_until="networkidle")
                page.evaluate("() => document.fonts.ready")
                result = page.evaluate(script)
            finally:
                browser.close()
    except PlaywrightError as error:
        raise PipelineError(f"浏览器采集设计失败：{error}") from error
    if result is None:
        raise UserInputRequired("设计页未找到 .page 根节点，无法确定有效截图区域")

    bounds = result["root"]["bounds"]
    design = {
        "版本": DESIGN_DOCUMENT_VERSION,
        "来源名称": source["sourceName"],
        "来源路径": source["sourcePath"],
        "sourceMd5": source["sourceMd5"],
        "入口文件": source["html"]["path"],
        "样式文件": [item["path"] for item in source["css"]],
        "设计画布": {"宽度像素": round(bounds["width"]), "高度像素": round(bounds["height"])},
        "设计根节点": {"选择器": result["root"]["selector"], "边界": bounds},
        "浏览器环境": result["browser"],
        "节点": result["nodes"],
        "图片资源": result["images"],
        "采集时间": utc_now(),
    }
    design_path = artifact / DESIGN_DOCUMENT_NAME
    atomic_json(design_path, design)
    runs_root = artifact / "runs"
    screenshot_path = runs_root / "设计截图.png"
    if not screenshot_path.is_file():
        runs_root.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch(headless=True, executable_path=str(CHROME_EXECUTABLE))
                try:
                    page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
                    page.goto(url, wait_until="networkidle")
                    page.locator(design["设计根节点"]["选择器"]).screenshot(path=str(screenshot_path))
                finally:
                    browser.close()
        except PlaywrightError as error:
            raise PipelineError(f"浏览器截取设计图失败：{error}") from error
    return {
        "artifactPath": str(artifact),
        "designPath": str(design_path),
        "screenshotPath": str(screenshot_path),
        "设计根节点": design["设计根节点"],
        "cacheHit": False,
    }


def complete_design_screenshot(archive: Path, project_root: Path, image: Path) -> dict[str, Any]:
    """登记浏览器已保存的设计截图，并在任何结果下回收本地静态服务。"""
    artifact, source, state = load_source(archive, project_root)
    try:
        design_path = artifact / DESIGN_DOCUMENT_NAME
        if not design_path.is_file():
            raise PipelineError(f"缺少设计解析结果，无法登记设计截图：{design_path}")
        design = json.loads(design_path.read_text(encoding="utf-8"))
        if design.get("sourceMd5") != source["sourceMd5"]:
            raise PipelineError(f"设计解析结果与当前 ZIP 不匹配：{design_path}")
        image = image.expanduser().resolve()
        expected_image = (artifact / "runs" / "设计截图.png").resolve()
        if image != expected_image or not image.is_file():
            raise PipelineError("设计截图必须位于 artifact/runs/设计截图.png")
        state["designScreenshot"] = {"image": str(image), "capturedAt": utc_now()}
        state.setdefault("history", []).append({"phase": "design_screenshot", "at": utc_now(), "detail": state["designScreenshot"]})
        _write_state(artifact, state)
        return {"artifactPath": str(artifact), "image": str(image), "status": "recorded"}
    finally:
        stop_design_server(archive, project_root)


def ensure_design_evidence(archive: Path, project_root: Path) -> dict[str, Any]:
    """自动完成设计服务、浏览器采集、设计截图登记和服务回收。"""
    artifact, _, state = load_source(archive, project_root)
    recorded = state.get("designScreenshot")
    if isinstance(recorded, dict) and Path(str(recorded.get("image", ""))).is_file():
        return {"artifactPath": str(artifact), "status": "cached", "image": recorded["image"]}
    started = start_design_server(archive, project_root)
    try:
        captured = capture_rendered_design(archive, project_root)
        return complete_design_screenshot(archive, project_root, Path(captured["screenshotPath"]))
    finally:
        if not started.get("cacheHit"):
            stop_design_server(archive, project_root)


def import_assets(archive: Path, project_root: Path, compose_file: Path, apply: bool = True) -> dict[str, Any]:
    """由 Python 固定执行逐图导入、Hash 清单写入和生成基线记录。"""
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"preflight", "assets_imported"}:
        raise PipelineError(f"当前阶段不能 assets：{state['phase']}")
    compose_file = compose_file.expanduser().resolve()
    command = [
        sys.executable,
        str(Path(__file__).with_name("import_zip_images.py")),
        "--zip",
        str(archive),
        "--compose",
        str(compose_file),
        "--project-root",
        str(project_root),
    ]
    if apply:
        command.append("--apply")
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=False)
    (artifact / "logs").mkdir(exist_ok=True)
    (artifact / "logs" / "assets.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise PipelineError(f"资源导入失败，日志已写入：{artifact / 'logs' / 'assets.log'}")
    if not apply:
        return {"artifactPath": str(artifact), "phase": state["phase"], "preview": True}
    state["composeFile"] = str(compose_file)
    if state["phase"] != "assets_imported":
        transition(state, "assets_imported", {"composeFile": str(compose_file), "apply": True})
    state["composeBaselineMd5"] = md5_file(compose_file)
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "composeBaselineMd5": state["composeBaselineMd5"]}


def run_fixed_pipeline(archive: Path, project_root: Path, compose_file: Path) -> dict[str, Any]:
    """自动推进浏览器采集、资源导入和编译，只在等待页面代码时暂停。"""
    archive = archive.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    compose_file = compose_file.expanduser().resolve()
    inspect_archive(archive, project_root, compose_file)
    design = ensure_design_evidence(archive, project_root)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "inspected":
        validate_project(archive, project_root, compose_file)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "validated":
        preflight_project(archive, project_root)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "preflight":
        import_assets(archive, project_root, compose_file, apply=True)
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] == "assets_imported":
        baseline = state.get("composeBaselineMd5")
        current = md5_file(compose_file)
        if not isinstance(baseline, str):
            state["composeBaselineMd5"] = current
            _write_state(artifact, state)
            baseline = current
        if current == baseline:
            return {"artifactPath": str(artifact), "phase": state["phase"], "status": "awaiting_compose_generation", "design": design}
        validate_compose_source(compose_file)
        state["composeFile"] = str(compose_file)
        transition(state, "generated", {"composeFile": str(compose_file), "composeMd5": current})
        _write_state(artifact, state)
        compile_project(archive, project_root)
        return {"artifactPath": str(artifact), "phase": "compiled", "status": "compile_started", "design": design}
    if state["phase"] == "generated":
        compile_project(archive, project_root)
        return {"artifactPath": str(artifact), "phase": "compiled", "status": "compile_started", "design": design}
    return {"artifactPath": str(artifact), "phase": state["phase"], "status": "unchanged", "design": design}


def validate_project(archive: Path, project_root: Path, compose_file: Path | None = None) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] not in {"inspected", "validated"}:
        raise PipelineError(f"当前阶段不能 validate：{state['phase']}")
    target = compose_file or (Path(state["composeFile"]) if state.get("composeFile") else None)
    if target is None:
        raise PipelineError("validate 必须提供目标 Compose 文件")
    if target is not None:
        target = target.expanduser().resolve()
        root = project_root.expanduser().resolve()
        if root not in target.parents and target != root:
            raise PipelineError(f"Compose 目标必须位于项目根目录内：{target}")
        if not target.is_file():
            raise PipelineError(f"Compose 目标不存在：{target}")
        validate_compose_source(target)
        state["composeFile"] = str(target)
    transition(state, "validated", {"composeFile": state.get("composeFile")})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "sourceMd5": source["sourceMd5"]}


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


def gradle_command(project_root: Path) -> list[str]:
    """在项目根目录优先执行 Gradle Wrapper，缺失时回退系统 Gradle。"""
    root = project_root.expanduser().resolve()
    if (root / "gradlew").is_file():
        return ["./gradlew"]
    if shutil.which("gradle"):
        return ["gradle"]
    raise PipelineError(f"项目根目录缺少 ./gradlew，且系统未安装 gradle：{root}")


def compose_gradle_module(project_root: Path, compose_file: Path) -> str:
    """根据目标 Compose 文件路径确定 Gradle 模块，避免由调用方猜 task。"""
    root = project_root.expanduser().resolve()
    target = compose_file.expanduser().resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise PipelineError(f"Compose 文件必须位于项目根目录内：{target}") from error
    parts = relative.parts
    try:
        source_index = parts.index("src")
    except ValueError as error:
        raise PipelineError(f"无法从 Compose 路径识别 Gradle 模块（缺少 src）：{target}") from error
    module_parts = parts[:source_index]
    return ":" + ":".join(module_parts) if module_parts else ""


def _normalize_gradle_task(task: str) -> str:
    value = task.strip()
    return value if value.startswith(":") else f":{value}"


def discover_compile_task(project_root: Path, compose_file: Path) -> str:
    """由 Gradle 任务列表确定目标模块的稳定 Debug Kotlin 编译任务。"""
    root = project_root.expanduser().resolve()
    module = compose_gradle_module(root, compose_file)
    result = subprocess.run(
        [*gradle_command(root), "tasks", "--all", "--console=plain"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise PipelineError(f"无法读取 Gradle 任务列表：{result.stderr.strip() or result.stdout.strip()}")

    candidates = []
    for line in result.stdout.splitlines():
        match = GRADLE_COMPILE_TASK.match(line)
        if not match:
            continue
        task = _normalize_gradle_task(match.group(1))
        if module and not task.startswith(f"{module}:"):
            continue
        task_name = task.rsplit(":", 1)[-1]
        if "AndroidTest" in task_name or "UnitTest" in task_name or task_name.endswith("TestKotlin"):
            continue
        candidates.append(task)

    candidates = sorted(set(candidates))
    if not candidates:
        raise PipelineError(f"未找到模块 {module or ':root'} 的 Kotlin 编译任务，不能让模型猜测 Gradle task")

    exact_debug = [task for task in candidates if task.endswith(":compileDebugKotlin")]
    if len(exact_debug) == 1:
        return exact_debug[0]
    debug_candidates = [task for task in candidates if task.endswith("DebugKotlin")]
    if len(debug_candidates) == 1:
        return debug_candidates[0]
    if len(debug_candidates) > 1:
        raise PipelineError(f"模块 {module or ':root'} 存在多个 Debug Kotlin 编译任务，请用户明确选择：{debug_candidates}")
    if len(candidates) == 1:
        return candidates[0]
    raise PipelineError(f"模块 {module or ':root'} 的 Kotlin 编译任务存在歧义，请用户明确选择：{candidates}")


def record_decision(archive: Path, project_root: Path, decision_path: Path) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    decision = validate_decision(json.loads(decision_path.read_text(encoding="utf-8")))
    if decision["action"] == "apply_patch":
        root = project_root.expanduser().resolve()
        target = (root / decision["target"]).resolve()
        if root not in target.parents:
            raise PipelineError("apply_patch target 必须解析到项目根目录内")
    index = len(list(artifact.glob("decision-*.json"))) + 1
    atomic_json(artifact / f"decision-{index:02d}.json", {**decision, "recordedAt": utc_now(), "phase": state["phase"]})
    if decision["action"] == "ask_user":
        atomic_json(artifact / "needs-user-input.json", {**decision, "recordedAt": utc_now()})
        raise UserInputRequired(decision["question"])
    return {"artifactPath": str(artifact), "action": decision["action"], "phase": state["phase"]}


def compile_project(archive: Path, project_root: Path) -> dict[str, Any]:
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] not in {"generated", "compiled"}:
        raise PipelineError(f"当前阶段不能 compile：{state['phase']}")
    task = state.get("preflightTask")
    if not isinstance(task, str) or not task:
        raise PipelineError("compile 必须复用 Python preflight 已确定的任务")
    if not SAFE_TASK.fullmatch(task):
        raise PipelineError(f"Gradle task 不在白名单中：{task}")
    gradle = gradle_command(project_root)
    state["attempts"]["compile"] = state["attempts"].get("compile", 0) + 1
    if state.get("preflightTask") != task:
        raise PipelineError(f"compile 必须复用 preflight 任务：{state.get('preflightTask')!r} != {task!r}")
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("compile 缺少 Compose 文件，无法执行布局安全检查")
    validate_compose_source(Path(compose_file))
    log = artifact / "logs" / f"compile-{state['attempts']['compile']:02d}.log"
    result = _run_fixed([*gradle, task, "--console=plain"], project_root, log)
    if result.returncode != 0:
        raise PipelineError(f"编译失败，日志已写入：{log}")
    if state["phase"] != "compiled":
        transition(state, "compiled", {"task": task, "log": str(log)})
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "log": str(log)}


def preflight_project(archive: Path, project_root: Path) -> dict[str, Any]:
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"validated", "preflight"}:
        raise PipelineError(f"当前阶段不能 preflight：{state['phase']}")
    compose_file = state.get("composeFile")
    if not isinstance(compose_file, str) or not compose_file:
        raise PipelineError("preflight 缺少 Compose 文件，无法由 Python 解析 Gradle 模块")
    task = discover_compile_task(project_root, Path(compose_file))
    if not SAFE_TASK.fullmatch(task):
        raise PipelineError(f"Gradle task 不在白名单中：{task}")
    gradle = gradle_command(project_root)
    log = artifact / "logs" / "preflight.log"
    result = _run_fixed([*gradle, task, "--console=plain"], project_root, log)
    if result.returncode != 0:
        raise PipelineError(f"预检编译失败，日志已写入：{log}")
    if state["phase"] != "preflight":
        transition(state, "preflight", {"task": task, "log": str(log)})
    state["preflightTask"] = task
    state["preflightTaskSource"] = "python-discovered"
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "log": str(log)}


def install_k80(archive: Path, project_root: Path, serial: str, expected_avd: str, apk: Path) -> dict[str, Any]:
    if expected_avd != "K80":
        raise PipelineError("install-k80 固定要求项目约束中的 K80 模拟器")
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


def next_evidence_path(directory: Path, filename: str) -> Path:
    """返回目录内未占用的证据文件名：先用原名，再追加 _1、_2……。"""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    suffix = candidate.suffix
    stem = candidate.stem
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def screenshot_k80(archive: Path, project_root: Path, serial: str, expected_avd: str = "K80") -> dict[str, Any]:
    if not SAFE_SERIAL.fullmatch(serial):
        raise PipelineError(f"ADB serial 不安全：{serial}")
    artifact, _, state = load_source(archive, project_root)
    if state["phase"] not in {"installed", "screenshot"}:
        raise PipelineError(f"当前阶段不能 screenshot：{state['phase']}")
    if expected_avd != "K80":
        raise PipelineError("screenshot-k80 固定要求项目约束中的 K80 模拟器")
    probe = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise PipelineError(f"无法读取模拟器名称：{probe.stderr.strip()}")
    validate_device_name(probe.stdout.strip(), expected_avd)
    destination = artifact / "runs"
    destination.mkdir(parents=True, exist_ok=True)
    image = next_evidence_path(destination, "应用截图.png")
    with image.open("wb") as output:
        result = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise PipelineError(f"截图失败：{result.stderr.decode(errors='replace').strip()}")
    if state["phase"] != "screenshot":
        transition(state, "screenshot", {"serial": serial, "image": str(image)})
    state["lastScreenshot"] = str(image)
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], "image": str(image)}


def code_image_compare_script() -> Path:
    """定位 code-image 的独立图片对比脚本，不把对比实现复制到本 Skill。"""
    candidates: list[Path] = []
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "skills" / "code-image" / "scripts" / "compare_images.py")
    candidates.append(Path.home() / ".codex" / "skills" / "code-image" / "scripts" / "compare_images.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise PipelineError(f"找不到 code-image 图片对比脚本，已检查：{searched}")


def _latest_app_screenshot(artifact: Path, state: dict[str, Any]) -> Path:
    """取得最近一次由 screenshot-k80 登记的 App 截图，并限制在证据目录内。"""
    candidates: list[Path] = []
    if state.get("lastScreenshot"):
        candidates.append(Path(str(state["lastScreenshot"])))
    for history in reversed(state.get("history", [])):
        detail = history.get("detail", {}) if isinstance(history, dict) else {}
        image = detail.get("image") if isinstance(detail, dict) else None
        if image:
            candidates.append(Path(str(image)))
    runs = (artifact / "runs").resolve()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if runs in resolved.parents and resolved.is_file():
            return resolved
    raise PipelineError("找不到最近一次 App 截图，请先执行 screenshot-k80")


def compare_screenshots(archive: Path, project_root: Path) -> dict[str, Any]:
    """调用 code-image 的独立视觉对比脚本，生成可追溯的差异证据。"""
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] != "screenshot":
        raise PipelineError(f"当前阶段不能 compare-screenshots：{state['phase']}")
    runs = artifact / "runs"
    design = runs / "设计截图.png"
    if not design.is_file():
        raise PipelineError(f"设计截图不存在：{design}")
    app = _latest_app_screenshot(artifact, state)
    output_dir = runs
    log_path = artifact / "logs" / "compare-images.log"
    command = [
        sys.executable,
        str(code_image_compare_script()),
        "--design",
        str(design),
        "--app",
        str(app),
        "--output-dir",
        str(output_dir),
    ]
    completed = _run_fixed(command, project_root.resolve(), log_path)
    if completed.returncode != 0:
        raise PipelineError(f"图片对比失败，日志已写入：{log_path}")
    report = output_dir / "diff.json"
    if not report.is_file():
        raise PipelineError(f"图片对比未生成差异报告：{report}")
    try:
        report_data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError(f"图片对比生成的报告不是有效 JSON：{report}") from error
    if not isinstance(report_data, dict):
        raise PipelineError(f"图片对比报告必须是 JSON 对象：{report}")
    report_data["sourceMd5"] = source["sourceMd5"]
    report_data["designScreenshot"] = str(design)
    report_data["appScreenshot"] = str(app)
    atomic_json(report, report_data)
    state["comparison"] = {
        "report": str(report),
        "designScreenshot": str(design),
        "appScreenshot": str(app),
        "metrics": report_data.get("metrics", {}),
    }
    state.setdefault("history", []).append(
        {"phase": "compared", "at": utc_now(), "detail": state["comparison"]}
    )
    _write_state(artifact, state)
    return {"artifactPath": str(artifact), "phase": state["phase"], **state["comparison"]}


def mark_diff(archive: Path, project_root: Path, report: Path | None, outcome: str) -> dict[str, Any]:
    if outcome not in {"pass", "repair", "stop"}:
        raise PipelineError("diff outcome 必须是 pass、repair 或 stop")
    artifact, source, state = load_source(archive, project_root)
    if state["phase"] != "screenshot":
        raise PipelineError(f"当前阶段不能 mark-diff：{state['phase']}")
    if report is None:
        report = Path(compare_screenshots(archive, project_root)["report"])
        artifact, source, state = load_source(archive, project_root)
    report = report.expanduser().resolve()
    if artifact not in report.parents or not report.is_file():
        raise PipelineError(f"差异报告不存在：{report}")
    try:
        report_data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PipelineError(f"差异报告不是有效 JSON：{report}") from error
    if not isinstance(report_data, dict):
        raise PipelineError(f"差异报告必须是 JSON 对象：{report}")
    if report_data.get("sourceMd5") not in (None, source["sourceMd5"]):
        raise PipelineError("差异报告 sourceMd5 与当前 ZIP 不一致")
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
    parser = argparse.ArgumentParser(description="固定执行蓝湖 Compose 还原流程")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--zip", required=True, type=Path)
    inspect.add_argument("--project-root", required=True, type=Path)
    inspect.add_argument("--compose", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--zip", required=True, type=Path)
    validate.add_argument("--project-root", required=True, type=Path)
    validate.add_argument("--compose", required=True, type=Path)
    assets = subparsers.add_parser("assets")
    assets.add_argument("--zip", required=True, type=Path)
    assets.add_argument("--project-root", required=True, type=Path)
    assets.add_argument("--compose", required=True, type=Path)
    assets.add_argument("--apply", action="store_true")
    fixed = subparsers.add_parser("run-fixed", help="自动执行设计采集、资源导入和编译，仅在等待 Compose 生成时暂停")
    fixed.add_argument("--zip", required=True, type=Path)
    fixed.add_argument("--project-root", required=True, type=Path)
    fixed.add_argument("--compose", required=True, type=Path)
    generated = subparsers.add_parser("mark-generated")
    generated.add_argument("--zip", required=True, type=Path)
    generated.add_argument("--project-root", required=True, type=Path)
    generated.add_argument("--compose", required=True, type=Path)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--zip", required=True, type=Path)
    preflight.add_argument("--project-root", required=True, type=Path)
    compile_command = subparsers.add_parser("compile")
    compile_command.add_argument("--zip", required=True, type=Path)
    compile_command.add_argument("--project-root", required=True, type=Path)
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
    screenshot.add_argument("--expected-avd", default="K80")
    start_design_server_command = subparsers.add_parser("start-design-server")
    start_design_server_command.add_argument("--zip", required=True, type=Path)
    start_design_server_command.add_argument("--project-root", required=True, type=Path)
    start_design_server_command.add_argument("--port", type=int, default=0)
    capture_design = subparsers.add_parser("采集设计", help="采集浏览器最终布局并写入设计解析文件")
    capture_design.add_argument("--zip", required=True, type=Path)
    capture_design.add_argument("--project-root", required=True, type=Path)
    screenshot_design = subparsers.add_parser("screenshot-design")
    screenshot_design.add_argument("--zip", required=True, type=Path)
    screenshot_design.add_argument("--project-root", required=True, type=Path)
    screenshot_design.add_argument("--image", required=True, type=Path)
    stop_design_server_command = subparsers.add_parser("stop-design-server")
    stop_design_server_command.add_argument("--zip", required=True, type=Path)
    stop_design_server_command.add_argument("--project-root", required=True, type=Path)
    compare = subparsers.add_parser("compare-screenshots", help="调用 code-image 独立视觉对比脚本")
    compare.add_argument("--zip", required=True, type=Path)
    compare.add_argument("--project-root", required=True, type=Path)
    diff = subparsers.add_parser("mark-diff")
    diff.add_argument("--zip", required=True, type=Path)
    diff.add_argument("--project-root", required=True, type=Path)
    diff.add_argument("--report", type=Path, help="已有差异报告；省略时自动调用 compare-screenshots")
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
            result = import_assets(args.zip, args.project_root, args.compose, apply=args.apply)
        elif args.command == "run-fixed":
            result = run_fixed_pipeline(args.zip, args.project_root, args.compose)
        elif args.command == "mark-generated":
            artifact, _, state = load_source(args.zip, args.project_root)
            if state["phase"] not in {"assets_imported", "generated"}:
                raise PipelineError(f"当前阶段不能 mark-generated：{state['phase']}")
            target = args.compose.resolve()
            if not target.is_file() or args.project_root.resolve() not in target.parents:
                raise PipelineError(f"Compose 目标不存在或不在项目内：{target}")
            validate_compose_source(target)
            state["composeFile"] = str(target)
            if state["phase"] != "generated":
                transition(state, "generated", {"composeFile": str(target)})
            _write_state(artifact, state)
            result = {"artifactPath": str(artifact), "phase": state["phase"], "composeFile": str(target)}
        elif args.command == "preflight":
            result = preflight_project(args.zip, args.project_root)
        elif args.command == "compile":
            result = compile_project(args.zip, args.project_root)
        elif args.command == "install-k80":
            result = install_k80(args.zip, args.project_root, args.serial, args.expected_avd, args.apk)
        elif args.command == "screenshot-k80":
            result = screenshot_k80(args.zip, args.project_root, args.serial, args.expected_avd)
        elif args.command == "start-design-server":
            result = start_design_server(args.zip, args.project_root, args.port)
        elif args.command == "采集设计":
            result = capture_rendered_design(args.zip, args.project_root)
        elif args.command == "screenshot-design":
            result = complete_design_screenshot(args.zip, args.project_root, args.image)
        elif args.command == "stop-design-server":
            result = stop_design_server(args.zip, args.project_root)
        elif args.command == "compare-screenshots":
            result = compare_screenshots(args.zip, args.project_root)
        elif args.command == "mark-diff":
            result = mark_diff(args.zip, args.project_root, args.report, args.outcome)
        elif args.command == "complete":
            result = complete_pipeline(args.zip, args.project_root)
        elif args.command == "record-decision":
            result = record_decision(args.zip, args.project_root, args.decision)
        elif args.command == "status":
            artifact, source, state = load_source(args.zip, args.project_root)
            result = {"artifactPath": str(artifact), "sourceMd5": source["sourceMd5"], **state}
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
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "blocked", "error": f"输入或状态文件无法处理：{error}"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
