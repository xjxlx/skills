/**
 * Compose 页面统一验证器。
 *
 * 一次运行完成以下检查：
 *   1. 启动 IDE 已经运行并安装好的目标 Activity，不执行构建、安装或长时间固定等待。
 *   2. 截取当前页面并与 original.png 做整页像素对比。
 *   3. 通过 uiautomator 提取 e<domIndex> 边界，与 HTML 语义树比对。
 *   4. 对文本和关键区域做局部色差抽查。
 *   5. 输出统一报告、差异图、热点和差异区域。
 */
const fs = require('node:fs');
const path = require('node:path');
const { execSync } = require('node:child_process');
const { PNG } = require('pngjs');
const {
  evaluateReferenceDimensions,
  evaluateStructure,
  selectSpotCandidates,
  shouldAcceptReport,
} = require('./compose-validation-core');
const {
  ADB,
  TOOL_OUTPUT_DIR,
  WORK_DIR,
} = require('./config');
const { loadOrCreateRuntimeContext } = require('./runtime-context');

const INPUT_DIR = TOOL_OUTPUT_DIR;
const SEMANTIC = path.join(INPUT_DIR, 'semantic.json');
const GENERATION_REPORT = path.join(INPUT_DIR, 'compose-generation-report.json');
const DESIGN_PNG = path.join(INPUT_DIR, 'original.png');
const SHOT = path.join(INPUT_DIR, 'compose-shot.png');
const UI_XML = path.join(INPUT_DIR, 'ui.xml');

const TOL_XY = parseFloat(process.env.VALIDATE_TOL_XY || '4');
const TOL_WH = parseFloat(process.env.VALIDATE_TOL_WH || '4');
const TOL_TEXT_WH = parseFloat(process.env.VALIDATE_TOL_TEXT_WH || process.env.VALIDATE_TOL_TEXT_H || '6');
const STRUCT_PASS = parseFloat(process.env.VALIDATE_STRUCT_PASS || '0.95');
const SPOT_PASS = parseFloat(process.env.VALIDATE_SPOT_PASS || '0.8');
const PIXEL_PASS = parseFloat(process.env.VALIDATE_PIXEL_PASS || '0.95');
const SPOT_COUNT = parseInt(process.env.VALIDATE_SPOT_COUNT || '8', 10);
const SPOT_DIST = parseFloat(process.env.VALIDATE_SPOT_DIST || '0.18');
const READY_ATTEMPTS = parseInt(process.env.VALIDATE_READY_ATTEMPTS || '10', 10);
const READY_INTERVAL_MS = parseInt(process.env.VALIDATE_READY_INTERVAL_MS || '200', 10);
const DIFF_THRESHOLD = 40;
const GRID_COLS = 10;
const GRID_ROWS = 5;

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function load(p) {
  return PNG.sync.read(fs.readFileSync(p));
}

function composite(img) {
  const { width, height, data } = img;
  const out = new Uint8ClampedArray(width * height * 3);
  for (let i = 0; i < width * height; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    const a = data[i * 4 + 3] / 255;
    out[i * 3] = Math.round(r * a + 255 * (1 - a));
    out[i * 3 + 1] = Math.round(g * a + 255 * (1 - a));
    out[i * 3 + 2] = Math.round(b * a + 255 * (1 - a));
  }
  return { width, height, data: out };
}

function resizeRGB(img, tw, th) {
  if (img.width === tw && img.height === th) return img;
  const sw = img.width;
  const sh = img.height;
  const data = img.data;
  const out = { width: tw, height: th, data: new Uint8ClampedArray(tw * th * 3) };
  const sx = sw / tw;
  const sy = sh / th;
  for (let y = 0; y < th; y++) {
    const gy = y * sy;
    const y0 = Math.min(Math.floor(gy), sh - 1);
    const y1 = Math.min(y0 + 1, sh - 1);
    const fy = gy - y0;
    for (let x = 0; x < tw; x++) {
      const gx = x * sx;
      const x0 = Math.min(Math.floor(gx), sw - 1);
      const x1 = Math.min(x0 + 1, sw - 1);
      const fx = gx - x0;
      const oi = (y * tw + x) * 3;
      for (let c = 0; c < 3; c++) {
        const v00 = data[(y0 * sw + x0) * 3 + c];
        const v10 = data[(y0 * sw + x1) * 3 + c];
        const v01 = data[(y1 * sw + x0) * 3 + c];
        const v11 = data[(y1 * sw + x1) * 3 + c];
        const top = v00 + (v10 - v00) * fx;
        const bot = v01 + (v11 - v01) * fx;
        out.data[oi + c] = Math.round(top + (bot - top) * fy);
      }
    }
  }
  return out;
}

