/**
 * code-html-compose 步骤 9：基于语义树生成「可维护」的 Compose 布局（脚本生成，避免大模型跑偏）。
 *
 * 高保真基线：以语义树提供几何和样式，以原始 HTML 截图提供视觉真源，逐元素确定性生成。
 * 先通过「元素边界校验 + 文本/关键区块抽查」，再允许独立进行语义化重构。
 *
 * 输入：
 *   - 语义树 JSON：tools/out/semantic.json（normalize.js 产出，坐标为设计稿 px）
 *   - 设计图资源目录：由 DESIGN_DIR 指定（含 img/*.png）
 * 输出：
 *   - app/src/main/java/com/jollyeng/www/compose/ui/activity/report/Test1Page.kt
 *   - 设计图 png 复制到 app res 目录（mipmap-xhdpi），并引用为 R.mipmap.*
 *
 * 布局策略（准确性优先）：
 *   - 当前设计稿的实际像素尺寸动态取自 semantic.json，元素坐标在 main() 中用 DP_PER_PX
 *     换算为逻辑 dp 后生成，禁止套用历史设计稿尺寸。
 *   - 根容器以当前设计稿逻辑宽高作为固定画布；运行时按窗口宽高的较小比例动态设置局部 Density，
 *     居中完整显示，不拉伸、不裁切，也不使用 graphicsLayer 掩盖基线几何误差。
 *   - 每个视觉元素直接相对根 Box 用 padding(start, top) 定位，保留 0.5dp 精度。
 *   - 每个视觉元素打 Modifier.testTag("e<domIndex>")，并记录被后层完整覆盖的不可观测节点。
 *   - 设计画布根背景图用 ImageItem(ImageParameter(data=R.mipmap.*, modifier=Modifier.fillMaxSize(),
 *     contentScale=ContentScale.FillBounds))，只铺满固定逻辑画布。
 *
 * Major 约束（方法过大）：元素过多时把每个顶层 root 拆成独立 private fun Test1PageSection<k>()
 * Composable，根函数按序调用，避免单个方法字节码超 64KB（MethodTooLargeException）。
 */
const fs = require('fs');
const path = require('path');
const {
  buildBoxDecorationModifier,
  buildCroppedBackgroundModifier,
  buildResponsivePageRoot,
  convertSemanticToDp,
  deriveBackgroundImageGeometry,
  deriveTextRenderMetrics,
  deriveTextPlacement,
  findObservableElements,
  orderVisualElements,
  shouldFillRootBackground,
} = require('./compose-generation-core');
const {
  capitalizeFirst,
  chineseToCamel,
  computeListGeometry,
  detectCardGroups,
  detectGridInfo,
  detectRepeatedTextGroups,
  extractCardSlots,
  findTitleForGroup,
  inferComponentName,
  matchSlot,
} = require('./compose-list-core');
const {
  collectExclusiveSlots,
  filterReferenceUnsupportedImages,
  isRuleEnabled,
  loadExperienceState,
  normalizeListGeometry,
  recordExperienceEvent,
  roundToHalf,
} = require('./compose-generation-rules');
const {
  COMPOSE_IMAGE_IMPORTS,
  COMPOSE_ACTIVITY,
  COMPOSE_KOTLIN_DIR,
  COMPOSE_PACKAGE,
  COMPOSE_RES_DIR,
  COMPOSE_R_IMPORT,
  DESIGN_DIR,
  EXPERIENCE_RULES_PATH,
  PROJECT_ROOT,
  TOOL_OUTPUT_DIR,
  requiredSetting,
} = require('./config');
const { ensureLandscapeActivity } = require('./launcher-activity');

const TOOLS = __dirname;
const SEMANTIC = path.join(TOOL_OUTPUT_DIR, 'semantic.json');
const GENERATION_REPORT = path.join(TOOL_OUTPUT_DIR, 'compose-generation-report.json');
const EXPERIENCE_RULES = EXPERIENCE_RULES_PATH;
const REFERENCE_PNG = path.join(TOOL_OUTPUT_DIR, 'original.png');

// 设计稿逻辑宽高（dp）。蓝湖导出 HTML 的实际像素（@2x）动态取自 semantic.json 的 designW/designH。
// Android dp 与 px 的关系：px = dp × density（density = densityDpi / 160）。
// @2x 设计图对应 densityDpi = 320（xhdpi，密度 = 2），故 dp = px × 160 / 320 = px × 0.5。
let DESIGN_W = 667;
let DESIGN_H = 375;
// 设计图为 @2x，对应 Android 320dpi（xhdpi）。density = densityDpi / 160 = 2。
const DESIGN_DENSITY_DPI = 320;
// 设计稿 css px → dp 的换算比例。
//   默认 0.5：蓝湖 @2x 导出（css px 是物理像素，dp = px × 0.5，对应 320dpi/xhdpi）。
//   @1x 设计稿（css px 即 dp 值）应传 DP_PER_PX=1，如 812 设计稿（812×375 为 dp 值）。
const DP_PER_PX = parseFloat(process.env.DP_PER_PX || String(160 / DESIGN_DENSITY_DPI));

// 目标页面名（可经环境变量 PAGE_NAME 覆盖，如 Test2Page；默认 Test1Page）
const PAGE_NAME = process.env.PAGE_NAME || 'Test1Page';
// 目标 Compose 文件
const TARGET_KT = path.join(requiredSetting('COMPOSE_KOTLIN_DIR', COMPOSE_KOTLIN_DIR), `${PAGE_NAME}.kt`);

// 设计图资源目录（img 源）：优先 DESIGN_DIR，否则从语义树首个 bgImage 提取
const SOURCE_DIR = requiredSetting('DESIGN_DIR', DESIGN_DIR);
const IMG_DIR = path.join(SOURCE_DIR, 'img');

// 图片复制到 app res：使用已注册的 res 源目录 layouts/v2/report
// 图片密度目录与设计稿倍率一致：@2x（DP_PER_PX=0.5）→ xhdpi，@1x（DP_PER_PX=1）→ mdpi（1dp=1px）。
// 放错目录会导致 density 320 模拟器把 @1x 图误判为 @2x 而缩小一半。
const RES_IMG_DIR = path.join(
  requiredSetting('COMPOSE_RES_DIR', COMPOSE_RES_DIR),
  `mipmap-${DP_PER_PX < 1 ? 'xhdpi' : 'mdpi'}`,
);
const KOTLIN_PACKAGE = requiredSetting('COMPOSE_PACKAGE', COMPOSE_PACKAGE);
const R_IMPORT = requiredSetting('COMPOSE_R_IMPORT', COMPOSE_R_IMPORT);
const IMAGE_IMPORTS = requiredSetting('COMPOSE_IMAGE_IMPORTS', COMPOSE_IMAGE_IMPORTS);

// ---------------- 工具 ----------------
function rgbToColor(rgb) {
  if (!rgb) return null;
  const m = rgb.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/);
  if (!m) return null;
  const r = Math.round(Number(m[1]));
  const g = Math.round(Number(m[2]));
  const b = Math.round(Number(m[3]));
  const a = m[4] !== undefined ? Math.round(Number(m[4]) * 255) : 255;
  return `Color(0x${[a, r, g, b].map((v) => v.toString(16).padStart(2, '0').toUpperCase()).join('')})`;
}

function parseRadius(radius) {
  if (!radius || radius === '0px') return 0;
  const m = radius.match(/([\d.]+)px/);
  return m ? Number(m[1]) : 0;
}

function parseBoxShadow(shadow) {
  // 形如 rgba(0,0,0,0.06) 0px 0px 4px 0px
  if (!shadow) return null;
  const m = shadow.match(/rgba?\([^)]*\)\s+([\d.]+)px\s+([\d.]+)px\s+([\d.]+)px/);
  if (!m) return null;
  return { elevation: Math.max(1, Number(m[3]) / 2) };
}

function fontWeightNumber(fw) {
  if (!fw) return 400;
  const n = parseInt(fw, 10);
  return isNaN(n) ? 400 : n;
}

function fontWeightExpr(n) {
  if (n >= 900) return 'FontWeight.Black';
  if (n >= 700) return 'FontWeight.Bold';
  if (n >= 600) return 'FontWeight.SemiBold';
  if (n >= 500) return 'FontWeight.Medium';
  return 'FontWeight.Normal';
}

function esc(str) {
  return String(str).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
}

// ---------------- 图片收集与复制 ----------------
function collectImages(elements) {
  const map = new Map(); // 文件名 -> 资源名
  let idx = 0;
  for (const e of elements) {
    let file = null;
    if (e.role === 'image' && e.imgSrc) {
      file = path.basename(e.imgSrc);
    } else if (e.style && e.style.bgImage) {
      const m = e.style.bgImage.match(/url\("?([^")]+)"?\)/);
      if (m) file = path.basename(m[1]);
    }
    if (!file) continue;
    if (map.has(file)) continue;
    map.set(file, `icon_report_html_${idx++}`);
  }
  return map;
}

function copyImages(semantic) {
  const map = collectImages(semantic.elements);
  const copied = [];
  fs.mkdirSync(RES_IMG_DIR, { recursive: true });
  for (const [file, resName] of map.entries()) {
    const src = path.join(IMG_DIR, file);
    if (!fs.existsSync(src)) {
      console.warn(`  图片缺失，跳过：${src}`);
      continue;
    }
    const ext = path.extname(file) || '.png';
    const destName = resName + (ext === '.jpg' || ext === '.jpeg' ? '.jpg' : '.png');
    fs.copyFileSync(src, path.join(RES_IMG_DIR, destName));
    copied.push({ resName, file });
  }
  return copied;
}

// ---------------- 嵌套层级构建（无 offset，用 padding 定位） ----------------
function resolveResName(e, imgMap) {
  if (e.role === 'image' && e.imgSrc) {
    const file = path.basename(e.imgSrc);
    return imgMap.get(file);
  }
  if (e.style && e.style.bgImage) {
    const m = e.style.bgImage.match(/url\("?([^")]+)"?\)/);
    if (m) return imgMap.get(path.basename(m[1]));
  }
  return null;
}

// normalize.js 的文本容器使用 flex + align-items:center；Compose 使用相同的容器内居中语义。
function genContentAlignment(textAlign) {
  switch (textAlign) {
    case 'right':
      return 'Alignment.CenterEnd';
    case 'center':
      return 'Alignment.Center';
    default:
      return 'Alignment.CenterStart';
  }
}

