/**
 * HTML 语义树采集器。
 * 1. 用系统 Chrome 加载 DESIGN_DIR 下的 index.html，遍历 DOM 计算每个视觉元素的精确几何与样式
 * 2. 截取原始 HTML 作为视觉真源
 * 3. 导出语义树 JSON（供 Compose 生成器直接分析布局）
 * 依赖环境变量 DESIGN_DIR：直接包含 index.html 的设计源目录。
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { CHROME_BIN, DESIGN_DIR, TOOL_OUTPUT_DIR, requiredSetting } = require('./config');
const { detectDesignSize, requireSupportedDesignSize } = require('./design-size');

const CHROME = CHROME_BIN;
const BASE = requiredSetting('DESIGN_DIR', DESIGN_DIR);
const SRC_HTML = (() => {
  const cands = fs.readdirSync(BASE);
  const hit = cands.find(f => /^\.?code-lanhu-index\.html$/.test(f) || f === 'index.html');
  return path.join(BASE, hit || 'index.html');
})();
const OUT_DIR = TOOL_OUTPUT_DIR;

// 固定横屏基准；不读取 DESIGN_WIDTH、DESIGN_HEIGHT，也不允许静默套用其他尺寸。
const {
  w: VIEW_W,
  h: VIEW_H,
  source: DESIGN_SIZE_SOURCE,
} = requireSupportedDesignSize(detectDesignSize(BASE));
console.log(`设计稿尺寸：${VIEW_W}x${VIEW_H}（${DESIGN_SIZE_SOURCE}）`);

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--force-device-scale-factor=1', '--hide-scrollbars', '--disable-lcd-text'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: VIEW_W, height: VIEW_H, deviceScaleFactor: 1 });
  await page.goto('file://' + SRC_HTML, { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  // 重置 body 默认样式，确保坐标原点从 (0,0) 开始（浏览器默认 body margin=8px 会导致整体偏移）
  await page.evaluate(() => {
    document.body.style.margin = '0px';
    document.body.style.padding = '0px';
  });

  const elements = await page.$$eval('body *', (els) => {
      const out = [];
      let domIndex = 0;
      for (const el of els) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
        const r = el.getBoundingClientRect();
        if (r.width < 0.5 && r.height < 0.5) continue;

        // 检测祖先 overflow:hidden 的裁剪：元素矩形与所有裁剪祖先矩形取交集，若完全在裁剪范围外则跳过
        let visRect = { x: r.x, y: r.y, w: r.width, h: r.height };
        let p = el.parentElement;
        while (p && p.tagName !== 'BODY') {
          const pcs = getComputedStyle(p);
          const ov = pcs.overflow;
          if (ov === 'hidden' || ov === 'scroll' || ov === 'auto' || ov === 'clip') {
            const pr = p.getBoundingClientRect();
            const ix = Math.max(visRect.x, pr.x);
            const iy = Math.max(visRect.y, pr.y);
            const ix2 = Math.min(visRect.x + visRect.w, pr.x + pr.width);
            const iy2 = Math.min(visRect.y + visRect.h, pr.y + pr.height);
            visRect = { x: ix, y: iy, w: Math.max(0, ix2 - ix), h: Math.max(0, iy2 - iy) };
            if (visRect.w <= 0 || visRect.h <= 0) break;
          }
          p = p.parentElement;
        }
        if (visRect.w <= 0 || visRect.h <= 0) continue; // 完全被祖先裁剪，视觉上不可见
        const bgColor = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' ? cs.backgroundColor : null;
        const bgImage = cs.backgroundImage && cs.backgroundImage !== 'none' ? cs.backgroundImage : null;
        const borderW = parseFloat(cs.borderTopWidth || '0');
        const hasBorder = borderW > 0 && cs.borderTopStyle !== 'none';
        const isImg = el.tagName === 'IMG';
        const directText = (() => {
          const nodes = Array.from(el.childNodes);
          return nodes.some(n => n.nodeType === 3 && (n.textContent || '').trim().length > 0);
        })();
        const text = directText ? (el.innerText || '').trim() : null;
        const visible = bgColor || bgImage || hasBorder || isImg || directText;
        if (!visible) continue;

        let role = 'container';
        if (isImg) role = 'image';
        else if (directText && !bgColor && !bgImage && !hasBorder) role = 'text';
        else if (bgImage && !directText) role = 'bg-image';
        else if (bgImage && directText) role = 'card-bg';
        else if (bgColor && !directText) role = 'box';
        else role = 'box-text';

        const imgSrc = isImg ? (el.getAttribute('src') || '') : null;
        out.push({
          domIndex: domIndex++,
          tag: el.tagName.toLowerCase(),
          className: typeof el.className === 'string' ? el.className : '',
          role,
          rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
          imgSrc,
          text,
          z: (() => {
            if (directText) return 100000 + domIndex;
            if (isImg) return 90000 + domIndex; // 图片是实际内容，覆盖背景色块
            return domIndex;
          })(),
          style: {
            opacity: cs.opacity !== '1' ? cs.opacity : null,
            bgColor,
            bgImage,
            bgSize: bgImage ? cs.backgroundSize : null,
            bgPosition: bgImage ? cs.backgroundPosition : null,
            borderRadius: cs.borderRadius && cs.borderRadius !== '0px' ? cs.borderRadius : null,
            border: hasBorder ? `${cs.borderTopWidth} ${cs.borderTopStyle} ${cs.borderTopColor}` : null,
            boxShadow: cs.boxShadow && cs.boxShadow !== 'none' ? cs.boxShadow : null,
            color: directText ? cs.color : null,
            fontSize: directText ? cs.fontSize : null,
            fontWeight: directText && cs.fontWeight !== '400' ? cs.fontWeight : null,
            fontFamily: directText ? cs.fontFamily : null,
            lineHeight: directText ? cs.lineHeight : null,
            textAlign: directText && cs.textAlign !== 'start' ? cs.textAlign : null,
            whiteSpace: directText && cs.whiteSpace !== 'normal' ? cs.whiteSpace : null,
            textDecoration: directText && cs.textDecorationLine && cs.textDecorationLine !== 'none' ? cs.textDecorationLine : null,
          },
        });
      }
      return out;
    });

  // 写语义树 JSON（Compose 生成器输入）
  fs.writeFileSync(path.join(OUT_DIR, 'semantic.json'), JSON.stringify({ designW: VIEW_W, designH: VIEW_H, count: elements.length, elements }, null, 2));

  // 原始 HTML 截图是最终视觉真源，只截取一次。
  await page.screenshot({ path: path.join(OUT_DIR, 'original.png') });

  await browser.close();
  console.log('elements:', elements.length);
  console.log('semantic.json:', path.join(OUT_DIR, 'semantic.json'));
  console.log('original.png:', path.join(OUT_DIR, 'original.png'));
}

main().catch((err) => { console.error(err); process.exit(1); });
