/**
 * code-html-compose 步骤 10：Compose 视图 vs 设计稿 像素对比（模拟器截图）。
 *
 * 流程：
 *   1. 用 adb 启动目标 Activity（默认 ReportHomeV3Activity，承载 Test1Page）
 *   2. 等待渲染完成后 adb 截图（横屏，无状态栏/导航栏）
 *   3. 把截图双线性缩放到设计稿尺寸（默认 1334x750，与 normalized.png 对齐）
 *   4. 复用 compare.js 的像素对比逻辑，逐像素计算相似度
 *   5. 生成 diff 图（左=设计稿 中=Compose 右=差异高亮）与报告，输出到 run-<时间戳>/
 *
 * 前置：
 *   - AVD 名称 375，adb 序列 emulator-5554（物理 1334x750 @320dpi，与设计稿 @2x 完全一致）
 *   - 模拟器已横屏（adb shell settings put system user_rotation 1）
 *   - app 已安装并编译
 *
 * 用法：node compose-shoot.js [activityComponent]
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { PNG } = require('pngjs');
const {
  ADB,
  COMPOSE_ACTIVITY,
  TOOL_OUTPUT_DIR,
  WORK_DIR,
  requiredSetting,
} = require('./config');

const INPUT_DIR = TOOL_OUTPUT_DIR;
const DESIGN_PNG = path.join(INPUT_DIR, 'normalized.png'); // 设计稿截图（new.html）
const SHOT = path.join(INPUT_DIR, 'compose-shot.png'); // Compose 截图
const ACTIVITY = process.argv[2] || requiredSetting('COMPOSE_ACTIVITY', COMPOSE_ACTIVITY);

// 设计稿尺寸（Compose 截图缩放对齐到该尺寸再对比）
const DESIGN_W = 1334;
const DESIGN_H = 750;

// Compose 阶段 PASS 阈值（跨渲染器对比，默认 0.95，可用 COMPOSE_PASS 覆盖）。
// 与 HTML 阶段（同渲染器 99.95%）不同：Chrome 设计稿 vs 模拟器截图带字体/抗锯齿/密度噪声。
const PASS = parseFloat(process.env.COMPOSE_PASS || '0.95');

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function load(p) {
  return PNG.sync.read(fs.readFileSync(p));
}

// 双线性缩放（缩放到设计稿尺寸）
function resize(img, tw, th) {
  const { width, height, data } = img;
  const out = new PNG({ width: tw, height: th });
  const sx = width / tw;
  const sy = height / th;
  for (let y = 0; y < th; y++) {
    for (let x = 0; x < tw; x++) {
      const gx = x * sx;
      const gy = y * sy;
      const x0 = Math.floor(gx), y0 = Math.floor(gy);
      const x1 = Math.min(x0 + 1, width - 1), y1 = Math.min(y0 + 1, height - 1);
      const fx = gx - x0, fy = gy - y0;
      const oi = (y * tw + x) * 4;
      for (let c = 0; c < 4; c++) {
        const v00 = data[(y0 * width + x0) * 4 + c];
        const v10 = data[(y0 * width + x1) * 4 + c];
        const v01 = data[(y1 * width + x0) * 4 + c];
        const v11 = data[(y1 * width + x1) * 4 + c];
        const top = v00 + (v10 - v00) * fx;
        const bot = v01 + (v11 - v01) * fx;
        out.data[oi + c] = Math.round(top + (bot - top) * fy);
      }
    }
  }
  return out;
}

// 顺时针旋转 90°（用于把竖屏截图转成横屏，与设计稿方向对齐）
function rotate90(img) {
  const { width, height, data } = img;
  const out = new PNG({ width: height, height: width });
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const si = (y * width + x) * 4;
      const di = (x * out.width + (out.height - 1 - y)) * 4;
      out.data[di] = data[si];
      out.data[di + 1] = data[si + 1];
      out.data[di + 2] = data[si + 2];
      out.data[di + 3] = data[si + 3];
    }
  }
  return out;
}

// 带 alpha 合成到白底
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

function writePx(img, x, y, r, g, b) {
  const i = (y * img.width + x) * 4;
  img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255;
}

function screencap() {
  fs.mkdirSync(INPUT_DIR, { recursive: true });
  execSync(`${ADB} exec-out screencap -p > "${SHOT}"`, { shell: true });
  console.log(`  截图完成 → ${SHOT}`);
}

function main() {
  const OUT_DIR = path.join(WORK_DIR, `compose-run-${timestamp()}`);
  fs.mkdirSync(OUT_DIR, { recursive: true });

  console.log(`步骤 10.1：启动 Activity ${ACTIVITY}`);
  // 恢复自然分辨率（清除 1334x750 的 override，避免横屏被错误按竖屏渲染导致缩放错乱）
  execSync(`${ADB} shell wm size reset`, { shell: true });
  // 375 模拟器为原生横屏（1334x750），旋转 0 即横屏，与设计稿方向一致。
  // 注意：不能设 user_rotation=1（会把原生横屏设备转成竖屏 750x1334，导致布局压缩变形）。
  execSync(`${ADB} shell settings put system accelerometer_rotation 0`, { shell: true });
  execSync(`${ADB} shell settings put system user_rotation 0`, { shell: true });
  // 沉浸全屏：隐藏系统状态栏/导航栏，保证截图 = 纯内容区域（避免系统 UI 挤入导致整体偏移）
  execSync(`${ADB} shell settings put global policy_control immersive.full=*`, { shell: true });
  // 强制重启 Activity，确保以横屏重新渲染
  execSync(`${ADB} shell am force-stop ${
    ACTIVITY.split('/')[0]
  }`, { shell: true });
  execSync(`${ADB} shell am start -n ${ACTIVITY}`, { shell: true });
  // 等待渲染完成（首帧布局 + 图片加载）
  execSync(`sleep 6`, { shell: true });

  console.log('步骤 10.2：截取 Compose 渲染画面');
  screencap();

  if (!fs.existsSync(DESIGN_PNG)) {
    console.error(`设计稿截图不存在：${DESIGN_PNG}`);
    process.exit(1);
  }

  // 方向校正：设计稿为横屏，若截图是竖屏则旋转成横屏，避免变形
  let shotImg = load(SHOT);
  if (shotImg.width > shotImg.height) {
    console.log(`  截图横屏 ${shotImg.width}x${shotImg.height}，方向正确`);
  } else {
    console.log(`  截图竖屏 ${shotImg.width}x${shotImg.height}，旋转 90° 校正为横屏`);
    shotImg = rotate90(shotImg);
  }
  // 保存校正后的横屏截图，便于人工核对
  fs.writeFileSync(path.join(INPUT_DIR, 'compose-shot-landscape.png'), PNG.sync.write(shotImg));

  const shot = composite(resize(shotImg, DESIGN_W, DESIGN_H));
  const design = composite(load(DESIGN_PNG));
  const w = DESIGN_W, h = DESIGN_H;
  const n = w * h;

  let totalDiff = 0, diffPixels = 0;
  const THRESHOLD = 40;
  const GRID_COLS = 10, GRID_ROWS = 5;
  const grid = Array.from({ length: GRID_COLS * GRID_ROWS }, () => 0);
  const gridPixels = Array.from({ length: GRID_COLS * GRID_ROWS }, () => 0);
  const mask = new Uint8Array(n); // 差异像素掩码（供连通域聚类）

  for (let i = 0; i < n; i++) {
    const dr = shot.data[i * 3] - design.data[i * 3];
    const dg = shot.data[i * 3 + 1] - design.data[i * 3 + 1];
    const db = shot.data[i * 3 + 2] - design.data[i * 3 + 2];
    const dist = Math.sqrt(dr * dr + dg * dg + db * db) / Math.sqrt(255 * 255 * 3);
    totalDiff += dist;
    const px = Math.floor((i % w) / w * GRID_COLS);
    const py = Math.floor(Math.floor(i / w) / h * GRID_ROWS);
    const gi = py * GRID_COLS + px;
    gridPixels[gi]++;
    if (dist * Math.sqrt(3) > THRESHOLD / 255) { diffPixels++; grid[gi]++; mask[i] = 1; }
  }

  const similarity = 1 - totalDiff / n;
  const diffRatio = diffPixels / n;

  // 差异连通域聚类（4 邻域 BFS），输出最大差异区域 bbox，精确定位差异元素
  const regions = [];
  const visited = new Uint8Array(n);
  const stack = [];
  for (let i = 0; i < n; i++) {
    if (!mask[i] || visited[i]) continue;
    let minX = w, minY = h, maxX = 0, maxY = 0, cnt = 0;
    stack.push(i); visited[i] = 1;
    while (stack.length) {
      const c = stack.pop();
      const cx = c % w, cy = Math.floor(c / w);
      cnt++; if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;
      if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;
      const nbs = [c - 1, c + 1, c - w, c + w];
      for (const nb of nbs) {
        if (nb < 0 || nb >= n) continue;
        const nbx = nb % w, nby = Math.floor(nb / w);
        if (Math.abs(nbx - cx) + Math.abs(nby - cy) !== 1) continue;
        if (mask[nb] && !visited[nb]) { visited[nb] = 1; stack.push(nb); }
      }
    }
    regions.push({ x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1, diffPx: cnt });
  }
  regions.sort((a, b) => b.diffPx - a.diffPx);

  const hotspots = [];
  for (let gi = 0; gi < grid.length; gi++) {
    hotspots.push({ col: gi % GRID_COLS, row: Math.floor(gi / GRID_COLS), diffRatio: grid[gi] / gridPixels[gi], diffPx: grid[gi] });
  }
  hotspots.sort((x, y) => y.diffRatio - x.diffRatio);

  // diff 图：左=设计稿 中=Compose 右=差异高亮
  const diffCanvas = new PNG({ width: w * 3, height: h });
  for (let i = 0; i < n; i++) {
    const ax = i % w, ay = Math.floor(i / w);
    const ar = design.data[i * 3], ag = design.data[i * 3 + 1], ab = design.data[i * 3 + 2];
    const sr = shot.data[i * 3], sg = shot.data[i * 3 + 1], sb = shot.data[i * 3 + 2];
    const d = Math.sqrt((ar - sr) ** 2 + (ag - sg) ** 2 + (ab - sb) ** 2);
    const isDiff = d > THRESHOLD;
    writePx(diffCanvas, ax, ay, ar, ag, ab);
    writePx(diffCanvas, w + ax, ay, sr, sg, sb);
    writePx(diffCanvas, 2 * w + ax, ay, isDiff ? 255 : 255, isDiff ? 0 : 255, isDiff ? 0 : 255);
  }
  fs.writeFileSync(path.join(OUT_DIR, 'compose-diff.png'), PNG.sync.write(diffCanvas));
  fs.writeFileSync(path.join(OUT_DIR, 'compose-shot.png'), fs.readFileSync(SHOT));
  fs.copyFileSync(DESIGN_PNG, path.join(OUT_DIR, 'design.png'));

  const report = {
    activity: ACTIVITY,
    design: path.basename(DESIGN_PNG),
    compared: `${w}x${h}`,
    pixelSimilarity: similarity,
    diffPixelRatio: diffRatio,
    verdict: similarity >= PASS ? 'PASS(高还原·跨渲染器)' : similarity >= 0.9 ? 'WARN(基本还原，有局部偏差)' : 'FAIL(结构/样式偏差较大)',
    hotspots: hotspots.slice(0, 8).map(h => `(col=${h.col},row=${h.row}) diffPx=${h.diffPx} ratio=${(h.diffRatio * 100).toFixed(1)}%`),
    diffRegions: regions.slice(0, 12).map(r => `x=${r.x} y=${r.y} w=${r.w} h=${r.h} diffPx=${r.diffPx}`),
  };
  fs.writeFileSync(path.join(OUT_DIR, 'compose-report.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(INPUT_DIR, 'compose-report.json'), JSON.stringify(report, null, 2));

  console.log(JSON.stringify(report, null, 2));
  console.log(`\nCompose 对比产物目录：${OUT_DIR}`);
  console.log(`  compose-diff.png   对比图（左=设计稿 中=Compose 右=差异高亮）`);
  console.log(`  compose-shot.png   Compose 原始截图`);
  console.log(`  compose-report.json   对比报告`);
}

main();