function rectContains(a, b) {
  return a.x <= b.x && a.y <= b.y && a.x + a.w >= b.x + b.w && a.y + a.h >= b.y + b.h;
}

// 严格包含：a 包含 b 且两者 rect 不完全相同，避免形成环。
function rectContainsStrict(a, b) {
  return (
    rectContains(a, b) &&
    !(a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h)
  );
}

// 四舍五入到 0.5dp，保留设计稿半像素精度（整数取整会丢掉 0.5 导致坐标漂移）。
function r05(v) {
  return Math.max(0, Math.round(v * 2) / 2);
}

// rect 的唯一键（用于按位置合并同 rect 元素 / 匹配列表宿主）。
function rectKey(r) {
  return `${r.x},${r.y},${r.w},${r.h}`;
}

// 只有真正从视口原点铺满的背景才能转成 fillMaxSize；源 HTML 的 body margin 是设计的一部分。
function isFullScreenBg(e, designW, designH) {
  return shouldFillRootBackground({
    rect: e.rect,
    hasImage: Boolean((e.style && e.style.bgImage) || e.imgSrc),
  }, designW, designH);
}

// 全屏纯色根容器（如 .page 的白色背景）：铺满视口、仅背景色、无图片无文字。
// 这类元素应作为根 Box 的底色，而非生成一个覆盖层（否则会盖住根背景图，导致背景颜色错乱）。
function isFullScreenPlainBox(e, designW, designH) {
  if (!e.style || !e.style.bgColor) return false;
  if (e.style.bgImage || e.imgSrc || e.text) return false;
  return e.rect.x <= 0.01 && e.rect.y <= 0.01 &&
    e.rect.w >= designW - 0.01 && e.rect.h >= designH - 0.01;
}

// 按 rect + 内容签名去重：normalize.js 会因 DOM 嵌套产生相同 rect 的重复元素。
function deduplicate(elements) {
  const seen = new Map(); // rectKey -> { sig }
  const out = [];
  for (const e of elements) {
    const k = `${e.rect.x},${e.rect.y},${e.rect.w},${e.rect.h}`;
    const sig = `${e.role}|${e.imgSrc || ''}|${e.text || ''}|${(e.style && e.style.bgImage) || ''}`;
    const entry = seen.get(k);
    if (!entry) {
      seen.set(k, { sig });
      out.push(e);
    } else if (entry.sig !== sig) {
      out.push(e);
    }
  }
  return out;
}

// 构建几何包含树：每个元素挂到"面积最小且包含它"的容器下
function buildTree(elements) {
  const nodes = elements.map((e) => ({ e, children: [], parent: null }));
  for (const n of nodes) {
    let best = null;
    let bestArea = Infinity;
    for (const m of nodes) {
      if (m === n) continue;
      if (rectContainsStrict(m.e.rect, n.e.rect)) {
        const area = m.e.rect.w * m.e.rect.h;
        if (area < bestArea) {
          best = m;
          bestArea = area;
        }
      }
    }
    if (best) {
      best.children.push(n);
      n.parent = best;
    }
  }
  for (const n of nodes) n.children.sort((a, b) => a.e.z - b.e.z);
  return nodes.filter((n) => !n.parent);
}

// 渲染元素自身内容（不含外层的 padding 定位层）。每个叶子元素带 testTag 供边界校验。
function genContent(e, ctx, indent) {
  const imgMap = ctx.imgMap;
  const pad = ' '.repeat(indent);
  const w = e.rect.w, h = e.rect.h;
  const s = e.style || {};
  const radius = parseRadius(s.borderRadius);
  const res = resolveResName(e, imgMap);
  const tag = `Modifier.testTag("e${e.domIndex}")`;

  // 图片 / 背景图：用 ImageItem 填充
  if (res) {
    const clip = radius > 0 ? `.clip(RoundedCornerShape(${radius}.dp))` : '';
    const backgroundGeometry = s.bgImage ? deriveBackgroundImageGeometry({
      boundsWidth: w,
      boundsHeight: h,
      backgroundSize: s.bgSize,
      backgroundPosition: s.bgPosition,
    }) : null;
    if (backgroundGeometry) {
      const imageModifier = buildCroppedBackgroundModifier(backgroundGeometry);
      return (
        `${pad}Box(modifier = ${tag}.size(${w}.dp, ${h}.dp).clipToBounds()) {\n` +
        `${pad}    ImageItem(\n` +
        `${pad}        parameter = ImageParameter(\n` +
        `${pad}            data = R.mipmap.${res},\n` +
        `${pad}            modifier = ${imageModifier},\n` +
        `${pad}            contentScale = ContentScale.FillBounds,\n` +
        `${pad}        ),\n` +
        `${pad}    )\n` +
        `${pad}}\n`
      );
    }
    return (
      `${pad}ImageItem(\n` +
      `${pad}    parameter = ImageParameter(\n` +
      `${pad}        data = R.mipmap.${res},\n` +
      `${pad}        modifier = ${tag}.size(${w}.dp, ${h}.dp)${clip},\n` +
      `${pad}        contentScale = ContentScale.FillBounds,\n` +
      `${pad}    ),\n` +
      `${pad})\n`
    );
  }

  // 纯文本
  if (e.role === 'text' && e.text) {
    const color = rgbToColor(s.color) || 'Color.Black';
    let fontSize = s.fontSize ? parseFloat(s.fontSize) : 14;
    let lineHeight = s.lineHeight && s.lineHeight !== 'normal' ? parseFloat(s.lineHeight) : fontSize;
    const fw = fontWeightExpr(fontWeightNumber(s.fontWeight));
    const placement = deriveTextPlacement(e, ctx.elements);
    const align = placement.alignment;
    // 外层逻辑边界固定为设计稿尺寸；内部绘制框允许垂直扩展，避免中文/粗体墨迹被紧贴行框裁掉。
    const isNowrap = s.whiteSpace === 'nowrap';
    // 最大行数按设计稿 rect 高度推算（normal 多行文本），避免实际行数超过设计稿导致底部被裁。
    const maxLines = isNowrap ? 1 : Math.max(1, Math.floor(Math.max(1, h) / Math.max(1, lineHeight)));
    const renderMetrics = deriveTextRenderMetrics({
      boundsHeight: h,
      fontSize,
      lineHeight,
      maxLines,
      isNowrap,
    });
    const visualOffsetY = placement.visualOffsetY;
    const textModifier = `Modifier.requiredSize(width = ${w}.dp, height = ${renderMetrics.renderHeight}.dp)` +
      (visualOffsetY === 0 ? '' : `.graphicsLayer { translationY = ${visualOffsetY}.dp.toPx() }`);
    // 文本装饰（如链接下划线 "查看详情"）
    const decoration = s.textDecoration && s.textDecoration !== 'none'
      ? `, textDecoration = TextDecoration.${s.textDecoration === 'underline' ? 'Underline' : 'Underline'}`
      : '';
    return (
      `${pad}Box(\n` +
      `${pad}    modifier = ${tag}.size(${w}.dp, ${h}.dp),\n` +
      `${pad}    contentAlignment = ${genContentAlignment(align)},\n` +
      `${pad}) {\n` +
      `${pad}    ${renderMetrics.fitWidth ? 'FittedSingleLineText' : 'Text'}(\n` +
      `${pad}        modifier = ${textModifier},\n` +
      (renderMetrics.fitWidth
        ? `${pad}        maxWidth = ${w}.dp,\n` +
          `${pad}        contentAlignment = ${genContentAlignment(align)},\n` +
          `${pad}        horizontalOrigin = ${align === 'right' ? '1f' : align === 'center' ? '0.5f' : '0f'},\n`
        : '') +
      `${pad}        text = "${esc(e.text)}",\n` +
      `${pad}        maxLines = ${maxLines},\n` +
      `${pad}        overflow = TextOverflow.${renderMetrics.allowInkOverflow ? 'Visible' : 'Clip'},\n` +
      `${pad}        softWrap = ${isNowrap ? 'false' : 'true'},\n` +
      `${pad}        style = TextStyle(\n` +
      `${pad}            fontSize = ${fontSize}.sp,\n` +
      `${pad}            lineHeight = ${renderMetrics.renderLineHeight}.sp,\n` +
      `${pad}            color = ${color},\n` +
      `${pad}            fontWeight = ${fw},\n` +
      `${pad}            textAlign = TextAlign.${align === 'right' ? 'Right' : align === 'center' ? 'Center' : 'Start'}${decoration},\n` +
      `${pad}            platformStyle = PlatformTextStyle(includeFontPadding = ${renderMetrics.includeFontPadding}),\n` +
      `${pad}        ),\n` +
      `${pad}    )\n` +
      `${pad}}\n`
    );
  }

  // 纯色块（含圆角 / 阴影）
  const bgColor = rgbToColor(s.bgColor);
  if (bgColor) {
    const shadow = parseBoxShadow(s.boxShadow);
    const mod = buildBoxDecorationModifier({
      tag,
      width: w,
      height: h,
      radius,
      backgroundColor: bgColor,
      shadowElevation: shadow ? shadow.elevation : 0,
    });
    return `${pad}Box(modifier = ${mod}) {}\n`;
  }

  // 透明容器：仅作为子元素定位容器，无可见内容
  return null;
}

// 是否透明容器：无图片、无背景色、无背景图、无文本 → 仅作定位容器。
// 扁平化阶段会把它移除，子节点提升到父级，从而让更多兄弟叶子成为对齐组（Column/Row）。
function isTransparentContainer(e) {
  const s = e.style || {};
  return !e.imgSrc && !s.bgImage && !s.bgColor && !e.text;
}

// 扁平化透明容器：移除无内容的容器，把其子节点提升到父级，保持绝对几何不变。
function flattenTransparent(nodes) {
  const roots = [];
  function walk(node, parent, out) {
    const kids = node.children;
    if (isTransparentContainer(node.e) && kids.length > 0) {
      for (const k of kids) {
        k.parent = parent;
        walk(k, parent, out);
      }
      return; // 容器本身不输出
    }
    const newKids = [];
    for (const k of kids) walk(k, node, newKids);
    node.children = newKids;
    out.push(node);
  }
  for (const r of nodes) walk(r, null, roots);
  return roots;
}

