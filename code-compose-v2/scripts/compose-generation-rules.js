/**
 * Compose 生成阶段的确定性规则。
 *
 * 这里放布局不变量和设计稿可见性判断，避免由模型在生成 Kotlin 时临时决定。
 */
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');

const DEFAULT_RULE_IDS = [
  'uniform-list-card-geometry',
  'list-viewport-clips-and-pads',
  'uniform-repeated-items-become-list',
  'card-exclusive-slots-stay-in-item',
  'reject-reference-unsupported-images',
];

function roundToHalf(value) {
  return Math.round(value * 2) / 2;
}

function average(values, fallback = 0) {
  if (!values.length) return fallback;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

/** 将设计稿中略有 1px 差异的重复卡片归一为同一尺寸。 */
function normalizeListGeometry(group, baseGeometry, grid) {
  const itemW = roundToHalf(average(group.map((item) => item.rect.w), group[0]?.rect.w || 0));
  const itemH = roundToHalf(average(group.map((item) => item.rect.h), group[0]?.rect.h || 0));
  const colGap = roundToHalf(baseGeometry.colGap);
  const rowGap = roundToHalf(baseGeometry.rowGap);
  const cols = Math.max(1, grid.cols || group.length);
  const rows = Math.max(1, grid.rows || Math.ceil(group.length / cols));

  return {
    itemW,
    itemH,
    colGap,
    rowGap,
    containerRect: {
      x: baseGeometry.containerRect.x,
      y: baseGeometry.containerRect.y,
      w: roundToHalf(itemW * cols + colGap * Math.max(0, cols - 1)),
      h: roundToHalf(itemH * rows + rowGap * Math.max(0, rows - 1)),
    },
  };
}

function containsRect(parent, child) {
  return parent.x <= child.x + 0.01 &&
    parent.y <= child.y + 0.01 &&
    parent.x + parent.w >= child.x + child.w - 0.01 &&
    parent.y + parent.h >= child.y + child.h - 0.01;
}

/**
 * 提取只属于某张卡片的槽位。它们必须进入 item 数据，不能回到根节点变成 overlay。
 */
function collectExclusiveSlots(group, slotMatches, elements, extractCardSlots) {
  const commonDomIndices = new Set();
  for (const row of slotMatches) {
    for (const element of row) {
      if (element) commonDomIndices.add(element.domIndex);
    }
  }

  return group.map((card) => {
    const candidates = extractCardSlots(card, elements).filter(
      (element) => !commonDomIndices.has(element.domIndex),
    );
    return candidates.filter((element, index) => {
      // 同一视觉节点可能因 DOM 嵌套重复出现，只保留一次。
      return candidates.findIndex((candidate) =>
        candidate.domIndex !== element.domIndex &&
        candidate.role === element.role &&
        containsRect(candidate.rect, element.rect) &&
        candidate.rect.w * candidate.rect.h >= element.rect.w * element.rect.h
      ) === -1 || candidates.findIndex((candidate) => candidate.domIndex === element.domIndex) === index;
    });
  });
}

function resolveImagePath(imgSrc, designDir) {
  if (!imgSrc) return null;
  const value = String(imgSrc).replace(/^file:\/\//, '');
  if (path.isAbsolute(value)) return value;
  return path.resolve(designDir, value);
}

function referencePixelSupport(element, source, reference, normalized) {
  const rect = element.rect;
  let opaque = 0;
  let supported = 0;
  for (let y = 0; y < Math.ceil(rect.h); y++) {
    for (let x = 0; x < Math.ceil(rect.w); x++) {
      const sx = Math.min(source.width - 1, Math.floor((x / Math.max(1, rect.w)) * source.width));
      const sy = Math.min(source.height - 1, Math.floor((y / Math.max(1, rect.h)) * source.height));
      const si = (sy * source.width + sx) * 4;
      const alpha = source.data[si + 3] / 255;
      if (alpha < 0.8) continue;
      opaque++;
      const rx = Math.min(reference.width - 1, Math.max(0, Math.floor(rect.x + x)));
      const ry = Math.min(reference.height - 1, Math.max(0, Math.floor(rect.y + y)));
      const ri = (ry * reference.width + rx) * 4;
      const distance = Math.hypot(
        source.data[si] - reference.data[ri],
        source.data[si + 1] - reference.data[ri + 1],
        source.data[si + 2] - reference.data[ri + 2],
      );
      if (distance <= 35) supported++;
    }
  }
  let referenceRenderDistance = 0;
  if (normalized) {
    let distance = 0;
    const width = Math.ceil(rect.w);
    const height = Math.ceil(rect.h);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const rx = Math.min(reference.width - 1, Math.max(0, Math.floor(rect.x + x)));
        const ry = Math.min(reference.height - 1, Math.max(0, Math.floor(rect.y + y)));
        const ri = (ry * reference.width + rx) * 4;
        const ni = (Math.min(normalized.height - 1, ry) * normalized.width + Math.min(normalized.width - 1, rx)) * 4;
        distance += Math.hypot(
          reference.data[ri] - normalized.data[ni],
          reference.data[ri + 1] - normalized.data[ni + 1],
          reference.data[ri + 2] - normalized.data[ni + 2],
        ) / Math.sqrt(255 * 255 * 3);
      }
    }
    referenceRenderDistance = distance / Math.max(1, width * height);
  }
  return {
    opaquePixels: opaque,
    sourceCoverage: opaque / Math.max(1, Math.ceil(rect.w) * Math.ceil(rect.h)),
    supportRate: supported / Math.max(1, opaque),
    referenceRenderDistance,
  };
}