function crop(img, x, y, w, h, tw, th) {
  const out = new Uint8ClampedArray(tw * th * 3);
  for (let j = 0; j < th; j++) {
    const sy = Math.min(y + Math.floor((j / th) * h), img.height - 1);
    for (let i = 0; i < tw; i++) {
      const sx = Math.min(x + Math.floor((i / tw) * w), img.width - 1);
      const si = (sy * img.width + sx) * 3;
      const di = (j * tw + i) * 3;
      out[di] = img.data[si];
      out[di + 1] = img.data[si + 1];
      out[di + 2] = img.data[si + 2];
    }
  }
  return out;
}

function regionAvgDist(a, b) {
  let sum = 0;
  const count = a.length / 3;
  for (let i = 0; i < count; i++) {
    const dr = a[i * 3] - b[i * 3];
    const dg = a[i * 3 + 1] - b[i * 3 + 1];
    const db = a[i * 3 + 2] - b[i * 3 + 2];
    sum += Math.sqrt(dr * dr + dg * dg + db * db) / Math.sqrt(255 * 255 * 3);
  }
  return sum / Math.max(1, count);
}

function compareFullPage(shot, design) {
  const width = design.width;
  const height = design.height;
  const count = width * height;
  const grid = Array.from({ length: GRID_COLS * GRID_ROWS }, () => 0);
  const gridPixels = Array.from({ length: GRID_COLS * GRID_ROWS }, () => 0);
  const mask = new Uint8Array(count);
  let totalDiff = 0;
  let diffPixels = 0;

  for (let i = 0; i < count; i++) {
    const dr = shot.data[i * 3] - design.data[i * 3];
    const dg = shot.data[i * 3 + 1] - design.data[i * 3 + 1];
    const db = shot.data[i * 3 + 2] - design.data[i * 3 + 2];
    const normalizedDistance = Math.sqrt(dr * dr + dg * dg + db * db) / Math.sqrt(255 * 255 * 3);
    totalDiff += normalizedDistance;
    const px = Math.floor((i % width) / width * GRID_COLS);
    const py = Math.floor(Math.floor(i / width) / height * GRID_ROWS);
    const gridIndex = py * GRID_COLS + px;
    gridPixels[gridIndex]++;
    if (normalizedDistance * Math.sqrt(3) > DIFF_THRESHOLD / 255) {
      diffPixels++;
      grid[gridIndex]++;
      mask[i] = 1;
    }
  }

  const hotspots = grid.map((diffPx, index) => ({
    col: index % GRID_COLS,
    row: Math.floor(index / GRID_COLS),
    diffRatio: diffPx / Math.max(1, gridPixels[index]),
    diffPx,
  })).sort((a, b) => b.diffRatio - a.diffRatio);

  const regions = [];
  const visited = new Uint8Array(count);
  const stack = [];
  for (let i = 0; i < count; i++) {
    if (!mask[i] || visited[i]) continue;
    let minX = width;
    let minY = height;
    let maxX = 0;
    let maxY = 0;
    let pixels = 0;
    stack.push(i);
    visited[i] = 1;
    while (stack.length) {
      const current = stack.pop();
      const x = current % width;
      const y = Math.floor(current / width);
      pixels++;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      for (const neighbor of [current - 1, current + 1, current - width, current + width]) {
        if (neighbor < 0 || neighbor >= count) continue;
        const nx = neighbor % width;
        const ny = Math.floor(neighbor / width);
        if (Math.abs(nx - x) + Math.abs(ny - y) !== 1) continue;
        if (mask[neighbor] && !visited[neighbor]) {
          visited[neighbor] = 1;
          stack.push(neighbor);
        }
      }
    }
    regions.push({ x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1, diffPx: pixels });
  }
  regions.sort((a, b) => b.diffPx - a.diffPx);

  return {
    similarity: 1 - totalDiff / count,
    diffPixelRatio: diffPixels / count,
    hotspots: hotspots.slice(0, 8),
    diffRegions: regions.slice(0, 12),
  };
}

function writePx(img, x, y, r, g, b) {
  const index = (y * img.width + x) * 4;
  img.data[index] = r;
  img.data[index + 1] = g;
  img.data[index + 2] = b;
  img.data[index + 3] = 255;
}