// 合并同 rect 的兄弟节点（双背景）：设计稿会出现同一位置叠放两张背景层的情况
// （如"今日已读"分区 e16 + e31 同为 bg-image、同 rect）。若直接平铺渲染，两者互相
// 叠加没问题，但列表一旦嵌套进主容器，会被后画的兄弟背景层盖住而丢失。
// 因此这里把"无子节点"的同 rect 兄弟降级为主节点的背景层（layers），随主容器一起渲染，
// 且保持原 z 序（主节点内容先画，layers 后画），视觉不缺失，列表也能安全嵌套进主容器。
function mergeSameRectChildren(roots) {
  function walk(node) {
    (node.children || []).forEach(walk);
    const byRect = new Map();
    for (const child of node.children || []) {
      const k = rectKey(child.e.rect);
      if (!byRect.has(k)) byRect.set(k, []);
      byRect.get(k).push(child);
    }
    const merged = [];
    for (const group of byRect.values()) {
      if (group.length === 1) {
        merged.push(group[0]);
        continue;
      }
      // 主容器 = 有子节点的那个；其余无子节点的同 rect 节点降级为背景层
      const main = group.find((n) => n.children.length > 0) || group[0];
      for (const n of group) {
        if (n === main) continue;
        if (n.children.length === 0) {
          main.layers = main.layers || [];
          main.layers.push(n.e);
        } else {
          // 双方都有子节点（罕见）：保留为独立兄弟，避免破坏内部嵌套
          merged.push(n);
        }
      }
      merged.push(main);
    }
    node.children = merged;
  }
  for (const r of roots) {
    r.layers = r.layers || [];
    walk(r);
  }
  return roots;
}

// 查找列表宿主容器：树中"面积最小且包含所有卡片中心点"的节点。
// 用中心点而非完整矩形判定，兼容"卡片底部略溢出分区背景"的设计（今日已读 4 卡中
// 底部两卡的中心仍在分区 e16 内，但下缘超出 e16 背景；用中心判定仍能命中 e16 作宿主，
// 使列表能嵌套进所在分区，而不是平铺在根容器）。
function findListHost(group, roots) {
  const centers = group.map((c) => ({
    x: c.rect.x + c.rect.w / 2,
    y: c.rect.y + c.rect.h / 2,
  }));
  let best = null;
  let bestArea = Infinity;
  function walk(node) {
    const r = node.e.rect;
    const allIn = centers.every(
      (c) => r.x <= c.x && c.x <= r.x + r.w && r.y <= c.y && c.y <= r.y + r.h,
    );
    if (allIn && !group.some((c) => c.domIndex === node.e.domIndex)) {
      const area = r.w * r.h;
      if (area < bestArea) {
        best = node;
        bestArea = area;
      }
    }
    (node.children || []).forEach(walk);
  }
  (roots || []).forEach(walk);
  return best;
}

// ---------------- 左侧导航聚合 ----------------
// 左侧导航聚合：把根下零散的左导航元素（图标 + 文字）聚合成一个 LeftNavBar 合成容器。
// 设计稿左侧有一列竖排导航（课程/书架/磨耳朵/报告 + 图标），语义树里它们是根下的平级元素，
// 相互独立、无公共父容器。这里按 x 坐标阈值挑出左侧导航元素，用外接矩形作为容器，
// 内部按相对坐标嵌套，使生成代码呈现"LeftNavBar 包含各导航项"的层级结构
// （参考 ReportHomeV3Layout 的 LeftMenu 写法）。
function groupLeftNav(roots, designW) {
  const threshold = Math.min(120, designW * 0.15); // 左侧导航 x 阈值（dp）
  const navNodes = roots.filter(
    (r) => r.e.rect.x < threshold && r.e.rect.x + r.e.rect.w < threshold + 40
  );
  if (navNodes.length < 3) return roots; // 没有明显的左导航列，不合成
  const minX = Math.min(...navNodes.map((n) => n.e.rect.x));
  const minY = Math.min(...navNodes.map((n) => n.e.rect.y));
  const maxX = Math.max(...navNodes.map((n) => n.e.rect.x + n.e.rect.w));
  const maxY = Math.max(...navNodes.map((n) => n.e.rect.y + n.e.rect.h));
  const synth = {
    e: {
      domIndex: -1,
      role: 'container',
      className: 'left-nav',
      rect: { x: minX, y: minY, w: maxX - minX, h: maxY - minY },
      z: Math.max(...navNodes.map((n) => n.e.z || 0)) + 1,
      style: {}, imgSrc: null, text: null,
    },
    children: navNodes,
    layers: [],
    parent: null,
    synthetic: true,
  };
  const navSet = new Set(navNodes);
  const newRoots = roots.filter((r) => !navSet.has(r));
  newRoots.push(synth); // 导航 z 序高，放在最后绘制（盖在最上层）
  return newRoots;
}

// 从树中摘除被列表包含的卡片节点（卡片自身 + 公共槽位子元素）。
// 卡片中"非公共槽位"的子元素（如某张卡独有的"Quiz 90%"徽标）不在列表数据里，
// 需要提升为根级覆盖层单独渲染（保持原 z 序），保证视觉无缺失。
function removeListCards(roots, excludedDomIndices) {
  const overlays = [];
  function detachChildren(node) {
    const kept = [];
    for (const child of node.children || []) {
      if (excludedDomIndices.has(child.e.domIndex)) {
        // 卡片（或公共槽位子元素）由列表渲染，从其父节点摘除；
        // 其下"非公共槽位"的子元素提升为根级覆盖层
        for (const gc of child.children || []) {
          if (!excludedDomIndices.has(gc.e.domIndex)) overlays.push(gc);
        }
        continue;
      }
      detachChildren(child);
      kept.push(child);
    }
    node.children = kept;
  }
  // 摘除子节点后，也要过滤根级被排除的节点：某些卡片因几何上溢出所在分区
  // （如"今日已读"的底部卡片超出分区 rect）而成为根节点，若只清理子节点，
  // 这些卡片会被重复渲染（既在 Lazy 网格里、又在根级平铺一次）。
  // 被排除根节点下的"非公共槽位"子元素同样提升为根级覆盖层，保证视觉无缺失。
  for (const r of roots) detachChildren(r);
  const keptRoots = [];
  for (const r of roots) {
    if (excludedDomIndices.has(r.e.domIndex)) {
      for (const gc of r.children || []) {
        if (!excludedDomIndices.has(gc.e.domIndex)) overlays.push(gc);
      }
      continue;
    }
    keptRoots.push(r);
  }
  roots = keptRoots;
  if (overlays.length > 0) {
    roots = roots.concat(overlays);
    roots.sort((a, b) => (a.e.z || 0) - (b.e.z || 0));
  }
  return roots;
}

// ---------------- 列表渲染（数据驱动） ----------------
// 渲染一个列表项的单个子元素（图片或文本），值从数据类字段读取。
// 布局结构与 genContent 保持一致的精确性：外层 Box 锁 design 尺寸 + testTag，
// 内部按 renderH/行高等渲染，保证结构校验与视觉还原。
// 返回 Kotlin 代码片段；slotIdx 为数据类字段下标。
function genListItemSlotCode(slot, slotIdx, indent, ctx, imgMap) {
  const pad = ' '.repeat(indent);
  const e = slot.element;
  const s = e.style || {};
  const w = e.rect.w;
  const h = e.rect.h;
  const res = slot.res ? `R.mipmap.${slot.res}` : null;

  if (res) {
    // 图片 / 背景图子元素
    const radius = slot.radius > 0 ? `.clip(RoundedCornerShape(${slot.radius}.dp))` : '';
    const imageModifier = slot.crop
      ? `Modifier.wrapContentSize(unbounded = true, align = Alignment.TopStart).requiredSize(width = ${slot.crop.imgW}.dp, height = ${slot.crop.imgH}.dp).graphicsLayer { translationX = ${slot.crop.offX}.dp.toPx(); translationY = ${slot.crop.offY}.dp.toPx() }`
      : `Modifier.size(${w}.dp, ${h}.dp)${radius}`;
    // 链式拼接：testTag 之后接 imageModifier（去掉开头的 "Modifier."，补连接点）
    const chained = `${imageModifier.replace(/^Modifier\./, '.')}${slot.crop ? '.clipToBounds()' : ''}`;
    return (
      `${pad}Box(\n` +
      `${pad}    modifier = Modifier.padding(start = ${slot.relX}.dp, top = ${slot.relY}.dp)) {\n` +
      `${pad}    ImageItem(\n` +
      `${pad}        parameter = ImageParameter(\n` +
      `${pad}            data = item.children[${slotIdx}]?.res,\n` +
      `${pad}            modifier = Modifier.testTag(item.children[${slotIdx}]?.tag ?: "")${chained},\n` +
      `${pad}            contentScale = ContentScale.FillBounds,\n` +
      `${pad}        ),\n` +
      `${pad}    )\n` +
      `${pad}}\n`
    );
  }

  // 文本子元素
  const align = slot.align || 'left';
  const textModifier =
    `Modifier.requiredSize(width = ${w}.dp, height = ${slot.renderH}.dp)` +
    (slot.visualOffsetY ? `\n${pad}        .graphicsLayer { translationY = ${slot.visualOffsetY}.dp.toPx() }` : '');
  return (
    `${pad}Box(\n` +
    `${pad}    modifier = Modifier.padding(start = ${slot.relX}.dp, top = ${slot.relY}.dp)) {\n` +
    `${pad}    Box(\n` +
    `${pad}        modifier = Modifier.testTag(item.children[${slotIdx}]?.tag ?: "").size(${w}.dp, ${h}.dp),\n` +
    `${pad}        contentAlignment = ${genContentAlignment(align)},\n` +
    `${pad}    ) {\n` +
    `${pad}        Text(\n` +
    `${pad}            modifier = ${textModifier},\n` +
    `${pad}            text = item.children[${slotIdx}]?.text ?: "",\n` +
    `${pad}            maxLines = ${slot.maxLines},\n` +
    `${pad}            overflow = TextOverflow.${slot.allowInkOverflow ? 'Visible' : 'Clip'},\n` +
    `${pad}            softWrap = ${slot.isNowrap ? 'false' : 'true'},\n` +
    `${pad}            style = TextStyle(\n` +
    `${pad}                fontSize = ${slot.fontSize}.sp,\n` +
    `${pad}                lineHeight = ${slot.renderLineHeight}.sp,\n` +
    `${pad}                color = ${slot.color},\n` +
    `${pad}                fontWeight = ${slot.fontWeightExpr},\n` +
    `${pad}                textAlign = TextAlign.${align === 'right' ? 'Right' : align === 'center' ? 'Center' : 'Start'},\n` +
    `${pad}                platformStyle = PlatformTextStyle(includeFontPadding = ${slot.includeFontPadding}),\n` +
    `${pad}            ),\n` +
    `${pad}        )\n` +
    `${pad}    }\n` +
    `${pad}}\n`
  );
}

