/**
 * 最小原型：HTML 规范化器（步骤 4-5）
 * 1. 用系统 Chrome 加载 DESIGN_DIR 下的 index.html，遍历 DOM 计算每个视觉元素的精确几何与样式
 * 2. 生成规范化 HTML（语义标注 + 绝对定位精确还原）
 * 3. 导出语义树 JSON（供 Compose 生成器作为输入）
 * 依赖环境变量 DESIGN_DIR：直接包含 index.html 的设计源目录。
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { CHROME_BIN, DESIGN_DIR, TOOL_OUTPUT_DIR, requiredSetting } = require('./config');

const CHROME = CHROME_BIN;
const BASE = requiredSetting('DESIGN_DIR', DESIGN_DIR);
const SRC_HTML = (() => {
  const cands = fs.readdirSync(BASE);
  const hit = cands.find(f => /^\.?code-lanhu-index\.html$/.test(f) || f === 'index.html');
  return path.join(BASE, hit || 'index.html');
})();
const NORMALIZED_HTML = path.join(BASE, 'normalized.html');
const OUT_DIR = TOOL_OUTPUT_DIR;

// 动态检测设计稿尺寸：优先解析 css 中 .page 块的 width/height（排除 rem/response 变体），
// 其次解析目录名 lanhu_WxH，最后回退 1334x750。避免硬编码视口与设计稿不匹配导致坐标偏移。
function detectDesignSize(dir) {
  const cssFiles = [];
  try {
    for (const f of fs.readdirSync(dir)) {
      if (f.endsWith('.css') && !/(\.rem|\.response)\.css$/.test(f)) cssFiles.push(f);
    }
  } catch (e) {}
  for (const f of cssFiles) {
    let css;
    try { css = fs.readFileSync(path.join(dir, f), 'utf8'); } catch (e) { continue; }
    const block = css.match(/\.page\s*\{[^}]*\}/);
    if (block) {
      const wm = block[0].match(/width:\s*([\d.]+)px/);
      const hm = block[0].match(/height:\s*([\d.]+)px/);
      if (wm && hm) return { w: Math.round(+wm[1]), h: Math.round(+hm[1]) };
    }
  }
  const dm = path.basename(dir).match(/(\d+)x(\d+)/);
  if (dm) return { w: +dm[1], h: +dm[2] };
  return { w: 1334, h: 750 };
}
const { w: VIEW_W, h: VIEW_H } = detectDesignSize(BASE);
console.log(`设计稿尺寸：${VIEW_W}x${VIEW_H}`);

// z-index 策略：默认 DOM 顺序（文本最高层）。可选 'legacy' 恢复“背景图整体抬升”的旧策略。
const Z_STRATEGY = process.env.Z_STRATEGY || 'dom';

// 是否有直接文本子节点（过滤掉纯 <br>）
function hasDirectText(el) {
  const nodes = Array.from(el.childNodes);
  return nodes.some(n => n.nodeType === 3 && (n.textContent || '').trim().length > 0);
}

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

  const elements = await page.$$eval('body *', (els, _zStrategy) => {
      const Z_STRATEGY_LOCAL = _zStrategy;
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
            if (Z_STRATEGY_LOCAL === 'legacy') return (bgImage ? 50000 + domIndex : domIndex);
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
    },
    Z_STRATEGY
  );

  // 写语义树 JSON（Compose 生成器输入）
  fs.writeFileSync(path.join(OUT_DIR, 'semantic.json'), JSON.stringify({ designW: VIEW_W, designH: VIEW_H, count: elements.length, elements }, null, 2));

  // 生成规范化 HTML
  const html = buildNormalizedHtml(elements);
  fs.writeFileSync(NORMALIZED_HTML, html);

  // 截图：原始 vs 规范化
  await screenshot(page, SRC_HTML, path.join(OUT_DIR, 'original.png'));
  await screenshot(page, NORMALIZED_HTML, path.join(OUT_DIR, 'normalized.png'));

  await browser.close();
  console.log('elements:', elements.length);
  console.log('normalized:', NORMALIZED_HTML);
  console.log('semantic.json:', path.join(OUT_DIR, 'semantic.json'));
  console.log('screenshots:', path.join(OUT_DIR, 'original.png'), path.join(OUT_DIR, 'normalized.png'));
}

function screenshot(page, file, dest) {
  return new Promise(async (resolve) => {
    await page.evaluate(() => location.reload()); // 触发 reload 到新 url
    await page.goto('file://' + file, { waitUntil: 'networkidle0' });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: dest });
    resolve();
  });
}

function buildNormalizedHtml(elements) {
  const parts = [];
  for (const e of elements) {
    const s = e.style;
    const st = [`position:absolute`, `left:${e.rect.x}px`, `top:${e.rect.y}px`, `width:${e.rect.w}px`, `height:${e.rect.h}px`, `z-index:${e.z}`];
    if (s.opacity) st.push(`opacity:${s.opacity}`);
    if (s.bgColor) st.push(`background-color:${s.bgColor}`);
    if (s.bgImage) st.push(`background-image:${s.bgImage}`, `background-size:${s.bgSize || '100% 100%'}`, `background-repeat:no-repeat`, `background-position:${s.bgPosition || '0% 0%'}`);
    if (s.borderRadius) st.push(`border-radius:${s.borderRadius}`);
    if (s.border) st.push(`border:${s.border}`);
    if (s.boxShadow) st.push(`box-shadow:${s.boxShadow}`);
    if (e.role === 'image' && e.imgSrc) {
      parts.push(`<img data-vi="${e.role}" style="${escapeAttr(st.join(';'))}" src="${escapeAttr(e.imgSrc)}"/>`);
    } else if (e.text) {
      const t = [`color:${s.color || '#000'}`, `font-size:${s.fontSize || '14px'}`, `line-height:${s.lineHeight || 'normal'}`];
      if (s.fontFamily) t.push(`font-family:${s.fontFamily}`);
      if (s.fontWeight) t.push(`font-weight:${s.fontWeight}`);
      if (s.textAlign) t.push(`text-align:${s.textAlign}`);
      if (s.whiteSpace) t.push(`white-space:${s.whiteSpace}`);
      else t.push('white-space:pre-line');
      // 用 flex 让文字在容器内垂直居中，还原 flex 布局下字形的实际位置
      const justify = s.textAlign === 'right' ? 'flex-end' : s.textAlign === 'center' ? 'center' : 'flex-start';
      const flexSt = `justify-content:${justify};align-items:center`;
      parts.push(`<div data-vi="${e.role}" style="${escapeAttr(st.join(';') + ';display:flex;' + flexSt)}"><span style="${escapeAttr(t.join(';'))}">${escapeHtml(e.text)}</span></div>`);
    } else {
      parts.push(`<div data-vi="${e.role}" style="${escapeAttr(st.join(';'))}"></div>`);
    }
  }
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/>
<style>html,body{margin:0;padding:0;width:${VIEW_W}px;height:${VIEW_H}px;overflow:hidden}body{position:relative}img{max-width:none}</style>
</head><body>
${parts.join('\n')}
</body></html>`;
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
// 内联属性值转义：双引号必须转义，否则会破坏属性边界
function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, '&quot;');
}

main().catch((err) => { console.error(err); process.exit(1); });