function writeDiffImage(shot, design, outputPath) {
  const width = design.width;
  const height = design.height;
  const canvas = new PNG({ width: width * 3, height });
  for (let i = 0; i < width * height; i++) {
    const x = i % width;
    const y = Math.floor(i / width);
    const dr = design.data[i * 3] - shot.data[i * 3];
    const dg = design.data[i * 3 + 1] - shot.data[i * 3 + 1];
    const db = design.data[i * 3 + 2] - shot.data[i * 3 + 2];
    const isDiff = Math.sqrt(dr * dr + dg * dg + db * db) > DIFF_THRESHOLD;
    writePx(canvas, x, y, design.data[i * 3], design.data[i * 3 + 1], design.data[i * 3 + 2]);
    writePx(canvas, width + x, y, shot.data[i * 3], shot.data[i * 3 + 1], shot.data[i * 3 + 2]);
    writePx(canvas, width * 2 + x, y, 255, isDiff ? 0 : 255, isDiff ? 0 : 255);
  }
  fs.writeFileSync(outputPath, PNG.sync.write(canvas));
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function launch(activity) {
  const packageName = activity.split('/')[0];
  execSync(`${ADB} shell am force-stop ${packageName}`, { stdio: 'ignore', shell: true });
  const output = execSync(`${ADB} shell am start -W -n ${activity}`, {
    encoding: 'utf8',
    shell: true,
  });
  if (/Error|Exception/i.test(output) && !/Status: ok/i.test(output)) {
    throw new Error(`Activity 启动失败：${output.trim()}`);
  }
}

function readBounds(scaleX, scaleY) {
  execSync(`${ADB} shell uiautomator dump /sdcard/ui.xml`, { stdio: 'ignore', shell: true });
  execSync(`${ADB} pull /sdcard/ui.xml "${UI_XML}"`, { stdio: 'ignore', shell: true });
  const xml = fs.readFileSync(UI_XML, 'utf8');
  const map = {};
  const pattern = /<node[^>]*resource-id="(e\d+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/g;
  let match;
  while ((match = pattern.exec(xml))) {
    map[match[1]] = {
      x: Number(match[2]) / scaleX,
      y: Number(match[3]) / scaleY,
      w: (Number(match[4]) - Number(match[2])) / scaleX,
      h: (Number(match[5]) - Number(match[3])) / scaleY,
    };
  }
  return map;
}

function waitForBounds(scaleX, scaleY, expectedCount) {
  let bounds = {};
  for (let attempt = 0; attempt < READY_ATTEMPTS; attempt++) {
    bounds = readBounds(scaleX, scaleY);
    if (Object.keys(bounds).length >= expectedCount) return bounds;
    if (attempt + 1 < READY_ATTEMPTS) sleepSync(READY_INTERVAL_MS);
  }
  return bounds;
}

function main() {
  const runtime = loadOrCreateRuntimeContext();
  const activity = process.argv[2] || runtime.activity;

  if (!fs.existsSync(SEMANTIC)) {
    console.error(`语义树不存在：${SEMANTIC}`);
    process.exit(1);
  }
  if (!fs.existsSync(DESIGN_PNG)) {
    console.error(`原始设计截图不存在：${DESIGN_PNG}`);
    process.exit(1);
  }
  if (!fs.existsSync(GENERATION_REPORT)) {
    console.error(`Compose 生成报告不存在：${GENERATION_REPORT}`);
    process.exit(1);
  }

  const semantic = JSON.parse(fs.readFileSync(SEMANTIC, 'utf8'));
  if (semantic.designW !== 1334 || semantic.designH !== 750) {
    console.error(`设计稿尺寸不匹配：需要 1334x750，实际为 ${semantic.designW}x${semantic.designH}`);
    process.exit(1);
  }

  const generation = JSON.parse(fs.readFileSync(GENERATION_REPORT, 'utf8'));
  const observableIndices = new Set(generation.observableDomIndices || []);
  const observableElements = semantic.elements.filter((element) => observableIndices.has(element.domIndex));
  if (observableElements.length !== generation.observableElementCount) {
    console.error('Compose 生成报告与 semantic.json 不一致，请重新生成 Compose。');
    process.exit(1);
  }

  console.log(`启动 Activity：${activity}`);
  launch(activity);

  // 使用当前真实窗口计算坐标缩放；不修改模拟器窗口、density 或旋转。
  execSync(`${ADB} exec-out screencap -p > "${SHOT}"`, { shell: true });
  const initialShot = load(SHOT);
  if (initialShot.width <= initialShot.height) {
    throw new Error(`模拟器截图仍为竖屏 ${initialShot.width}x${initialShot.height}，请先把模拟器旋转到横屏。`);
  }
  const scaleX = initialShot.width / semantic.designW;
  const scaleY = initialShot.height / semantic.designH;
  console.log(`截图 ${initialShot.width}x${initialShot.height}，坐标缩放 ${scaleX.toFixed(4)}x${scaleY.toFixed(4)}`);

  const bounds = waitForBounds(scaleX, scaleY, observableElements.length);
  // 标签出现后重新截取最终画面，避免使用启动过程中的旧帧。
  execSync(`${ADB} exec-out screencap -p > "${SHOT}"`, { shell: true });
  const shot = resizeRGB(composite(load(SHOT)), semantic.designW, semantic.designH);
  const design = composite(load(DESIGN_PNG));
  const reference = evaluateReferenceDimensions(design, semantic.designW, semantic.designH);

  const pixel = compareFullPage(shot, design);
  const structure = evaluateStructure(observableElements, bounds, {
    toleranceXY: TOL_XY,
    toleranceWH: TOL_WH,
    toleranceTextWH: TOL_TEXT_WH,
    viewportWidth: semantic.designW,
    viewportHeight: semantic.designH,
  });

  const candidates = selectSpotCandidates(
    observableElements,
    SPOT_COUNT,
    semantic.designW,
    semantic.designH,
  );
  const spotChecks = candidates.map((element) => {
    const rect = element.rect;
    const x = Math.max(0, rect.x);
    const y = Math.max(0, rect.y);
    const w = Math.min(rect.w, shot.width - x, design.width - x);
    const h = Math.min(rect.h, shot.height - y, design.height - y);
    if (w < 8 || h < 8) {
      return { domIndex: element.domIndex, role: element.role, skipped: true, passed: true };
    }
    const actual = crop(shot, x, y, w, h, 48, 48);
    const expected = crop(design, x, y, w, h, 48, 48);
    const distance = regionAvgDist(actual, expected);
    return {
      domIndex: element.domIndex,
      role: element.role,
      rect: { x, y, w, h },
      dist: Number(distance.toFixed(4)),
      passed: distance <= SPOT_DIST,
    };
  });
  const spotPassed = spotChecks.filter((check) => check.passed).length;
  const spotPassRate = spotChecks.length ? spotPassed / spotChecks.length : 0;

  const report = {
    activity,
    comparedAt: new Date().toISOString(),
    designPx: `${semantic.designW}x${semantic.designH}`,
    reference,
    pixel: {
      similarity: Number(pixel.similarity.toFixed(6)),
      threshold: PIXEL_PASS,
      passed: pixel.similarity >= PIXEL_PASS,
      diffPixelRatio: pixel.diffPixelRatio,
      hotspots: pixel.hotspots.map((item) =>
        `(col=${item.col},row=${item.row}) diffPx=${item.diffPx} ratio=${(item.diffRatio * 100).toFixed(1)}%`),
      diffRegions: pixel.diffRegions.map((item) =>
        `x=${item.x} y=${item.y} w=${item.w} h=${item.h} diffPx=${item.diffPx}`),
    },
    generation: {
      sourceElementCount: generation.sourceElementCount,
      observableElementCount: generation.observableElementCount,
      occluded: generation.occluded,
    },
    structure: {
      ...structure,
      passRate: Number(structure.passRate.toFixed(4)),
      threshold: STRUCT_PASS,
    },
    spot: {
      total: spotChecks.length,
      passed: spotPassed,
      passRate: Number(spotPassRate.toFixed(4)),
      threshold: SPOT_PASS,
      checks: spotChecks,
    },
  };
  report.verdict = shouldAcceptReport(report, {
    pixelPass: PIXEL_PASS,
    structurePass: STRUCT_PASS,
    spotPass: SPOT_PASS,
  }) ? 'PASS(整页相似度、结构边界和局部抽查均通过)' : 'FAIL(页面尚未达到验收标准)';

  const outputDir = path.join(WORK_DIR, `compose-run-${timestamp()}`);
  fs.mkdirSync(outputDir, { recursive: true });
  fs.writeFileSync(path.join(outputDir, 'compose-report.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(INPUT_DIR, 'compose-structure-report.json'), JSON.stringify(report, null, 2));
  fs.copyFileSync(SHOT, path.join(outputDir, 'compose-shot.png'));
  fs.copyFileSync(DESIGN_PNG, path.join(outputDir, 'design.png'));
  writeDiffImage(shot, design, path.join(outputDir, 'compose-diff.png'));

  console.log(JSON.stringify({
    verdict: report.verdict,
    pixelSimilarity: report.pixel.similarity,
    structurePassRate: report.structure.passRate,
    spotPassRate: report.spot.passRate,
    missingElements: report.structure.missing,
    topDiffRegions: report.pixel.diffRegions.slice(0, 5),
  }, null, 2));
  console.log(`验证报告：${path.join(outputDir, 'compose-report.json')}`);
  console.log(`差异图：${path.join(outputDir, 'compose-diff.png')}`);

  if (report.verdict.startsWith('FAIL')) {
    process.exitCode = 1;
  }
}

main();