// 构建单个槽位相对指定卡片的描述（相对坐标 + 渲染指标 + 资源名）。
// 抽出为独立函数，使"模板卡统一定义"与"逐卡精确几何"共用同一套槽位计算逻辑。
// 列表项渲染一律以各卡自身匹配到的槽位元素为准（见 childValueCode），
// 这样即使卡片间槽位文本宽度参差（如"今日已读"标题/描述宽度 87-90dp），
// 每张卡仍按其设计宽高还原，不因模板卡统一宽而失真。
function buildSlotForCard(slotEl, card, ctx, imgMap) {
  const es = slotEl.style || {};
  const color = rgbToColor(es.color) || 'Color.Black';
  let fontSize = es.fontSize ? parseFloat(es.fontSize) : 14;
  let lineHeight = es.lineHeight && es.lineHeight !== 'normal' ? parseFloat(es.lineHeight) : fontSize;
  const isNowrap = es.whiteSpace === 'nowrap';
  const maxLines = isNowrap ? 1 : Math.max(1, Math.floor(Math.max(1, slotEl.rect.h) / Math.max(1, lineHeight)));
  const renderMetrics = deriveTextRenderMetrics({ boundsHeight: slotEl.rect.h, fontSize, lineHeight, maxLines, isNowrap });
  const placement = deriveTextPlacement(slotEl, ctx.elements);
  const res = resolveResName(slotEl, imgMap);
  const crop = es.bgImage
    ? deriveBackgroundImageGeometry({ boundsWidth: slotEl.rect.w, boundsHeight: slotEl.rect.h, backgroundSize: es.bgSize, backgroundPosition: es.bgPosition })
    : null;
  return {
    element: slotEl,
    res,
    crop,
    relX: Math.round((slotEl.rect.x - card.rect.x) * 10) / 10,
    relY: Math.round((slotEl.rect.y - card.rect.y) * 10) / 10,
    radius: parseRadius(es.borderRadius),
    align: placement.alignment,
    visualOffsetY: placement.visualOffsetY,
    fontSize,
    lineHeight,
    renderLineHeight: renderMetrics.renderLineHeight,
    renderH: renderMetrics.renderHeight,
    maxLines,
    isNowrap,
    allowInkOverflow: renderMetrics.allowInkOverflow,
    includeFontPadding: renderMetrics.includeFontPadding,
    color,
    fontWeightExpr: fontWeightExpr(fontWeightNumber(es.fontWeight)),
  };
}

// 从模板卡片构建槽位描述（相对坐标 + 渲染指标 + 资源名），供生成列表项数据类与 item Composable。
function buildSlotDescriptors(card, templateSlots, ctx, imgMap) {
  const s = card.style || {};
  const w = card.rect.w;
  const h = card.rect.h;
  const cardRes = resolveResName(card, imgMap);
  // 卡片自身背景图（含裁剪几何）
  const bgCrop = s.bgImage
    ? deriveBackgroundImageGeometry({ boundsWidth: w, boundsHeight: h, backgroundSize: s.bgSize, backgroundPosition: s.bgPosition })
    : null;
  return { cardRes, bgCrop, w, h, slots: templateSlots.map((te) => buildSlotForCard(te, card, ctx, imgMap)) };
}