/**
 * 过滤语义树中没有原始设计稿视觉证据的稀疏图片节点。
 * 重点防止透明小箭头、指示器等资源被误当成页面组件生成。
 */
function filterReferenceUnsupportedImages(semantic, { designDir, referencePath, normalizedPath }) {
  if (!referencePath || !fs.existsSync(referencePath)) {
    return { semantic, filtered: [], skipped: true };
  }

  const reference = PNG.sync.read(fs.readFileSync(referencePath));
  const normalized = normalizedPath && fs.existsSync(normalizedPath)
    ? PNG.sync.read(fs.readFileSync(normalizedPath))
    : null;
  const filtered = [];
  const kept = semantic.elements.filter((element) => {
    if (element.role !== 'image' || !element.imgSrc) return true;
    const imagePath = resolveImagePath(element.imgSrc, designDir);
    if (!imagePath || !fs.existsSync(imagePath)) return true;
    const source = PNG.sync.read(fs.readFileSync(imagePath));
    const evidence = referencePixelSupport(element, source, reference, normalized);
    const smallIndependentImage = element.rect.w * element.rect.h <= 1200;
    const sparseUnsupportedByReference =
      smallIndependentImage &&
      evidence.sourceCoverage < 0.1 &&
      evidence.referenceRenderDistance > 0.15;
    const unsupportedByReference = sparseUnsupportedByReference;
    if (!unsupportedByReference) return true;
    filtered.push({
      domIndex: element.domIndex,
      role: element.role,
      imgSrc: element.imgSrc,
      evidence,
      reason: '小型图片区域与 original.png 的视觉差异超过阈值',
    });
    return false;
  });

  return {
    semantic: { ...semantic, elements: kept, count: kept.length },
    filtered,
    skipped: false,
  };
}

function defaultExperienceState() {
  return {
    version: 1,
    rules: Object.fromEntries(DEFAULT_RULE_IDS.map((id) => [id, { enabled: true, hits: 0 }])),
    events: [],
  };
}

function loadExperienceState(filePath) {
  if (!fs.existsSync(filePath)) return defaultExperienceState();
  try {
    const state = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const defaults = defaultExperienceState();
    return {
      ...defaults,
      ...state,
      rules: { ...defaults.rules, ...(state.rules || {}) },
      events: Array.isArray(state.events) ? state.events : [],
    };
  } catch (error) {
    console.warn(`经验规则文件损坏，将恢复默认规则：${filePath}`);
    return defaultExperienceState();
  }
}

function isRuleEnabled(state, id) {
  return !state || !state.rules || !state.rules[id] || state.rules[id].enabled !== false;
}

function saveExperienceState(filePath, state) {
  fs.writeFileSync(filePath, JSON.stringify(state, null, 2) + '\n');
}

function recordExperienceEvent(filePath, event) {
  const state = loadExperienceState(filePath);
  const ids = event.ruleIds || [];
  for (const id of ids) {
    if (!state.rules[id]) state.rules[id] = { enabled: true, hits: 0 };
    state.rules[id].hits += 1;
  }
  state.events.push({ ...event, recordedAt: new Date().toISOString() });
  state.events = state.events.slice(-100);
  saveExperienceState(filePath, state);
  return state;
}

module.exports = {
  DEFAULT_RULE_IDS,
  collectExclusiveSlots,
  filterReferenceUnsupportedImages,
  isRuleEnabled,
  loadExperienceState,
  normalizeListGeometry,
  recordExperienceEvent,
  roundToHalf,
  saveExperienceState,
};
