/**
 * code-html-compose 步骤 10（方案 A）：Compose 结构校验 + 局部抽查。
 *
 * 验收从「整页像素相似度」改为两层校验：
 *   1. 元素边界校验：launch 后 uiautomator dump 解析各 testTag("e<domIndex>") 的实际 bounds，
 *      与语义树 rect（设计稿 px）做容差比对，逐元素判定位置/尺寸是否正确 → 结构正确率。
 *   2. 局部抽查：对文本和关键元素区域，裁剪原始 HTML 截图(original.png)与 Compose 截图做像素对比，
 *      用平均色差判定该区块是否渲染正确（容忍跨渲染器噪声）。
 *
 * 前置：目标模拟器已启动；脚本会按当前 semantic.json 和 DP_PER_PX 设置验收窗口与密度。
 * 用法：node compose-validate.js [activityComponent]
 * 输出：tools/out/compose-structure-report.json + .code-html-compose/compose-run-<ts>/ 对比图
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { PNG } = require('pngjs');
const {
  evaluateReferenceDimensions,
  evaluateReferenceImage,
  evaluateStructure,
  selectSpotCandidates,
  shouldAcceptReport,
} = require('./compose-validation-core');
const {
  ADB,
  COMPOSE_ACTIVITY,
  PROJECT_ROOT,
  TOOL_OUTPUT_DIR,
  WORK_DIR,
  requiredSetting,
} = require('./config');
const { ensureLauncherActivity } = require('./launcher-activity');

// 设计稿倍率：默认 @2x（DP_PER_PX=0.5，semantic css px 为物理像素），@1x 设计稿（如 812，css px 即 dp 值）传 DP_PER_PX=1。
// 与 html-to-compose.js 保持一致，经环境变量 DP_PER_PX 传递。
const DP_PER_PX = parseFloat(process.env.DP_PER_PX || '0.5');
// 模拟器 density 固定 320（@2x），uiautomator/screencap 返回物理 px。
// 物理 px = semantic css px × PX_SCALE，其中 PX_SCALE = DP_PER_PX × (320 / 160) = DP_PER_PX × 2：
//   @2x（DP_PER_PX=0.5）→ PX_SCALE=1，物理 == semantic，零缩放（兼容既有 @2x 流程）；
//   @1x（DP_PER_PX=1.0）→ PX_SCALE=2，物理 = semantic × 2，验收前需把物理观测缩回 semantic 空间比较。
const PX_SCALE = DP_PER_PX * 2;
const INPUT_DIR = TOOL_OUTPUT_DIR;
const SEMANTIC = path.join(INPUT_DIR, 'semantic.json');
const GENERATION_REPORT = path.join(INPUT_DIR, 'compose-generation-report.json');
const DESIGN_PNG = path.join(INPUT_DIR, 'original.png'); // 原始 HTML 截图是最终视觉真源
const NORMALIZED_PNG = path.join(INPUT_DIR, 'normalized.png'); // 规范化 HTML 仅作为中间层健康检查
const SHOT = path.join(INPUT_DIR, 'compose-shot.png');
const UI_XML = path.join(INPUT_DIR, 'ui.xml');
const ACTIVITY = process.argv[2] || requiredSetting('COMPOSE_ACTIVITY', COMPOSE_ACTIVITY);

// 结构校验容差（px，物理=设计 px）。文本宽高都必须校验，防止 wrapContent 溢出遮挡相邻元素。
const TOL_XY = parseFloat(process.env.VALIDATE_TOL_XY || '4');
const TOL_WH = parseFloat(process.env.VALIDATE_TOL_WH || '4');
const TOL_TEXT_WH = parseFloat(process.env.VALIDATE_TOL_TEXT_WH || process.env.VALIDATE_TOL_TEXT_H || '6');
const REFERENCE_DIST = parseFloat(process.env.VALIDATE_REFERENCE_DIST || '0.02');

// 验收阈值
const STRUCT_PASS = parseFloat(process.env.VALIDATE_STRUCT_PASS || '0.95'); // 元素边界通过率
const SPOT_PASS = parseFloat(process.env.VALIDATE_SPOT_PASS || '0.8'); // 抽查通过率
const SPOT_COUNT = parseInt(process.env.VALIDATE_SPOT_COUNT || '8', 10); // 抽查元素数
// 区块平均色差阈值(归一化)：@2x 设计稿（DP_PER_PX=0.5）用 0.18；@1x 小字号设计稿（DP_PER_PX≥1）CJK 渲染噪声更大，默认放宽到 0.28。
// 可用 VALIDATE_SPOT_DIST 覆盖。
const SPOT_DIST = parseFloat(process.env.VALIDATE_SPOT_DIST || (DP_PER_PX >= 1 ? '0.28' : '0.18'));

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
    const r = data[i * 4], g = data[i * 4 + 1], b = data[i * 4 + 2], a = data[i * 4 + 3] / 255;
    out[i * 3] = Math.round(r * a + 255 * (1 - a));
    out[i * 3 + 1] = Math.round(g * a + 255 * (1 - a));
    out[i * 3 + 2] = Math.round(b * a + 255 * (1 - a));
  }
  return { width, height, data: out };
}

function rotate90(img) {
  const { width, height, data } = img;
  const out = new PNG({ width: height, height: width });
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const si = (y * width + x) * 4;
      const di = (x * out.width + (out.height - 1 - y)) * 4;
      for (let c = 0; c < 4; c++) out.data[di + c] = data[si + c];
    }
  }
  return out;
}

function launch(designW, designH) {
  // 物理分辨率始终从当前 semantic 尺寸推导，density 固定 320；禁止套用历史设计稿宽高。
  execSync(`${ADB} shell wm size ${Math.round(designW * PX_SCALE)}x${Math.round(designH * PX_SCALE)}`, { shell: true });
  execSync(`${ADB} shell wm density 320`, { shell: true });
  execSync(`${ADB} shell settings put system accelerometer_rotation 0`, { shell: true });
  execSync(`${ADB} shell settings put system user_rotation 0`, { shell: true });
  execSync(`${ADB} shell settings put global policy_control immersive.full=*`, { shell: true });
  execSync(`${ADB} shell am force-stop ${ACTIVITY.split('/')[0]}`, { shell: true });
  execSync(`${ADB} shell am start -n ${ACTIVITY}`, { shell: true });
  execSync(`sleep 6`, { shell: true });
}

function screencap() {
  fs.mkdirSync(INPUT_DIR, { recursive: true });
  execSync(`${ADB} exec-out screencap -p > "${SHOT}"`, { shell: true });
}

// uiautomator dump → { "<domIndex>": {x,y,w,h} }（testTag 映射为 resource-id），
// 单位统一缩回 semantic 空间（css px）：物理 px ÷ PX_SCALE，@1x 设计稿时 PX_SCALE=2。
function dumpBounds() {
  execSync(`${ADB} shell uiautomator dump /sdcard/ui.xml`, { shell: true });
  execSync(`${ADB} pull /sdcard/ui.xml "${UI_XML}"`, { shell: true });
  const xml = fs.readFileSync(UI_XML, 'utf8');
  const map = {};
  const re = /<node[^>]*resource-id="(e\d+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/g;
  let m;
  while ((m = re.exec(xml))) {
    map[m[1]] = {
      x: +m[2] / PX_SCALE,
      y: +m[3] / PX_SCALE,
      w: (+m[4] - +m[2]) / PX_SCALE,
      h: (+m[5] - +m[3]) / PX_SCALE,
    };
  }
  return map;
}

// 双线性缩放 composite 结果（RGB 3 通道）到 tw×th，用于把物理截图缩回 semantic 空间（@1x 时 ÷2）。
function resizeRGB(img, tw, th) {
  if (img.width === tw && img.height === th) return img;
  const sw = img.width, sh = img.height, data = img.data;
  const out = { width: tw, height: th, data: new Uint8ClampedArray(tw * th * 3) };
  const sx = sw / tw, sy = sh / th;
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

// 裁剪并最近邻缩放到 tw x th，返回 RGB 数组
function crop(img, x, y, w, h, tw, th) {
  const out = new Uint8ClampedArray(tw * th * 3);
  for (let j = 0; j < th; j++) {
    const sy = Math.min(y + Math.floor((j / th) * h), img.height - 1);
    for (let i = 0; i < tw; i++) {
      const sx = Math.min(x + Math.floor((i / tw) * w), img.width - 1);
      const si = (sy * img.width + sx) * 3;
      const di = (j * tw + i) * 3;
      out[di] = img.data[si]; out[di + 1] = img.data[si + 1]; out[di + 2] = img.data[si + 2];
    }
  }
  return out;
}

function regionAvgDist(a, b) {
  let sum = 0;
  const n = a.length / 3;
  for (let i = 0; i < n; i++) {
    const dr = a[i * 3] - b[i * 3];
    const dg = a[i * 3 + 1] - b[i * 3 + 1];
    const db = a[i * 3 + 2] - b[i * 3 + 2];
    sum += Math.sqrt(dr * dr + dg * dg + db * db) / Math.sqrt(255 * 255 * 3);
  }
  return sum / n;
}

function main() {
  try {
    ensureLauncherActivity(PROJECT_ROOT);
  } catch (error) {
    console.error(`\n${error.message}`);
    process.exit(1);
  }

  if (!fs.existsSync(SEMANTIC)) {
    console.error(`语义树不存在：${SEMANTIC}`);
    process.exit(1);
  }
  if (!fs.existsSync(DESIGN_PNG)) {
    console.error(`设计稿截图不存在：${DESIGN_PNG}（需先跑 normalize.js/compare.js）`);
    process.exit(1);
  }
  if (!fs.existsSync(NORMALIZED_PNG)) {
    console.error(`规范化 HTML 截图不存在：${NORMALIZED_PNG}（需先跑 normalize.js）`);
    process.exit(1);
  }
  const ROOT_OUT = path.join(WORK_DIR, `compose-run-${timestamp()}`);
  fs.mkdirSync(ROOT_OUT, { recursive: true });

  const semantic = JSON.parse(fs.readFileSync(SEMANTIC, 'utf8'));
  if (!fs.existsSync(GENERATION_REPORT)) {
    console.error(`Compose 生成报告不存在：${GENERATION_REPORT}（需先跑 html-to-compose.js）`);
    process.exit(1);
  }
  const generation = JSON.parse(fs.readFileSync(GENERATION_REPORT, 'utf8'));
  const observableIndices = new Set(generation.observableDomIndices || []);
  const observableElements = semantic.elements.filter((element) => observableIndices.has(element.domIndex));
  if (observableElements.length !== generation.observableElementCount) {
    console.error('Compose 生成报告与 semantic.json 不一致，请重新生成 Compose。');
    process.exit(1);
  }

  console.log('步骤 10.1：启动 Activity 并等待渲染');
  launch(semantic.designW, semantic.designH);

  console.log('步骤 10.2：截取 Compose 画面');
  screencap();

  console.log('步骤 10.3：uiautomator dump 提取元素边界');
  const bounds = dumpBounds();

  // 方向校正（横屏）
  let shotImg = load(SHOT);
  if (shotImg.width < shotImg.height) {
    console.log('  截图竖屏，旋转 90° 校正');
    shotImg = rotate90(shotImg);
  }
  let shot = composite(shotImg);
  // 物理截图缩回 semantic 空间（@1x 设计稿 PX_SCALE=2 时 ÷2），与 original.png 同尺寸对齐抽查。
  if (shot.width !== semantic.designW || shot.height !== semantic.designH) {
    shot = resizeRGB(shot, semantic.designW, semantic.designH);
  }
  const design = composite(load(DESIGN_PNG));
  const normalized = composite(load(NORMALIZED_PNG));

  // 原始 HTML 截图是 Compose 像素抽查真源；规范化 HTML 的差异单独报告，不能污染真源。
  const reference = evaluateReferenceDimensions(design, semantic.designW, semantic.designH);
  const intermediate = evaluateReferenceImage(normalized, design, REFERENCE_DIST);

  // ---- 1) 元素边界校验 ----
  const structure = evaluateStructure(observableElements, bounds, {
    toleranceXY: TOL_XY,
    toleranceWH: TOL_WH,
    toleranceTextWH: TOL_TEXT_WH,
    viewportWidth: semantic.designW,
    viewportHeight: semantic.designH,
  });

  // ---- 2) 局部抽查：按面积取前 K 个元素，裁剪区域做像素对比 ----
  const candidates = selectSpotCandidates(
    observableElements,
    SPOT_COUNT,
    semantic.designW,
    semantic.designH,
  );

  const spotChecks = candidates.map((e) => {
    const r = e.rect;
    const x = Math.max(0, r.x), y = Math.max(0, r.y);
    const w = Math.min(r.w, shot.width - x, design.width - x);
    const h = Math.min(r.h, shot.height - y, design.height - y);
    if (w < 8 || h < 8) return { domIndex: e.domIndex, role: e.role, skipped: true, passed: true };
    const a = crop(shot, x, y, w, h, 48, 48);
    const b = crop(design, x, y, w, h, 48, 48);
    const dist = regionAvgDist(a, b);
    const passed = dist <= SPOT_DIST;
    return { domIndex: e.domIndex, role: e.role, rect: { x, y, w, h }, dist: +dist.toFixed(4), passed };
  });
  const spotPass = spotChecks.filter((s) => s.passed).length;
  const spotPassRate = spotChecks.length ? spotPass / spotChecks.length : 0;

  const report = {
    activity: ACTIVITY,
    comparedAt: new Date().toISOString(),
    designPx: `${semantic.designW}x${semantic.designH}`,
    reference,
    intermediate,
    generation: {
      sourceElementCount: generation.sourceElementCount,
      generatedElementCount: generation.generatedElementCount,
      observableElementCount: generation.observableElementCount,
      occluded: generation.occluded,
    },
    structure: {
      ...structure,
      passRate: +structure.passRate.toFixed(4),
      threshold: STRUCT_PASS,
    },
    spot: {
      total: spotChecks.length,
      passed: spotPass,
      passRate: +spotPassRate.toFixed(4),
      threshold: SPOT_PASS,
      checks: spotChecks,
    },
  };
  const accepted = shouldAcceptReport(report, { structurePass: STRUCT_PASS, spotPass: SPOT_PASS });
  report.verdict = accepted ? 'PASS(基准有效·结构正确·抽查通过)' : 'FAIL(基准、结构或抽查有偏差)';

  fs.writeFileSync(path.join(ROOT_OUT, 'compose-structure-report.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(INPUT_DIR, 'compose-structure-report.json'), JSON.stringify(report, null, 2));
  fs.copyFileSync(SHOT, path.join(ROOT_OUT, 'compose-shot.png'));
  fs.copyFileSync(DESIGN_PNG, path.join(ROOT_OUT, 'design.png'));
  fs.copyFileSync(NORMALIZED_PNG, path.join(ROOT_OUT, 'normalized.png'));

  console.log(JSON.stringify({
    verdict: report.verdict,
    referenceValid: reference.valid,
    referenceDistance: reference.distance,
    structurePassRate: +structure.passRate.toFixed(4),
    spotPassRate: +spotPassRate.toFixed(4),
    structurePassed: structure.passed,
    structureTotal: structure.total,
    structureMissing: structure.missing,
    spotPassed: spotPass,
    spotTotal: spotChecks.length,
  }, null, 2));

  // 输出失败元素便于定位
  const failed = structure.checks.filter((c) => !c.passed);
  if (failed.length) {
    console.log(`\n边界未通过元素 ${failed.length} 个：`);
    for (const f of failed.slice(0, 20)) {
      console.log(`  e${f.domIndex} ${f.role} ${f.text || ''} → ${f.reason || `dx=${f.dx} dy=${f.dy} exp=${JSON.stringify(f.expected)} act=${JSON.stringify(f.actual)}`}`);
    }
  }

  console.log(`\n结构校验产物目录：${ROOT_OUT}`);
  console.log('  compose-structure-report.json   结构校验 + 抽查报告');
  console.log('  compose-shot.png   Compose 截图');
  console.log('  design.png   设计稿截图');
}

main();