// 生成一个列表组的完整 Kotlin 代码：数据类 + 列表数据 + item Composable + Lazy 容器调用。
// 返回 { callCode, comps, excluded }：
//   callCode  — 插入根 Box 的调用代码（含 Lazy 容器）
//   comps     — 需要追加到文件底部的方法/数据定义
//   excluded  — 本组占用的元素 domIndex 集合（基线渲染时跳过）
function genListGroupCode(group, ctx, imgMap, opts = {}) {
  console.log('[DEBUG] group =', group.map((c) => `${c.domIndex}:${c.rect.x},${c.rect.y},${c.rect.w},${c.rect.h} text="${(c.text||'').slice(0,12)}"`));
  const baseGeometry = computeListGeometry(group);
  const grid = detectGridInfo(group);
  const normalizedGeometry = isRuleEnabled(ctx.ruleState, 'uniform-list-card-geometry')
    ? normalizeListGeometry(group, baseGeometry, grid)
    : {
        itemW: group[0].rect.w,
        itemH: group[0].rect.h,
        colGap: baseGeometry.colGap,
        rowGap: baseGeometry.rowGap,
        containerRect: baseGeometry.containerRect,
      };
  const { containerRect, rowGap, colGap, itemW, itemH } = normalizedGeometry;
  const designW = DESIGN_W;
  const designH = DESIGN_H;
  // 相对父容器的定位（嵌套渲染用）：传入 parentRect 时，Lazy 容器调用以父容器为原点，
  // 使列表能作为子组件嵌套进所在分区；不传时保持绝对定位（根级调用）。
  const parentRect = opts.parentRect || null;
  // 相对父容器定位（嵌套渲染用）：保留 0.5dp 精度，使列表能作为子组件嵌套进所在分区
  const relX = r05(containerRect.x - (parentRect ? parentRect.x : 0));
  const relY = r05(containerRect.y - (parentRect ? parentRect.y : 0));

  // 见名知意的列表名：优先用上方标题语义，否则按位置兜底
  const title = findTitleForGroup(group, ctx.elements);
  let baseName = '';
  if (title) {
    baseName = chineseToCamel(title.text.trim().replace(/\s+/g, ''));
  }
  if (!baseName) {
    baseName = containerRect.y < designH / 3 ? 'Top' : containerRect.y > (designH * 2) / 3 ? 'Bottom' : 'Middle';
  }
  const listName = `${baseName}List`;
  const itemName = `${baseName}Card`;
  const itemDataType = `${itemName}Data`;
  const dataVar = `${listName}Data`;
  const viewportTag = `${listName.charAt(0).toLowerCase()}${listName.slice(1)}Viewport`;

  // 模板卡片 = 第一个卡片；其子元素作为槽位模板
  // 按视觉顺序排序（从上到下，从左到右），确保 Lazy 容器按正确视觉顺序渲染
  group.sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
  const templateCard = group[0];
  const templateSlots = extractCardSlots(templateCard, ctx.elements);

  // 结构一致性校验（公共槽位口径）：列表要求所有卡片共享同一套核心槽位——
  // 封面图 + 标题/描述文本。逐卡对每个模板槽位做匹配，取"所有卡片都命中"的槽位为公共槽位；
  // 仅出现在部分卡片上的额外槽位（如某张卡的附加徽标"Quiz 90%"）不属于公共槽位，
  // 由基线渲染单独覆盖，避免因一张卡的差异而放弃整组列表。
  const slotMatches = group.map((card) =>
    templateSlots.map((ts) => matchSlot(card, ts, templateCard, ctx.elements)),
  );
  const commonMask = templateSlots.map((_, i) => slotMatches.every((row) => row[i] !== null));
  const commonSlotIndices = commonMask
    .map((hit, i) => (hit ? i : -1))
    .filter((i) => i >= 0);
  const commonSlots = commonSlotIndices.map((i) => templateSlots[i]);
  // 公共槽位必须覆盖"封面图 + 文本"且数量 ≥2，才视为结构一致的重复卡片；
  // 否则（如"阅读量/阅读时长/磨耳朵"三张卡槽位差异大）回退为逐元素基线渲染。
  const hasCover = commonSlots.some((te) => resolveResName(te, imgMap));
  const hasText = commonSlots.some((te) => te.role === 'text');
  if (commonSlots.length < 2 || !hasCover || !hasText) {
    console.log(`  跳过列表组「${baseName || '未命名'}」：公共槽位不足（需封面+文本），回退为基线渲染`);
    return null;
  }

  // 高度一致性守卫：相似卡片要求各卡同高（≤2dp 即 4px）。若卡片高度参差
  // （如"今日已读"两行卡高 169/156px、且槽位文本宽度也不同），强行归一并嵌套进
  // 分区会被分区 clipToBounds 裁剪底部、并损失逐卡几何精度。此时回退为逐元素基线渲染，
  // 每张卡按其精确 rect 定位，既不裁切也不失真。
  const hMin = Math.min(...group.map((c) => c.rect.h));
  const hMax = Math.max(...group.map((c) => c.rect.h));
  if (hMax - hMin > 4) {
    console.log(`  跳过列表组「${baseName || '未命名'}」：卡片高度不统一（${hMin}-${hMax}px），回退为基线渲染`);
    return null;
  }

  // 说明：卡片间公共槽位宽度参差（如"今日已读"标题/描述宽 87-90dp）不再导致回退。
  // 列表项按各自匹配到的槽位元素渲染（见 childValueCode / item.children 逐卡几何），
  // 每张卡按自身设计宽高还原，因此保留懒加载列表的同时不失真。

  const exclusiveSlots = isRuleEnabled(ctx.ruleState, 'card-exclusive-slots-stay-in-item')
    ? collectExclusiveSlots(
        group,
        slotMatches.map((row) => commonSlotIndices.map((index) => row[index])),
        ctx.elements,
        extractCardSlots,
      )
    : group.map(() => []);
  const cardRadius = roundToHalf(parseRadius(templateCard.style && templateCard.style.borderRadius) || 9);

  const descriptor = buildSlotDescriptors(templateCard, commonSlots, ctx, imgMap);

  function colorArgbLiteral(style) {
    const match = String(style && style.color || '').match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/);
    if (!match) return '4278190080L';
    const alpha = Math.round((match[4] === undefined ? 1 : Number(match[4])) * 255);
    const value = (BigInt(alpha) << 24n) |
      (BigInt(Math.round(Number(match[1]))) << 16n) |
      (BigInt(Math.round(Number(match[2]))) << 8n) |
      BigInt(Math.round(Number(match[3])));
    return `${value.toString()}L`;
  }

  function extraValueCode(slot, card) {
    const extraDescriptor = buildSlotDescriptors(card, [slot], ctx, imgMap).slots[0];
    const align = extraDescriptor.align === 'right' ? 2 : extraDescriptor.align === 'center' ? 1 : 0;
    const res = extraDescriptor.res ? `R.mipmap.${extraDescriptor.res}` : 'null';
    return `CardExtraValue(\n` +
      `                tag = "e${slot.domIndex}",\n` +
      `                res = ${res},\n` +
      `                text = ${slot.text ? `"${esc(slot.text)}"` : 'null'},\n` +
      `                x = ${extraDescriptor.relX}f,\n` +
      `                y = ${extraDescriptor.relY}f,\n` +
      `                w = ${slot.rect.w}f,\n` +
      `                h = ${slot.rect.h}f,\n` +
      `                renderH = ${extraDescriptor.renderH}f,\n` +
      `                fontSize = ${extraDescriptor.fontSize}f,\n` +
      `                renderLineHeight = ${extraDescriptor.renderLineHeight}f,\n` +
      `                maxLines = ${extraDescriptor.maxLines},\n` +
      `                isNowrap = ${extraDescriptor.isNowrap},\n` +
      `                allowInkOverflow = ${extraDescriptor.allowInkOverflow},\n` +
      `                colorArgb = ${colorArgbLiteral(slot.style)},\n` +
      `                fontWeight = ${fontWeightNumber(slot.style && slot.style.fontWeight)},\n` +
      `                textAlign = ${align},\n` +
      `            )`;
  }

  // 生成单个公共槽位相对"当前卡"的 ChildValue 字面量（含几何与渲染参数）。
  // 与 CardExtraValue 不同，公共槽位需要携带图片裁剪几何(cropW/H/Off*)与字体 padding。
  // 之所以用 buildSlotForCard 在每个 item 内现算，是为了让每张卡都按自身设计几何渲染，
  // 而不是强套模板卡的统一宽（宽卡与窄卡并存时模板宽会撑坏窄卡，详见 buildSlotForCard 注释）。
  function childValueCode(slotEl, card) {
    const sd = buildSlotForCard(slotEl, card, ctx, imgMap);
    const align = sd.align === 'right' ? 2 : sd.align === 'center' ? 1 : 0;
    const res = sd.res ? `R.mipmap.${sd.res}` : 'null';
    const text = slotEl.text ? `"${esc(slotEl.text)}"` : 'null';
    const cw = sd.crop ? sd.crop.imgW : 0;
    const ch = sd.crop ? sd.crop.imgH : 0;
    const cox = sd.crop ? sd.crop.offX : 0;
    const coy = sd.crop ? sd.crop.offY : 0;
    return `ChildValue(\n` +
      `        tag = "e${slotEl.domIndex}",\n` +
      `        res = ${res},\n` +
      `        text = ${text},\n` +
      `        x = ${r05(sd.relX)}f,\n` +
      `        y = ${r05(sd.relY)}f,\n` +
      `        w = ${slotEl.rect.w}f,\n` +
      `        h = ${slotEl.rect.h}f,\n` +
      `        renderH = ${sd.renderH}f,\n` +
      `        fontSize = ${sd.fontSize}f,\n` +
      `        renderLineHeight = ${sd.renderLineHeight}f,\n` +
      `        visualOffsetY = ${r05(sd.visualOffsetY || 0)}f,\n` +
      `        radius = ${sd.radius}f,\n` +
      `        align = ${align},\n` +
      `        maxLines = ${sd.maxLines},\n` +
      `        isNowrap = ${sd.isNowrap},\n` +
      `        allowInkOverflow = ${sd.allowInkOverflow},\n` +
      `        includeFontPadding = ${sd.includeFontPadding},\n` +
      `        cropW = ${cw}f,\n` +
      `        cropH = ${ch}f,\n` +
      `        cropOffX = ${cox}f,\n` +
      `        cropOffY = ${coy}f,\n` +
      `        colorArgb = ${colorArgbLiteral(slotEl.style)},\n` +
      `        fontWeight = ${fontWeightNumber(slotEl.style && slotEl.style.fontWeight)},\n` +
      `    )`;
  }

  // 收集本组占用的全部元素（卡片自身 + 公共槽位匹配到的子元素），从基线渲染中剔除；
  // 非公共槽位（如仅某张卡独有的徽标）保留在基线渲染中作为覆盖层，保证视觉无缺失。
  const excluded = new Set();
  group.forEach((card, ci) => {
    excluded.add(card.domIndex);
    commonSlotIndices.forEach((si) => {
      const m = slotMatches[ci][si];
      if (m) excluded.add(m.domIndex);
    });
    for (const extra of exclusiveSlots[ci]) excluded.add(extra.domIndex);
  });

  // ---- 数据类定义 ----
  const childValueClass = `/**
 * 列表项子值：单个槽位（图片 res 或文本 text）的渲染数据。
 * 槽位几何（x/y/w/h）与渲染参数（字号/行高/对齐等）取自该卡片自身匹配到的槽位元素，
 * 使各卡即使文本宽度参差也能按各自设计几何精确还原。tag 为校验用 domIndex。
 */
data class ChildValue(
    val tag: String,
    val res: Int?,
    val text: String?,
    val x: Float,
    val y: Float,
    val w: Float,
    val h: Float,
    val renderH: Float,
    val fontSize: Float,
    val renderLineHeight: Float,
    val visualOffsetY: Float,
    val radius: Float,
    val align: Int,
    val maxLines: Int,
    val isNowrap: Boolean,
    val allowInkOverflow: Boolean,
    val includeFontPadding: Boolean,
    val cropW: Float,
    val cropH: Float,
    val cropOffX: Float,
    val cropOffY: Float,
    val colorArgb: Long,
    val fontWeight: Int,
)`;

  const extraValueClass = `/** 卡片专属槽位：只随拥有它的列表 item 渲染，不提升到页面 overlay。 */
data class CardExtraValue(
    val tag: String,
    val res: Int?,
    val text: String?,
    val x: Float,
    val y: Float,
    val w: Float,
    val h: Float,
    val renderH: Float,
    val fontSize: Float,
    val renderLineHeight: Float,
    val maxLines: Int,
    val isNowrap: Boolean,
    val allowInkOverflow: Boolean,
    val colorArgb: Long,
    val fontWeight: Int,
    val textAlign: Int,
)`;

  const itemDataClass = `/**
 * ${itemDataType}：${baseName} 单张卡片的完整渲染数据（背景图 + 各槽位子值）。
 */
data class ${itemDataType}(
    val tag: Int,
    val bgRes: Int?,
    val w: Float,
    val h: Float,
    val children: List<ChildValue?>,
    val extras: List<CardExtraValue>,
)`;

  // ---- 列表数据 ----
  const itemInit = group.map((card, ci) => {
    const cardRes = resolveResName(card, imgMap);
    const children = commonSlotIndices.map((si) => {
      const slotEl = slotMatches[ci][si];
      if (!slotEl) return 'null';
      return childValueCode(slotEl, card);
    }).join(',\n        ');
    const extras = exclusiveSlots[ci].map((slot) => extraValueCode(slot, card)).join(',\n            ');
    return `    ${itemDataType}(\n` +
      `        tag = ${card.domIndex},\n` +
      `        bgRes = ${cardRes ? `R.mipmap.${cardRes}` : 'null'},\n` +
      `        w = ${r05(card.rect.w)}f,\n` +
      `        h = ${r05(card.rect.h)}f,\n` +
      `        children = listOf(\n            ${children}\n        ),\n` +
      `        extras = listOf(${extras}),\n` +
      `    )`;
  }).join(',\n');
  const listData = `/**
 * ${listName}：${title ? `「${title.text.trim()}」` : '页面中'}的 ${group.length} 张相似卡片，懒加载渲染。
 */
private val ${dataVar} = listOf(
${itemInit},
)`;

  // ---- item Composable ----
  // 逐卡子槽位渲染：遍历 item.children，按每张卡自身携带的几何/渲染参数还原。
  // 这样卡片间文本宽度、字号等即使不一致，也能各自精确对齐设计稿。
  const childRender = `        item.children.forEachIndexed { i, child ->
            if (child == null) return@forEachIndexed
            Box(modifier = Modifier.padding(start = child.x.dp, top = child.y.dp)) {
                if (child.res != null) {
                    Box(
                        modifier = Modifier.testTag(child.tag).size(child.w.dp, child.h.dp).clip(RoundedCornerShape(child.radius.dp)),
                    ) {
                        ImageItem(
                            parameter = ImageParameter(
                                data = child.res,
                                modifier = if (child.cropW > 0f)
                                    Modifier.wrapContentSize(unbounded = true, align = Alignment.TopStart).requiredSize(width = child.cropW.dp, height = child.cropH.dp).graphicsLayer { translationX = child.cropOffX.dp.toPx(); translationY = child.cropOffY.dp.toPx() }.clipToBounds()
                                else
                                    Modifier.size(child.w.dp, child.h.dp),
                                contentScale = ContentScale.FillBounds,
                            ),
                        )
                    }
                } else {
                    Box(
                        modifier = Modifier.testTag(child.tag).size(child.w.dp, child.h.dp),
                        contentAlignment = when (child.align) {
                            2 -> Alignment.CenterEnd
                            1 -> Alignment.Center
                            else -> Alignment.CenterStart
                        },
                    ) {
                        Text(
                            modifier = Modifier.requiredSize(width = child.w.dp, height = child.renderH.dp).graphicsLayer { translationY = child.visualOffsetY.dp.toPx() },
                            text = child.text ?: "",
                            maxLines = child.maxLines,
                            overflow = if (child.allowInkOverflow) TextOverflow.Visible else TextOverflow.Clip,
                            softWrap = !child.isNowrap,
                            style = TextStyle(
                                fontSize = child.fontSize.sp,
                                lineHeight = child.renderLineHeight.sp,
                                color = Color(child.colorArgb),
                                fontWeight = FontWeight(child.fontWeight),
                                textAlign = when (child.align) {
                                    2 -> TextAlign.Right
                                    1 -> TextAlign.Center
                                    else -> TextAlign.Start
                                },
                                platformStyle = PlatformTextStyle(includeFontPadding = child.includeFontPadding),
                            ),
                        )
                    }
                }
            }
        }
`;
  const bgRender = descriptor.cardRes
    ? `        // 卡片背景图${descriptor.bgCrop ? '（按设计裁剪几何还原）' : ''}\n` +
      `        Box(modifier = Modifier.testTag("e" + item.tag).size(item.w.dp, item.h.dp).background(Color.White, RoundedCornerShape(${cardRadius}.dp)).clip(RoundedCornerShape(${cardRadius}.dp))) {\n` +
      `            ImageItem(\n` +
      `                parameter = ImageParameter(\n` +
      `                    data = item.bgRes ?: R.mipmap.${descriptor.cardRes},\n` +
      `                    modifier = ${descriptor.bgCrop ? buildCroppedBackgroundModifier(descriptor.bgCrop) : 'Modifier.size(item.w.dp, item.h.dp)'},\n` +
      `                    contentScale = ContentScale.FillBounds,\n` +
      `                ),\n` +
      `            )\n` +
      `        }\n`
    : '';
  const extraRender = `        item.extras.forEach { extra ->
            Box(modifier = Modifier.padding(start = extra.x.dp, top = extra.y.dp)) {
                if (extra.res != null) {
                    ImageItem(
                        parameter = ImageParameter(
                            data = extra.res,
                            modifier = Modifier.testTag(extra.tag).size(extra.w.dp, extra.h.dp),
                            contentScale = ContentScale.FillBounds,
                        ),
                    )
                } else {
                    Box(
                        modifier = Modifier.testTag(extra.tag).size(extra.w.dp, extra.h.dp),
                        contentAlignment = when (extra.textAlign) {
                            2 -> Alignment.CenterEnd
                            1 -> Alignment.Center
                            else -> Alignment.CenterStart
                        },
                    ) {
                        Text(
                            modifier = Modifier.requiredSize(width = extra.w.dp, height = extra.renderH.dp),
                            text = extra.text ?: "",
                            maxLines = extra.maxLines,
                            overflow = if (extra.allowInkOverflow) TextOverflow.Visible else TextOverflow.Clip,
                            softWrap = !extra.isNowrap,
                            style = TextStyle(
                                fontSize = extra.fontSize.sp,
                                lineHeight = extra.renderLineHeight.sp,
                                color = Color(extra.colorArgb),
                                fontWeight = FontWeight(extra.fontWeight),
                                textAlign = when (extra.textAlign) {
                                    2 -> TextAlign.Right
                                    1 -> TextAlign.Center
                                    else -> TextAlign.Start
                                },
                                platformStyle = PlatformTextStyle(includeFontPadding = true),
                            ),
                        )
                    }
                }
            }
        }
`;

  const itemComposable = `/**
 * ${itemName}：${baseName} 单张卡片。数据来自 ${itemDataType}，按槽位渲染封面/文本。
 */
@Composable
private fun ${itemName}(item: ${itemDataType}) {
    Box(
        modifier = Modifier.size(item.w.dp, item.h.dp),
    ) {
${bgRender}${childRender}
${extraRender}
    }
}
`;

  // ---- Lazy 容器调用 ----
  let lazyCall = '';
  const indent = '        ';
  const viewportRuleEnabled = isRuleEnabled(ctx.ruleState, 'list-viewport-clips-and-pads');
  // 视口高度：一律取列表自身完整高度（containerRect.h），不按宿主剩余空间裁切。
  // 宿主（分区/背景卡片）常比卡片网格更矮（如"今日已读"网格底行溢出分区背景），
  // 强行裁剪会把设计稿可见的底行卡片截断。视口 = 网格完整高度即可完整显示全部卡片；
  // 开启 viewport 规则时额外补 1 个 rowGap/colGap 高度容纳末项 contentPadding，避免再被裁。
  const viewportRulePad = viewportRuleEnabled
    ? (grid.type === 'LazyVerticalGrid' || grid.type === 'LazyColumn' ? rowGap : colGap)
    : 0;
  const viewportH = r05(containerRect.h + viewportRulePad);
  const viewportClip = viewportRuleEnabled ? '.clipToBounds()' : '';
  if (grid.type === 'LazyVerticalGrid') {
    lazyCall =
      `        /**
         * ${listName}：${group.length} 张卡片按 ${grid.cols} 列网格懒加载。
         * 容器位置 (${containerRect.x}, ${containerRect.y})，尺寸 ${containerRect.w}x${containerRect.h}dp。
         */\n` +
      `        Box(modifier = Modifier.testTag("${viewportTag}").padding(start = ${relX}.dp, top = ${relY}.dp).size(${containerRect.w}.dp, ${viewportH}.dp)${viewportClip}) {\n` +
      `            LazyVerticalGrid(\n` +
      `                columns = GridCells.Fixed(${grid.cols}),\n` +
      `                modifier = Modifier.fillMaxSize(),\n` +
      `                horizontalArrangement = Arrangement.spacedBy(${colGap}.dp),\n` +
      `                verticalArrangement = Arrangement.spacedBy(${rowGap}.dp),\n` +
      (viewportRuleEnabled ? `                contentPadding = PaddingValues(bottom = ${rowGap}.dp),\n` : '') +
      `            ) {\n` +
      `                items(${dataVar}) { item ->\n` +
      `                    ${itemName}(item)\n` +
      `                }\n` +
      `            }\n` +
      `        }\n`;
  } else if (grid.type === 'LazyColumn') {
    lazyCall =
      `        /**\n` +
      `         * ${listName}：${group.length} 张卡片纵向懒加载。\n` +
      `         * 容器位置 (${containerRect.x}, ${containerRect.y})，尺寸 ${containerRect.w}x${containerRect.h}dp。\n` +
      `         */\n` +
      `        Box(modifier = Modifier.testTag("${viewportTag}").padding(start = ${relX}.dp, top = ${relY}.dp).size(${containerRect.w}.dp, ${containerRect.h}.dp)${viewportClip}) {\n` +
      `            LazyColumn(\n` +
      `                modifier = Modifier.fillMaxSize(),\n` +
      `                verticalArrangement = Arrangement.spacedBy(${rowGap}.dp),\n` +
      (viewportRuleEnabled ? `                contentPadding = PaddingValues(bottom = ${rowGap}.dp),\n` : '') +
      `            ) {\n` +
      `                items(${dataVar}) { item ->\n` +
      `                    ${itemName}(item)\n` +
      `                }\n` +
      `            }\n` +
      `        }\n`;
  } else {
    lazyCall =
      `        /**\n` +
      `         * ${listName}：${group.length} 张卡片横向懒加载。\n` +
      `         * 容器位置 (${containerRect.x}, ${containerRect.y})，尺寸 ${containerRect.w}x${containerRect.h}dp。\n` +
      `         */\n` +
      `        Box(modifier = Modifier.testTag("${viewportTag}").padding(start = ${relX}.dp, top = ${relY}.dp).size(${containerRect.w}.dp, ${containerRect.h}.dp)${viewportClip}) {\n` +
      `            LazyRow(\n` +
      `                modifier = Modifier.fillMaxSize(),\n` +
      `                horizontalArrangement = Arrangement.spacedBy(${colGap}.dp),\n` +
      (viewportRuleEnabled ? `                contentPadding = PaddingValues(end = ${colGap}.dp),\n` : '') +
      `            ) {\n` +
      `                items(${dataVar}) { item ->\n` +
      `                    ${itemName}(item)\n` +
      `                }\n` +
      `            }\n` +
      `        }\n`;
  }

  // ---- 组装 comps（ChildValue 全局共用，仅首个列表组生成，避免重复定义编译报错）----
  const comps = [];
  if (opts.emitChildValue !== false) comps.push(childValueClass);
  comps.push(extraValueClass, itemDataClass, listData, itemComposable);

  return { callCode: lazyCall, comps, excluded };
}

