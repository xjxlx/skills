/**
 * 最小原型：像素对比
 * 用 pngjs 解码两张截图，合成到白底后逐像素计算相似度，输出报告。
 * 相似度 = 1 - 平均归一化色差；同时统计差异像素占比。
 * 每次运行都会生成独立对比图片（diff-visual.png）与报告，
 * 产物输出到项目根目录的 .code-html-compose/run-<时间戳>/ 下，方便观察。
 */
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');
const { packageNormalizedHtml } = require('./html-artifact-core');
const { DESIGN_DIR, TOOL_OUTPUT_DIR, WORK_DIR, requiredSetting } = require('./config');

// 输入截图位于目标项目工作目录（normalize.js 产出）
const INPUT_DIR = TOOL_OUTPUT_DIR;
const A = path.join(INPUT_DIR, 'original.png');
const B = path.join(INPUT_DIR, 'normalized.png');

// 规范化生成的 new.html（normalize.js 实际输出名为 normalized.html，落于 DESIGN_DIR）
const SOURCE_DIR = requiredSetting('DESIGN_DIR', DESIGN_DIR);
const NEW_HTML = path.join(SOURCE_DIR, 'normalized.html');

// 输出到目标项目的 .code-html-compose/run-<时间戳>/
const OUT_DIR = path.join(WORK_DIR, `run-${timestamp()}`);

function load(p) {
  return PNG.sync.read(fs.readFileSync(p));
}

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
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

function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  // 把两张输入截图一并拷入本次 run 目录，方便直接查看对比
  for (const [src, name] of [[A, 'original.png'], [B, 'normalized.png']]) {
    fs.copyFileSync(src, path.join(OUT_DIR, name));
  }
  // new.html 中的 <img src="./img/..."> 依赖设计源图片目录；归档时必须作为一个完整包复制。
  const packaged = packageNormalizedHtml({
    normalizedHtml: NEW_HTML,
    designDir: SOURCE_DIR,
    outputDir: OUT_DIR,
  });
  const a = composite(load(A));
  const b = composite(load(B));
  const w = Math.min(a.width, b.width);
  const h = Math.min(a.height, b.height);

  let totalDiff = 0;
  let diffPixels = 0;
  const THRESHOLD = 40; // 归一化色差阈值，超过视为差异像素
  const n = w * h;

  // 网格差异分布（10x5 网格，定位差异集中区域）
  const GRID_COLS = 10, GRID_ROWS = 5;
  const grid = Array.from({ length: GRID_COLS * GRID_ROWS }, () => 0);
  const gridPixels = Array.from({ length: GRID_COLS * GRID_ROWS }, () => 0);

  for (let i = 0; i < n; i++) {
    const dr = a.data[i * 3] - b.data[i * 3];
    const dg = a.data[i * 3 + 1] - b.data[i * 3 + 1];
    const db = a.data[i * 3 + 2] - b.data[i * 3 + 2];
    const dist = Math.sqrt(dr * dr + dg * dg + db * db) / Math.sqrt(255 * 255 * 3);
    totalDiff += dist;
    const px = Math.floor((i % w) / w * GRID_COLS);
    const py = Math.floor(Math.floor(i / w) / h * GRID_ROWS);
    const gi = py * GRID_COLS + px;
    gridPixels[gi]++;
    if (dist * Math.sqrt(3) > THRESHOLD / 255) { diffPixels++; grid[gi]++; }
  }

  const similarity = 1 - totalDiff / n;
  const diffRatio = diffPixels / n;

  // 网格中差异像素占比最高的几个区域
  const hotspots = [];
  for (let gi = 0; gi < grid.length; gi++) {
    const ratio = grid[gi] / gridPixels[gi];
    hotspots.push({ col: gi % GRID_COLS, row: Math.floor(gi / GRID_COLS), diffRatio: ratio, diffPx: grid[gi] });
  }
  hotspots.sort((x, y) => y.diffRatio - x.diffRatio);

  // 生成差异可视化图：左=原始，中=new.html，右=差异高亮（白底+红点）
  const diffCanvas = new PNG({ width: w * 3, height: h });
  for (let i = 0; i < n; i++) {
    const ax = i % w, ay = Math.floor(i / w);
    const ar = a.data[i * 3], ag = a.data[i * 3 + 1], ab = a.data[i * 3 + 2];
    const br = b.data[i * 3], bg = b.data[i * 3 + 1], bb = b.data[i * 3 + 2];
    const d = Math.sqrt((ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2);
    const isDiff = d > THRESHOLD;
    // 左：原始
    writePx(diffCanvas, ax, ay, ar, ag, ab);
    // 中：new.html
    writePx(diffCanvas, w + ax, ay, br, bg, bb);
    // 右：差异，白底+红点
    writePx(diffCanvas, 2 * w + ax, ay, isDiff ? 255 : 255, isDiff ? 0 : 255, isDiff ? 0 : 255);
  }
  fs.writeFileSync(path.join(OUT_DIR, 'diff-visual.png'), PNG.sync.write(diffCanvas));

  const report = {
    a: path.basename(A),
    b: path.basename(B),
    size: `${a.width}x${a.height} vs ${b.width}x${b.height}`,
    compared: `${w}x${h}`,
    pixelSimilarity: similarity,
    diffPixelRatio: diffRatio,
    verdict: similarity >= 0.98 ? 'PASS(高还原)' : similarity >= 0.9 ? 'WARN(基本还原，有局部偏差)' : 'FAIL(结构/样式偏差较大)',
    hotspots: hotspots.slice(0, 5).map(h => `(${h.col},${h.row}) diff=${(h.diffRatio * 100).toFixed(1)}%`),
  };

  // 报告写入 run 目录（归档），同时写一份到输入 out/ 目录（供迭代脚本读取最新结果）
  fs.writeFileSync(path.join(OUT_DIR, 'compare-report.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(INPUT_DIR, 'compare-report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  console.log(`\n对比产物目录：${OUT_DIR}`);
  console.log(`  new.html  规范化生成的 HTML`);
  if (packaged.copiedImageDirectory) console.log(`  img/  new.html 相对路径图片资源`);
  console.log(`  diff-visual.png  对比图片（左=原始 中=new.html 右=差异高亮）`);
  console.log(`  compare-report.json  对比报告`);
}

main();