// 收集所有元素级 Composable 的容器（全局，生成时依次填充）
const comps = [];

// 渲染兄弟叶子为流式布局（Column 或 Row）：仅用于「全部为叶子」且对齐、不重叠的组。
// 叶子直接内联（带 testTag），保证几何精确；组内每个叶子都很廉价，不会撑爆方法。
function renderFlowGroup(type, children, parentRect, ctx) {
  if (children.length < 2) return null;
  const rects = children.map((c) => c.e.rect);
  let common, sorted;
  if (type === 'Column') {
    const xs = rects.map((r) => r.x);
    if (Math.max(...xs) - Math.min(...xs) > 2) return null; // 未左对齐
    common = Math.min(...xs);
    sorted = [...children].sort((a, b) => a.e.rect.y - b.e.rect.y);
    for (let i = 0; i < sorted.length - 1; i++) {
      if (sorted[i].e.rect.y + sorted[i].e.rect.h > sorted[i + 1].e.rect.y + 1) return null; // 纵向重叠
    }
  } else {
    const ys = rects.map((r) => r.y);
    if (Math.max(...ys) - Math.min(...ys) > 2) return null; // 未顶对齐
    common = Math.min(...ys);
    sorted = [...children].sort((a, b) => a.e.rect.x - b.e.rect.x);
    for (let i = 0; i < sorted.length - 1; i++) {
      if (sorted[i].e.rect.x + sorted[i].e.rect.w > sorted[i + 1].e.rect.x + 1) return null; // 横向重叠
    }
  }
  const isCol = type === 'Column';
  const gapMod = `Spacer(Modifier.${isCol ? 'height' : 'width'}(`;
  const line = [];
  let prev = null;
  for (const c of sorted) {
    if (prev) {
      const gap = isCol ? c.e.rect.y - prev.y - prev.h : c.e.rect.x - prev.x - prev.w;
      line.push(`                ${gapMod}${gap}.dp))`);
    }
    const content = genContent(c.e, ctx, 8);
    if (content) line.push(content);
    prev = c.e.rect;
  }
  const padStr = isCol
    ? `Modifier.padding(start = ${Math.max(0, common - parentRect.x)}.dp, top = ${Math.max(0, sorted[0].e.rect.y - parentRect.y)}.dp)`
    : `Modifier.padding(start = ${Math.max(0, sorted[0].e.rect.x - parentRect.x)}.dp, top = ${Math.max(0, common - parentRect.y)}.dp)`;
  return (
    `                ${type}(\n` +
    `                    modifier = ${padStr},\n` +
    `                ) {\n` +
    line.join('\n') +
    `\n                }\n`
  );
}

// CJK 墨迹垂直补偿（dp）：
// Compose 渲染 CJK 字形时，墨迹相对浏览器会有稳定的垂直偏差；
// 保留平台字体安全 padding 后，仅对内部绘制层补偿剩余的视觉基线差：
//   - 首字符为中文（纯中文标题，如 "阅读量/磨耳朵/达标/查看详情"）→ 4dp（实测偏移 8px）
//   - 否则（含 CJK 的混合/单位文本，如 "1000词"、"30分钟"、"Day 2…"）→ 3.5dp（实测偏移 7px）
function cjkTopComp(text) {
  if (!text || !/[\u4e00-\u9fff]/.test(text)) return 0;
  const first = String(text).replace(/^\s+/, '')[0];
  return /[\u4e00-\u9fff]/.test(first) ? 4 : 3.5;
}

// 保证生成的方法名全局唯一（见名知意的推断可能产生重名，追加序号避免编译冲突）。
function uniqueComposeName(base, ctx) {
  ctx.usedNames = ctx.usedNames || new Set();
  let name = base;
  let i = 2;
  while (ctx.usedNames.has(name)) name = `${base}${i++}`;
  ctx.usedNames.add(name);
  return name;
}

// 生成一个节点的元素级 Composable（每个元素一个函数，避免 MethodTooLarge）。
// 采用嵌套层级渲染：当前节点内容 + 背景层（同 rect 兄弟降级而来） + 子组件（相对父容器定位）
// + 列表注入（当前节点是列表宿主时，在其内容与子节点之后追加 Lazy 容器）。
// 返回调用表达式；体注册到 comps。
function genNode(node, parentRect, ctx) {
  const e = node.e;
  // 相对父容器坐标，保留 0.5dp 精度（r05 已保证非负），避免累计取整导致坐标漂移。
  const relX = r05(e.rect.x - parentRect.x);
  // 坐标严格按设计稿 rect（dp）放置，不做任何 CJK 墨迹补偿。
  // 曾尝试对 CJK 文本向上扣 3.5~4dp，但同一行内"数字(0补偿)/单位(3.5补偿)"、以及
  // "文本标签(补偿)/徽章图片(0补偿)"会被补偿量拉开，破坏行内基准线对齐（用户多次反馈
  // "2620 与 1000词 不对齐、阅读量与达标不对齐"）。平台字体安全 padding 负责避免上下墨迹
  // 被裁切；这里只按设计稿语义框精确落位，视觉补偿由内部 Text 绘制层处理。
  const relY = r05(e.rect.y - parentRect.y);
  const name = uniqueComposeName(inferComponentName(e, ctx.parentContext || '', ctx.elements || []), ctx);

  const content = genContent(e, ctx, 8);
  const children = node.children;
  const bodyLines = [];
  if (content) bodyLines.push(content);

  // 背景层（mergeSameRectChildren 降级而来的同 rect 兄弟背景）随容器一起渲染，保持 z 序。
  // 若不随主容器嵌套渲染，后画的兄弟背景会盖住嵌套进去的列表。
  if (node.layers && node.layers.length > 0) {
    for (const layer of node.layers) {
      const lc = genContent(layer, ctx, 8);
      if (lc) bodyLines.push(lc);
    }
  }

  // 列表注入：当前节点是列表宿主时，在内容与子节点之后追加 Lazy 容器（卡片盖在分区背景之上）
  const listCall = node.listCall || (ctx.hostListCall ? ctx.hostListCall.get(e.domIndex) : null);

  // 子节点：全部为叶子且对齐 → 内联 Column/Row；否则每个子节点独立 Composable 调用
  if (children.length > 0) {
    const allLeaves = children.every((c) => c.children.length === 0);
    if (allLeaves) {
      const col = renderFlowGroup('Column', children, e.rect, ctx);
      if (col) bodyLines.push(col);
      else {
        const row = renderFlowGroup('Row', children, e.rect, ctx);
        if (row) bodyLines.push(row);
        else children.forEach((c) => bodyLines.push(genNode(c, e.rect, ctx)));
      }
    } else {
      children.forEach((c) => bodyLines.push(genNode(c, e.rect, ctx)));
    }
  }

  // 列表最后绘制：z 序高于分区内其他内容，避免被分区背景或标题覆盖
  if (listCall) bodyLines.push(listCall);

  if (bodyLines.length === 0) return ''; // 无可视内容（扁平化后一般不会发生）

  // 列表宿主容器：锁定自身尺寸，但不裁剪溢出内容。
  // 设计稿中分区背景（如"今日已读"e16）常常比卡片网格更短，底行卡片本就超出分区边界，
  // 结构校验按各卡片完整设计高比对（如 e17 高 169px）。若在宿主上加 clipToBounds，
  // 会把底行卡片在分区底边处裁短（169px→118px），导致卡片显示不全。
  // 列表自身的 Lazy 容器视口已 clipToBounds 并按完整网格高铺满，足以容纳并裁剪列表，
  // 因此宿主只锁定尺寸即可，不必重复裁剪。
  const hostModifier = listCall
    ? `.size(${e.rect.w}.dp, ${e.rect.h}.dp)` +
      (ctx.hostSemanticTags && ctx.hostSemanticTags.get(e.domIndex)
        ? `.testTag("${ctx.hostSemanticTags.get(e.domIndex)}")`
        : '')
    : '';

  // 方法注释：根据元素信息生成描述性注释
  const descParts = [];
  if (e.text) descParts.push(`文本：${e.text.trim().replace(/\s+/g, ' ')}`);
  if (e.className) descParts.push(`类名：${e.className}`);
  if (e.role) descParts.push(`角色：${e.role}`);
  const comment = `/**\n * ${descParts.join('；')}\n * 位置：(x=${relX}, y=${relY}) 相对父容器，尺寸：${e.rect.w}x${e.rect.h}dp\n */`;
  comps.push(
    `${comment}\n` +
      `@Composable\n` +
      `private fun ${name}() {\n` +
      `    Box(\n` +
      `        modifier = Modifier.padding(start = ${relX}.dp, top = ${relY}.dp)${hostModifier},\n` +
      `    ) {\n` +
      bodyLines.join('\n') +
      `\n    }\n}\n`
  );
  return `            ${name}()`;
}

// 高保真基线：每个视觉元素直接相对根容器定位，不做包含树、去重或 Row/Column 推断。
// 生成命名见名知意（根据元素文本/className 推断）+ 每个方法带注释。
function genBaselineNode(element, ctx) {
  const content = genContent(element, ctx, 8);
  if (!content) return '';
  const name = uniqueComposeName(inferComponentName(element, ctx.parentContext || '', ctx.elements || []), ctx);
  // 方法注释：根据元素信息生成描述性注释
  const descParts = [];
  if (element.text) descParts.push(`文本：${element.text.trim().replace(/\s+/g, ' ')}`);
  if (element.className) descParts.push(`类名：${element.className}`);
  if (element.role) descParts.push(`角色：${element.role}`);
  if (element.imgSrc) descParts.push(`图片：${path.basename(element.imgSrc)}`);
  else if (element.style && element.style.bgImage) {
    const m = element.style.bgImage.match(/url\("?([^")]+)"?\)/);
    if (m) descParts.push(`背景图：${path.basename(m[1])}`);
  }
  const comment = `/**\n * ${descParts.join('；')}\n * 位置：(x=${element.rect.x}, y=${element.rect.y})，尺寸：${element.rect.w}x${element.rect.h}dp\n */`;
  comps.push(
    `${comment}\n` +
      `@Composable\n` +
      `private fun ${name}() {\n` +
      `    Box(\n` +
      `        modifier = Modifier.padding(start = ${element.rect.x}.dp, top = ${element.rect.y}.dp),\n` +
      `    ) {\n` +
      content +
      `\n    }\n}\n`
  );
  return `        ${name}()`;
}

function genTest1Page(semantic, imgMap, ruleState) {
  const designW = DESIGN_W;
  const designH = DESIGN_H;
  // 先去重：normalize.js 会因 DOM 嵌套产生同 rect + 同内容签名的重复元素（如 e36/e40 同标题、
  // e35/e39 同封面），若不合并，列表槽位匹配与树形渲染都会出现"同一视觉被画两次"的冗余覆盖。
  // 去重只保留首个出现，domIndex 不变，校验用的 testTag 不受影响。
  let elements = deduplicate(semantic.elements);
  const ctx = { imgMap, elements, parentContext: PAGE_NAME, usedNames: new Set(), ruleState };

  // 1) 提取全屏根背景（单独 fillMaxSize 铺满）；同时识别全屏纯色根容器（.page）作为根 Box 底色，
  //    避免它被当成普通元素生成覆盖层而盖住根背景图。
  const bgIndex = elements.findIndex((e) => isFullScreenBg(e, designW, designH));
  const pageIndex = elements.findIndex((e) => isFullScreenPlainBox(e, designW, designH));
  let bgCode = '';
  let rootBgColor = null;
  let restElements = elements;
  const skipIndices = new Set();
  if (bgIndex >= 0) {
    const bg = elements[bgIndex];
    const res = resolveResName(bg, imgMap);
    if (res) {
      bgCode =
        `        // 根布局背景图：仅铺满当前设计画布\n` +
        `        ImageItem(\n` +
        `            parameter = ImageParameter(\n` +
        `                data = R.mipmap.${res},\n` +
        `                modifier = Modifier.fillMaxSize().testTag("e${bg.domIndex}"),\n` +
        `                contentScale = ContentScale.FillBounds,\n` +
        `            )\n` +
        `        )\n`;
    }
    skipIndices.add(bgIndex);
  }
  if (pageIndex >= 0) {
    rootBgColor = rgbToColor(elements[pageIndex].style.bgColor);
    skipIndices.add(pageIndex);
  }
  restElements = elements.filter((_, i) => !skipIndices.has(i));

  comps.length = 0; // 重置元素级 Composable / 数据类收集器

  // 2) 构建几何包含树：每个元素挂到"面积最小且包含它"的容器下 → 扁平化透明容器 →
  //    合并同 rect 兄弟（同一位置叠放的双背景，如"今日已读"分区 e16 + e31）。
  let roots = buildTree(restElements);
  roots = flattenTransparent(roots);
  roots = mergeSameRectChildren(roots);

  // 3) 检测相似卡片组 → 找宿主容器 → 生成数据驱动 Lazy 列表（脚本确定性生成，避免大模型跑偏）。
  //    判定标准：同区域若干卡片图片/文字结构相同、宽高差 ≤2dp → 聚成一组，
  //    用 LazyColumn/LazyRow/LazyVerticalGrid 懒加载，并嵌套进所在分区（宿主）容器。
  const cardGroups = detectCardGroups(restElements);
  console.log(`检测到 ${cardGroups.length} 个相似卡片组`);
  const excludedDomIndices = new Set();
  const hostListCall = new Map(); // 宿主 domIndex → Lazy 容器调用代码
  const hostSemanticTags = new Map(); // 宿主 domIndex → 结构回归测试标签
  let childValueEmitted = false;
  for (const group of cardGroups) {
    const host = findListHost(group, roots);
    const result = genListGroupCode(group, ctx, imgMap, {
      emitChildValue: !childValueEmitted,
      parentRect: host ? host.e.rect : null,
    });
    if (!result) continue; // 结构不一致的组回退为逐元素渲染（保留在树中）
    childValueEmitted = true;
    result.excluded.forEach((idx) => excludedDomIndices.add(idx));
    for (const c of result.comps) comps.push(c);
    if (host) {
      hostListCall.set(host.e.domIndex, result.callCode);
      const groupTitle = findTitleForGroup(group, elements);
      if (groupTitle && groupTitle.text.trim() === '今日已读') {
        hostSemanticTags.set(host.e.domIndex, 'todayReadSection');
      }
    } else {
      // 无宿主：列表作为根级合成容器追加，保证被列表包含的卡片仍被渲染
      const rect = computeListGeometry(group).containerRect;
      roots.push({
        e: { domIndex: -1, role: 'container', className: 'list', rect,
             z: Math.max(...group.map((g) => g.z || 0)) + 1, style: {}, imgSrc: null, text: null },
        children: [], layers: [], parent: null, synthetic: true,
        listCall: result.callCode,
      });
    }
  }
  ctx.hostListCall = hostListCall;
  ctx.hostSemanticTags = hostSemanticTags;

  // 4) 从树中摘除被列表包含的卡片节点；非公共槽位子元素提升为根级覆盖层
  roots = removeListCards(roots, excludedDomIndices);

  // 5) 左侧导航聚合成 LeftNavBar 合成容器（参考 ReportHomeV3Layout 的 LeftMenu 层级）
  roots = groupLeftNav(roots, designW);

  // 6) 树形嵌套渲染：根容器下的每个根节点递归生成嵌套结构的 Composable。
  //    组件按几何包含关系层层嵌套（如"今日已读"分区包含其 Lazy 列表），
  //    列表不会跑到父组件之外。
  const ROOT_RECT = { x: 0, y: 0, w: designW, h: designH };
  roots.sort((a, b) => (a.e.z || 0) - (b.e.z || 0));
  const calls = roots.map((r) => genNode(r, ROOT_RECT, ctx)).filter(Boolean);
  const callsStr = calls.join('\n');
  const sectionsCode = comps.join('\n');
  const responsivePageRoot = buildResponsivePageRoot({
    pageName: PAGE_NAME,
    designWidthDp: DESIGN_W,
    designHeightDp: DESIGN_H,
    rootBackgroundColor: rootBgColor,
    backgroundCode: bgCode,
    contentCode: callsStr,
  });

  return `package ${KOTLIN_PACKAGE}

import android.annotation.SuppressLint
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyItemScope
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.sp
import kotlin.math.min
${IMAGE_IMPORTS}
${R_IMPORT}

/**
 * 由当前设计稿（逻辑画布 ${DESIGN_W}x${DESIGN_H}dp）经 code-html-compose 高保真基线生成的 Compose 布局。
 * 布局策略：
 *  - 以语义树为真源，先逐元素生成可验证基线；基线通过后才允许单独做语义化重构。
 *  - 像素级验收尺寸取自当前 semantic.json；运行时按窗口宽高较小比例居中适配，不拉伸、不裁切。
 *  - 元素定位不使用 offset；所有视觉元素直接相对根 Box 使用 padding 定位并保留 0.5dp 精度。
 *  - 每个视觉元素带 Modifier.testTag("e<domIndex>")，供 compose-validate.js 完整边界校验。
 *  - 根背景图只铺满设计画布；不同宽高比窗口允许出现居中留白。
 */
${responsivePageRoot}

/**
 * FittedSingleLineText：单行文本按设计稿宽度等比缩放（nowrap 数字/短标签用）。
 * 通过 TextMeasurer 实测文本宽度，超出 maxWidth 时按比例缩放，避免横向溢出设计框。
 */
@OptIn(ExperimentalTextApi::class)
@Composable
private fun FittedSingleLineText(
    modifier: Modifier,
    maxWidth: Dp,
    contentAlignment: Alignment,
    horizontalOrigin: Float,
    text: String,
    maxLines: Int,
    overflow: TextOverflow,
    softWrap: Boolean,
    style: TextStyle,
) {
    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()
    val measured = textMeasurer.measure(
        text = AnnotatedString(text),
        style = style,
        maxLines = maxLines,
        overflow = overflow,
        softWrap = softWrap,
    )
    val targetWidthPx = with(density) { maxWidth.toPx() }
    val scale = if (measured.size.width > targetWidthPx && measured.size.width > 0) {
        targetWidthPx / measured.size.width
    } else {
        1f
    }
    val measuredWidth = with(density) { measured.size.width.toDp() }
    Box(modifier = modifier, contentAlignment = contentAlignment) {
        Text(
            modifier = Modifier
                .requiredWidth(measuredWidth)
                .graphicsLayer {
                    scaleX = scale
                    transformOrigin = androidx.compose.ui.graphics.TransformOrigin(horizontalOrigin, 0.5f)
                },
            text = text,
            maxLines = maxLines,
            overflow = overflow,
            softWrap = softWrap,
            style = style,
        )
    }
}
${sectionsCode}
`;
}

// ---------------- main ----------------
function main() {
  try {
    ensureLandscapeActivity(PROJECT_ROOT, COMPOSE_ACTIVITY);
  } catch (error) {
    console.error(`\n${error.message}`);
    process.exit(1);
  }

  if (!fs.existsSync(SEMANTIC)) {
    console.error(`语义树不存在：${SEMANTIC}。请先运行 normalize.js 生成语义树。`);
    process.exit(1);
  }
  let semantic = JSON.parse(fs.readFileSync(SEMANTIC, 'utf8'));
  console.log(`设计稿：${semantic.designW}x${semantic.designH}，元素 ${semantic.count} 个`);

  const experienceState = loadExperienceState(EXPERIENCE_RULES);
  const designDir = SOURCE_DIR;
  const referenceFilter = isRuleEnabled(experienceState, 'reject-reference-unsupported-images')
    ? filterReferenceUnsupportedImages(semantic, {
        designDir,
        referencePath: REFERENCE_PNG,
        normalizedPath: path.join(TOOL_OUTPUT_DIR, 'normalized.png'),
      })
    : { semantic, filtered: [], skipped: true };
  semantic = referenceFilter.semantic;
  if (referenceFilter.filtered.length) {
    console.log(`  已过滤 ${referenceFilter.filtered.length} 个设计稿无视觉证据的图片节点：` +
      referenceFilter.filtered.map((item) => `e${item.domIndex}`).join(', '));
    recordExperienceEvent(EXPERIENCE_RULES, {
      type: 'rule-applied',
      ruleIds: ['reject-reference-unsupported-images'],
      details: referenceFilter.filtered,
    });
  }

  // 设计稿逻辑尺寸（dp）动态取自语义树，适配不同尺寸的设计稿（如 1600x720 → 800x360dp）。
  DESIGN_W = semantic.designW * DP_PER_PX;
  DESIGN_H = semantic.designH * DP_PER_PX;

  // 像素 → 逻辑 dp 换算，保留 0.5dp 精度，避免字号、行高与坐标累计漂移。
  semantic = convertSemanticToDp(semantic, DP_PER_PX);

  // 先去重，再计算可观测元素：normalize.js 会因 DOM 嵌套产生同 rect+同内容签名的重复元素，
  // 去重后这些元素不会渲染、也没有 testTag，若仍计入结构校验分母会误报 not-found。
  // 去重必须在 main() 这里做，才能让生成报告与 genTest1Page 内部实际渲染保持一致。
  const dedupElements = deduplicate(semantic.elements);
  semantic = { ...semantic, elements: dedupElements };

  // 排除全屏纯色根容器（.page 底色）：它由根 Box 的 background 承载、不生成独立 testTag，
  // 必须与 genTest1Page 内部实际渲染一致，否则结构校验会把 e0 误判为 not-found。
  const renderableElements = dedupElements.filter(
    (e) => !isFullScreenPlainBox(e, DESIGN_W, DESIGN_H)
  );

  const repeatedTextGroups = isRuleEnabled(experienceState, 'uniform-repeated-items-become-list')
    ? detectRepeatedTextGroups(renderableElements)
    : [];
  if (repeatedTextGroups.length > 0) {
    console.log(`检测到 ${repeatedTextGroups.length} 组样式统一的重复文本 item，标记为列表候选：` +
      repeatedTextGroups.map((group) => group.items.map((item) => `e${item.domIndex}`).join('/')).join('、'));
  }
  const observable = findObservableElements(renderableElements);
  fs.writeFileSync(GENERATION_REPORT, JSON.stringify({
    mode: 'pixel-baseline',
    rules: {
      active: Object.keys(experienceState.rules).filter((id) => experienceState.rules[id].enabled),
      referenceFiltered: referenceFilter.filtered,
      referenceFilterSkipped: referenceFilter.skipped,
      repeatedTextGroups: repeatedTextGroups.map((group) => ({
        kind: group.kind,
        axis: group.axis,
        domIndices: group.items.map((item) => item.domIndex),
        texts: group.items.map((item) => item.text),
      })),
    },
    sourceElementCount: dedupElements.length,
    generatedElementCount: dedupElements.length,
    observableElementCount: observable.observable.length,
    observableDomIndices: observable.observable.map((element) => element.domIndex),
    occluded: observable.occluded,
  }, null, 2));

  // 1) 复制图片到 res
  console.log('步骤 9.1：复制设计图到 app res 目录');
  const copied = copyImages(semantic);
  console.log(`  已复制 ${copied.length} 张图片 → ${RES_IMG_DIR}`);
  const imgMap = new Map(copied.map((c) => [c.file, c.resName]));

  // 2) 生成 Kotlin
  console.log(`步骤 9.2：生成 ${PAGE_NAME}.kt`);
  const code = genTest1Page(semantic, imgMap, experienceState);
  fs.mkdirSync(path.dirname(TARGET_KT), { recursive: true });
  fs.writeFileSync(TARGET_KT, code.replace(/\n+$/, '\n'));
  console.log(`  已写入 → ${TARGET_KT}`);
  console.log('完成。');
}

main();
