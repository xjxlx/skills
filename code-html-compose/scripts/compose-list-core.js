/**
 * code-html-compose 列表检测与数据模型（纯函数，无渲染依赖，可单测）。
 *
 * 目的：从语义树中识别"结构相似、尺寸相近（|Δw|≤2dp、|Δh|≤2dp）"的重复卡片，
 * 把它们聚成列表组，并判定懒加载类型（LazyRow / LazyColumn / LazyVerticalGrid），
 * 同时提取每个卡片内的子元素（封面图、文本等）作为列表项数据源。
 *
 * 这样 html-to-compose.js 就能用数据驱动的 item Composable + Lazy 容器来构建列表，
 * 而不是逐卡生成 N 份几乎相同的硬编码 Composable。
 */

// 两个卡片尺寸是否相似（语义树单位为设计稿 px；允许 1dp/2px 内的栅格误差）
function sizeSimilar(a, b) {
  return Math.abs(a.rect.w - b.rect.w) <= 2 && Math.abs(a.rect.h - b.rect.h) <= 2;
}

/**
 * 按卡片外框判断列表几何，不把尾部被视口裁切的卡片当成尺寸异常。
 *
 * fullItems 是有足够可见宽度的完整卡片；clippedTailItems 是高度、轴向和位置
 * 连续，但宽度被右侧视口裁掉的尾项。列表判定只要求至少 3 个完整卡片的外框
 * 宽高在容差内，卡片内部的标题、按钮、锁定图标等状态差异不参与几何判定。
 */
function summarizeListGeometry(group, tolerancePx = 2) {
  if (!Array.isArray(group) || group.length < 3) {
    return { isList: false, fullItems: [], clippedTailItems: [] };
  }
  const fullItems = group.filter((item) => item?.rect && item.rect.w >= 60 && item.rect.h >= 60);
  if (fullItems.length < 3) {
    return { isList: false, fullItems, clippedTailItems: [] };
  }

  const widths = fullItems.map((item) => item.rect.w);
  const heights = fullItems.map((item) => item.rect.h);
  const widthRange = Math.max(...widths) - Math.min(...widths);
  const heightRange = Math.max(...heights) - Math.min(...heights);
  const yRange = Math.max(...fullItems.map((item) => item.rect.y)) - Math.min(...fullItems.map((item) => item.rect.y));
  const xRange = Math.max(...fullItems.map((item) => item.rect.x)) - Math.min(...fullItems.map((item) => item.rect.x));
  const axis = xRange >= yRange ? 'horizontal' : 'vertical';
  const ordered = [...fullItems].sort((a, b) => (
    axis === 'horizontal' ? a.rect.x - b.rect.x : a.rect.y - b.rect.y
  ));
  const base = ordered[ordered.length - 1];
  const clippedTailItems = group.filter((item) => {
    if (fullItems.includes(item) || !item?.rect) return false;
    const sameHeight = Math.abs(item.rect.h - base.rect.h) <= tolerancePx;
    const afterBase = axis === 'horizontal'
      ? item.rect.x >= base.rect.x + base.rect.w - tolerancePx
      : item.rect.y >= base.rect.y + base.rect.h - tolerancePx;
    return sameHeight && afterBase;
  });

  return {
    isList: widthRange <= tolerancePx && heightRange <= tolerancePx,
    axis,
    fullItems,
    clippedTailItems,
    widthRange,
    heightRange,
  };
}

// 是否"卡片级"元素：面积足够大、带背景图/图片
function isCardLike(e) {
  if (!e || !e.rect) return false;
  if (e.rect.w < 60 || e.rect.h < 60) return false;
  return Boolean(e.imgSrc || (e.style && e.style.bgImage));
}

// 两个元素是否可视为同一列表的卡片：
// 尺寸相似 + 角色相同 + 是否带图一致（内容结构近似）
function isSimilarCard(a, b) {
  if (!sizeSimilar(a, b)) return false;
  if (a.role !== b.role) return false;
  const aImg = Boolean(a.imgSrc || (a.style && a.style.bgImage));
  const bImg = Boolean(b.imgSrc || (b.style && b.style.bgImage));
  return aImg === bImg;
}

// 严格包含：o 完全落在 e 内且面积严格更小（排除同 rect 的重复元素，避免递归死循环）
function isStrictlyInside(o, e) {
  return isContainedIn(o, e) && (o.rect.w * o.rect.h) < (e.rect.w * e.rect.h) - 0.01;
}

// 是否"卡片级"元素：面积足够大、带背景图/图片，或是包含封面图的有色卡片容器。
// 容器守卫：若它包含 ≥2 个其它卡片级元素，则它是区块容器（如整段卡片背景），
// 不应被当成列表卡片，否则会把标题、子卡片全部吞进列表导致布局错乱。
function isCardLike(e, elements) {
  if (!e || !e.rect) return false;
  if (e.rect.w < 60 || e.rect.h < 60) return false;
  const hasImage = Boolean(e.imgSrc || (e.style && e.style.bgImage));
  // 蓝湖导出经常把卡片背景、封面和文字导出成同级节点：外框自身没有 imgSrc，
  // 但它有背景色/圆角，且空间上包住一张封面图。这类外框才是列表 item，
  // 不能只把内部封面图当成 item，否则公共文本槽位会被误判为缺失并回退成逐卡硬编码。
  const hasStyledCardSurface = Boolean(
    e.style && e.style.bgColor && e.style.borderRadius && elements &&
    elements.some((o) =>
      o !== e && isStrictlyInside(o, e) &&
      Boolean(o.imgSrc || (o.style && o.style.bgImage)) &&
      o.rect.w >= 60 && o.rect.h >= 60,
    ),
  );
  if (!hasImage && !hasStyledCardSurface) return false;
  if (elements) {
    // 容器守卫：统计 e 内含有的卡片级子元素数量，≥2 判为区块容器。
    // 注意：DOM 嵌套会把同一视觉封面生成两份同 rect 的重复元素（如 e18+e21），
    // 必须按位置去重后再计数，否则"一张卡片 + 一个封面"会被误判为容器而漏检成列表。
    let containedCards = 0;
    const seenRects = new Set();
    for (const o of elements) {
      if (o === e || o.domIndex === e.domIndex) continue;
      if (!isStrictlyInside(o, e) || !isCardLike(o, elements)) continue;
      const rk = `${Math.round(o.rect.x)},${Math.round(o.rect.y)},${Math.round(o.rect.w)},${Math.round(o.rect.h)}`;
      if (seenRects.has(rk)) continue;
      seenRects.add(rk);
      containedCards++;
      if (containedCards >= 2) return false;
    }
  }
  return true;
}

// 聚类：把互相相似的卡片聚成组，返回组数组（每组 ≥2 个）。
// 子列表抑制：若某组所有卡片都严格落在另一更大组（卡片组）的卡片内，
// 说明它是大卡片内部的子元素（如"今日已读"卡片的封面图自身也带背景图，会被判定为卡片），
// 应并入大列表项作为槽位，而不是独立成列表，否则会造成卡片内容与封面被渲染两次。
function detectCardGroups(elements) {
  const cards = elements.filter((e) => isCardLike(e, elements));
  const groups = [];
  const used = new Set();
  for (let i = 0; i < cards.length; i++) {
    if (used.has(cards[i].domIndex)) continue;
    const group = [cards[i]];
    used.add(cards[i].domIndex);
    for (let j = 0; j < cards.length; j++) {
      if (i === j || used.has(cards[j].domIndex)) continue;
      if (isSimilarCard(cards[i], cards[j])) {
        group.push(cards[j]);
        used.add(cards[j].domIndex);
      }
    }
    if (group.length >= 2) groups.push(group);
  }

  // 子列表抑制：去掉完全被更大组卡片覆盖的组（如封面图组被卡片组覆盖）
  const dropped = new Set();
  for (let i = 0; i < groups.length; i++) {
    for (let j = 0; j < groups.length; j++) {
      if (i === j) continue;
      const bigger = groups[j];
      const smaller = groups[i];
      // 大组的每张卡片面积都不小于小组 → bigger 确实更大
      const biggerAreas = bigger.every((a) => smaller.every((b) => a.rect.w * a.rect.h >= b.rect.w * b.rect.h));
      if (!biggerAreas) continue;
      // 小组所有卡片都严格落在更大组某张卡片内 → 丢弃小组
      if (smaller.every((b) => bigger.some((a) => isStrictlyInside(b, a)))) {
        dropped.add(i);
        break;
      }
    }
  }
  return groups.filter((_, i) => !dropped.has(i));
}

// 将视口右侧只露出一部分的同类卡片提升为“完整 item 数据”。
// 设计稿通常只导出可见矩形，但 Compose 列表需要完整 item 的尺寸和槽位；
// 因此保留 visibleRect 作为视口裁切依据，同时把 rect 补齐为前面完整卡片的尺寸。
function includeClippedTailItems(group, elements, tolerancePx = 2) {
  if (!Array.isArray(group) || !Array.isArray(elements) || group.length < 3) return group;
  const fullItems = group.filter((item) => item?.rect && item.rect.w >= 60 && item.rect.h >= 60);
  if (fullItems.length < 3) return group;

  const xRange = Math.max(...fullItems.map((item) => item.rect.x)) - Math.min(...fullItems.map((item) => item.rect.x));
  const yRange = Math.max(...fullItems.map((item) => item.rect.y)) - Math.min(...fullItems.map((item) => item.rect.y));
  const axis = xRange >= yRange ? 'horizontal' : 'vertical';
  const ordered = [...fullItems].sort((a, b) => (
    axis === 'horizontal' ? a.rect.x - b.rect.x : a.rect.y - b.rect.y
  ));
  const last = ordered[ordered.length - 1];
  const previous = ordered[ordered.length - 2];
  const expectedSize = axis === 'horizontal' ? last.rect.w : last.rect.h;
  const gap = axis === 'horizontal'
    ? last.rect.x - (previous.rect.x + previous.rect.w)
    : last.rect.y - (previous.rect.y + previous.rect.h);
  const expectedStart = axis === 'horizontal'
    ? last.rect.x + last.rect.w + gap
    : last.rect.y + last.rect.h + gap;
  const groupIndices = new Set(group.map((item) => item.domIndex));
  const candidates = elements.filter((item) => {
    if (!item?.rect || groupIndices.has(item.domIndex) || item.role !== last.role) return false;
    const style = item.style || {};
    const lastStyle = last.style || {};
    const sameSurface = style.bgColor === lastStyle.bgColor && style.borderRadius === lastStyle.borderRadius;
    if (!sameSurface) return false;
    const sizeAlongAxis = axis === 'horizontal' ? item.rect.w : item.rect.h;
    const crossAxisSize = axis === 'horizontal' ? item.rect.h : item.rect.w;
    const lastCrossAxisSize = axis === 'horizontal' ? last.rect.h : last.rect.w;
    const start = axis === 'horizontal' ? item.rect.x : item.rect.y;
    return sizeAlongAxis > 0 && sizeAlongAxis < expectedSize - tolerancePx &&
      Math.abs(crossAxisSize - lastCrossAxisSize) <= tolerancePx &&
      start >= expectedStart - tolerancePx * 2;
  });
  if (candidates.length === 0) return group;

  const tail = candidates.sort((a, b) => {
    const aStart = axis === 'horizontal' ? a.rect.x : a.rect.y;
    const bStart = axis === 'horizontal' ? b.rect.x : b.rect.y;
    return Math.abs(aStart - expectedStart) - Math.abs(bStart - expectedStart);
  })[0];
  const visibleRect = { ...tail.rect };
  const fullRect = {
    ...tail.rect,
    ...(axis === 'horizontal' ? { w: expectedSize } : { h: expectedSize }),
  };
  return [...group, { ...tail, rect: fullRect, visibleRect, clippedTail: true }];
}

// 判定列表布局类型与行列数：
//   - 多个行 + 多个列 → LazyVerticalGrid(列数 = cols)
//   - 多行单列 → LazyColumn
//   - 单行多列 → LazyRow
function detectGridInfo(group) {
  const ys = [...new Set(group.map((e) => Math.round(e.rect.y)))].sort((a, b) => a - b);
  const xs = [...new Set(group.map((e) => Math.round(e.rect.x)))].sort((a, b) => a - b);
  const rows = ys.length;
  const cols = xs.length;
  let type = 'LazyRow';
  if (rows > 1 && cols > 1) type = 'LazyVerticalGrid';
  else if (rows > 1) type = 'LazyColumn';
  return { type, rows, cols };
}

// 检测没有背景图、但视觉样式和尺寸完全一致的重复文本 item。
// 这类节点常见于横向序号、右侧纵向记录（如 01/02/03），不能因为不是图片卡片就逐个写死。
function detectRepeatedTextGroups(elements, excludedDomIndices = new Set()) {
  const buckets = new Map();
  for (const element of elements) {
    if (excludedDomIndices.has(element.domIndex) || element.role !== 'text' || !element.text) continue;
    const s = element.style || {};
    const key = [
      Math.round(element.rect.w),
      Math.round(element.rect.h),
      s.fontSize || '',
      s.fontWeight || '',
      s.lineHeight || '',
      s.color || '',
      s.textAlign || '',
      s.whiteSpace || '',
    ].join('|');
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(element);
  }

  const groups = [];
  for (const bucket of buckets.values()) {
    if (bucket.length < 3) continue;
    const sorted = [...bucket].sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
    const xRange = sorted[sorted.length - 1].rect.x - sorted[0].rect.x;
    const yRange = sorted[sorted.length - 1].rect.y - sorted[0].rect.y;
    const vertical = yRange >= xRange;
    const perpendicularRange = vertical
      ? Math.max(...sorted.map((element) => element.rect.x)) - Math.min(...sorted.map((element) => element.rect.x))
      : Math.max(...sorted.map((element) => element.rect.y)) - Math.min(...sorted.map((element) => element.rect.y));
    if (perpendicularRange > 16) continue;
    const axisValues = [...new Set(sorted.map((element) => Math.round(vertical ? element.rect.y : element.rect.x)))];
    if (axisValues.length !== sorted.length) continue;
    groups.push({
      kind: 'repeated-text',
      axis: vertical ? 'vertical' : 'horizontal',
      items: sorted,
    });
  }
  return groups;
}

// 计算列表容器矩形（包住所有卡片）与行列间距（dp）
function computeListGeometry(group) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const e of group) {
    minX = Math.min(minX, e.rect.x);
    minY = Math.min(minY, e.rect.y);
    maxX = Math.max(maxX, e.rect.x + e.rect.w);
    maxY = Math.max(maxY, e.rect.y + e.rect.h);
  }
  const containerRect = { x: minX, y: minY, w: maxX - minX, h: maxY - minY };

  // 行间距：同一列相邻两行卡片顶部的差值 - 卡片高度
  const rowsByY = new Map();
  for (const e of group) {
    const key = Math.round(e.rect.y);
    if (!rowsByY.has(key)) rowsByY.set(key, []);
    rowsByY.get(key).push(e);
  }
  const ys = [...rowsByY.keys()].sort((a, b) => a - b);
  let rowGap = 0;
  for (let i = 0; i < ys.length - 1; i++) {
    const topRow = rowsByY.get(ys[i]);
    const botRow = rowsByY.get(ys[i + 1]);
    // 找同一列上下相邻的两张卡，计算间距
    for (const t of topRow) {
      for (const b of botRow) {
        if (Math.abs(t.rect.x - b.rect.x) <= 2) {
          const gap = b.rect.y - (t.rect.y + t.rect.h);
          if (gap > 0) rowGap = Math.max(rowGap, gap);
        }
      }
    }
  }

  // 列间距：同一行相邻两列卡片左边界的差值 - 卡片宽度
  const colsByX = new Map();
  for (const e of group) {
    const key = Math.round(e.rect.x);
    if (!colsByX.has(key)) colsByX.set(key, []);
    colsByX.get(key).push(e);
  }
  const xs = [...colsByX.keys()].sort((a, b) => a - b);
  let colGap = 0;
  for (let i = 0; i < xs.length - 1; i++) {
    const leftCol = colsByX.get(xs[i]);
    const rightCol = colsByX.get(xs[i + 1]);
    for (const l of leftCol) {
      for (const r of rightCol) {
        if (Math.abs(l.rect.y - r.rect.y) <= 2) {
          const gap = r.rect.x - (l.rect.x + l.rect.w);
          if (gap > 0) colGap = Math.max(colGap, gap);
        }
      }
    }
  }

  return { containerRect, rowGap, colGap };
}

// 查找列表上方最近的标题文本（用于见名知意的命名）
function findTitleForGroup(group, elements) {
  const containerRect = computeListGeometry(group).containerRect;
  const candidates = elements.filter(
    (e) =>
      e.role === 'text' &&
      e.text &&
      e.rect.y + e.rect.h <= containerRect.y + 0.5 &&
      Math.abs(e.rect.x - containerRect.x) < 120,
  );
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b.rect.y + b.rect.h - (a.rect.y + a.rect.h)); // 距列表最近优先
  return candidates[0];
}

// 提取一个卡片内部的可见子元素（按相对位置 + 角色去重，DOM 嵌套会产生重复 rect）
function extractCardSlots(card, allElements) {
  const inside = allElements.filter(
    (e) =>
      e.domIndex !== card.domIndex &&
      e.rect.x >= card.rect.x - 0.01 &&
      e.rect.y >= card.rect.y - 0.01 &&
      e.rect.x + e.rect.w <= card.rect.x + card.rect.w + 0.01 &&
      e.rect.y + e.rect.h <= card.rect.y + card.rect.h + 0.01,
  );
  const seen = new Map();
  const slots = [];
  for (const e of inside) {
    const relX = Math.round(e.rect.x - card.rect.x);
    const relY = Math.round(e.rect.y - card.rect.y);
    const key = `${relX},${relY},${e.role}`;
    if (seen.has(key)) continue;
    seen.set(key, e.domIndex);
    slots.push(e);
  }
  slots.sort((a, b) => (a.z || 0) - (b.z || 0));
  return slots;
}

// 在 targetCard 中查找与模板槽位（相对位置 + 角色）匹配的子元素；找不到返回 null。
// 相对偏移必须相对模板卡片计算（relX = templateSlot.x - templateCard.x），
// 再用 targetCard 的左上角还原目标绝对坐标；若误用 targetCard 计算，会因每张卡片
// 绝对位置不同而把"绝对坐标相同"的错位元素匹配进来，导致其它卡片槽位为 null。
function matchSlot(targetCard, templateSlot, templateCard, allElements) {
  const relX = templateSlot.rect.x - templateCard.rect.x;
  const relY = templateSlot.rect.y - templateCard.rect.y;
  // 模板槽位在模板卡片内的相对偏移
  const candidates = allElements.filter(
    (e) =>
      e.domIndex !== targetCard.domIndex &&
      e.role === templateSlot.role &&
      Math.abs(e.rect.x - targetCard.rect.x - relX) <= 2 &&
      Math.abs(e.rect.y - targetCard.rect.y - relY) <= 2,
  );
  if (candidates.length === 0) return null;
  // 取包含在卡片内、最靠近模板的那个
  const inside = candidates.filter((e) => isContainedIn(e, targetCard));
  return (inside[0] || candidates[0]);
}

function isContainedIn(e, card) {
  return (
    e.rect.x >= card.rect.x - 0.01 &&
    e.rect.y >= card.rect.y - 0.01 &&
    e.rect.x + e.rect.w <= card.rect.x + card.rect.w + 0.01 &&
    e.rect.y + e.rect.h <= card.rect.y + card.rect.h + 0.01
  );
}

// 中文 → 驼峰英文（用于组件命名，覆盖本项目常见词，找不到返回 ''）
function chineseToCamel(text) {
  if (!text || typeof text !== 'string') return '';
  // 纯数字/数字开头 → 前缀 "Number"
  if (/^\d/.test(text)) return 'Number' + text.replace(/[^A-Za-z0-9]/g, '');
  const mapping = {
    '今日已读': 'TodayRead',
    '近7天阅读量达标情况': 'WeekReadingTarget',
    '学习报告': 'StudyReport',
    '阅读量': 'ReadingVolume',
    '阅读时长': 'ReadingDuration',
    '查看详情': 'ViewDetail',
    '磨耳朵': 'Listening',
    '分享卡片': 'ShareCard',
    '最近阅读平均AR': 'RecentAvgAR',
    'Quiz平均正确率': 'QuizAvgCorrectRate',
    '≥1000词达标': 'Target1000Words',
    '连续5天': 'Streak5Days',
    '共4本': 'Total4Books',
    '今天': 'Today',
    '未达标': 'NotAchieved',
    '达标': 'Achieved',
    '正确率': 'Accuracy',
    '累计学习': 'TotalLearning',
    '累计': 'Total',
    '课程': 'Course',
    '书架': 'Bookshelf',
    '报告': 'Report',
    '阅读': 'Reading',
    '今日': 'Today',
    '已读': 'Read',
    '共': 'Total',
    '卡片': 'Card',
    '列表': 'List',
    '标题': 'Title',
    '背景': 'Background',
    '图片': 'Image',
    '图标': 'Icon',
    '内容': 'Content',
    '词': 'Words',
    '分钟': 'Minutes',
    '小时': 'Hours',
    '本': 'Books',
    '近7天': 'Week7',
    '天': 'Day',
    '阅读量达标': 'ReadingTargetMet',
    '达标情况': 'TargetStatus',
    '情况': 'Status',
    '学习': 'Learning',
    '时长': 'Duration',
    '分享': 'Share',
    '最近': 'Recent',
    '平均': 'Avg',
    'AR': 'AR',
    '正确': 'Correct',
    '率': 'Rate',
    '自由读': 'FreeRead',
    '单词': 'Word',
    '连续': 'Streak',
    '量': 'Volume',
    '首': 'Book',
    '第': '',
    '章': 'Chapter',
    '节': 'Section',
    '总': 'Total',
    '统计': 'Stats',
  };
  if (mapping[text]) return mapping[text];
  // 子串匹配：按词条长度降序，让更具体的长短语优先命中
  // （如"近7天阅读量达标情况"先命中完整词条，而不是先被"天"→Day 拆碎）。
  const keys = Object.keys(mapping).sort((a, b) => b.length - a.length);
  for (const cn of keys) {
    if (text.includes(cn)) {
      const before = text.split(cn)[0];
      const after = text.split(cn).slice(1).join(cn);
      let result = mapping[cn];
      if (before && chineseToCamel(before)) result = chineseToCamel(before) + result;
      if (after && chineseToCamel(after)) result = result + chineseToCamel(after);
      return result;
    }
  }
  return '';
}

function capitalizeFirst(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// className → 组件类型后缀（用于组合见名知意的名称）
function classNameSuffix(element) {
  const className = (element.className || '').toLowerCase();
  if (className.includes('section')) return 'Section';
  if (className.includes('block')) return 'Block';
  if (className.includes('card')) return 'Card';
  if (className.includes('group')) return 'Group';
  if (className.includes('box')) return 'Box';
  if (className.includes('header')) return 'Header';
  if (className.includes('footer')) return 'Footer';
  if (className.includes('text')) return 'Text';
  if (className.includes('image') || (element.style && element.style.bgImage)) return 'Image';
  return 'Item';
}

// 从容器内部"直接包含"的文本中挑选最代表性的标题文本，用于容器语义命名。
// "直接包含" = 文本不被容器内其它非文本元素严格包含（排除深层嵌套子卡片里的文本），
// 这样统计卡整行等"无独立标题"的大容器不会误用子卡片的标题命名；
// 而带独立标题的分区（如"今日已读"）能正确取到标题。
// 选取策略：只看容器顶部区域（标题一般在顶部）内的直接文本，按 最上 → 最左 取第一个；
// 若无直接文本（大容器内全是子卡片）则返回 null，回退为通用命名。
function findRepresentativeText(element, allElements) {
  if (!allElements || !element || !element.rect) return null;
  const texts = allElements.filter(
    (e) => e !== element && e.role === 'text' && e.text && isContainedIn(e, element),
  );
  if (texts.length === 0) return null;
  // 直接包含：该文本不被容器内其它非文本元素严格包含
  const direct = texts.filter((t) => {
    const nested = allElements.some(
      (o) =>
        o !== element && o !== t &&
        o.role !== 'text' &&
        isStrictlyInside(o, element) &&
        isContainedIn(t, o),
    );
    return !nested;
  });
  if (direct.length === 0) return null; // 无直接标题（如整行统计卡的包装容器）→ 通用命名
  // 只取容器顶部区域（标题通常贴顶部）
  const topRegion = element.rect.y + element.rect.h * 0.25;
  const top = direct.filter((t) => t.rect.y <= topRegion);
  const pool = top.length ? top : direct;
  // 最上 → 最左
  pool.sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
  for (const t of pool) {
    const clean = String(t.text).trim().replace(/\s+/g, '');
    const camel = chineseToCamel(clean) || clean.replace(/[^A-Za-z0-9]+/g, '');
    if (camel) return { text: t, camel: capitalizeFirst(camel) };
  }
  return null;
}

// 查找包含该元素的最小"有代表性标题"的容器（用于兜底命名的上下文）。
// 例如"阅读量"卡内的进度条小色块没有直接标题，但其所属的"阅读量"卡有标题，
// 用该标题命名 → ReadingVolumeBox，而不是 Test1PageBoxGroup。
function findEnclosingTitledSection(element, allElements) {
  if (!allElements || !element || !element.rect) return null;
  let best = null;
  let bestArea = Infinity;
  for (const o of allElements) {
    if (o === element || o.domIndex === element.domIndex) continue;
    if (o.role === 'text') continue;
    if (!isStrictlyInside(element, o)) continue; // o 严格包含 element
    const rep = findRepresentativeText(o, allElements);
    if (!rep) continue;
    const area = o.rect.w * o.rect.h;
    if (area < bestArea) {
      bestArea = area;
      best = rep.camel;
    }
  }
  return best;
}

// 常见纯符号文本 → 语义名（用于 "/"、"·" 等无字面语义的文本）
function symbolName(text) {
  const map = {
    '/': 'Slash',
    '·': 'Dot',
    '>': 'Arrow',
    '<': 'BackArrow',
    '%': 'Percent',
    '％': 'Percent',
    '|': 'Divider',
    '&': 'And',
    '+': 'Plus',
    '=': 'Equals',
    '~': 'Tilde',
  };
  return map[text] || null;
}

// 组合语义后缀（角色前缀 + 类名后缀），避免同义重复与冗余尾缀：
//   - 角色前缀与类名后缀同义（Image+Image / Box+Box）时只保留一个，避免 CourseImageImage、ListeningBoxBox；
//   - 类名后缀为通用默认值 Item（label_1 之类无语义类名）时丢弃，避免 CourseImageItem 这类 Image+Item 冗余。
function buildSemanticSuffix(element) {
  const rolePrefix = {
    'bg-image': 'Background',
    image: 'Image',
    'card-bg': 'Card',
    'box-text': 'LabeledBox',
    box: 'Box',
    text: 'Text',
    container: 'Container',
  }[element.role] || '';
  const clsSuffix = classNameSuffix(element);
  // 类名后缀有意义且不与角色前缀同义 → 拼接；同义只保留一个；Item 视为无语义丢弃
  if (clsSuffix && clsSuffix !== 'Item') {
    if (clsSuffix === rolePrefix) return clsSuffix;
    return rolePrefix + clsSuffix;
  }
  return rolePrefix || 'Item';
}

// 根据元素信息推断组件名（见名知意）：
//   - 文本元素：用文本语义转英文驼峰（如"今日已读"→ TodayRead），不再拼接父上下文，
//     避免出现 TodayReadTest1Page 这种不可读命名。长描述文本（>12 字符）不做整句翻译，
//     用所在分区标题 + Description 兜底，避免 RecentNumber3AR2RAZ 这类乱码名。
//   - 容器/图片元素：优先用"直接包含的标题文本"语义命名（含"今日已读"的分区 → TodayReadSection）；
//     无语义标题时回退为 所在分区标题 + 语义后缀（如 阅读量卡内色块 → ReadingVolumeBox），
//     细线分隔图（宽/高 ≤3px）命名为 Divider。
function inferComponentName(element, parentContext = '', allElements = []) {
  const ctx = parentContext ? capitalizeFirst(parentContext) : '';
  // 所在分区标题（比父上下文更精确的兜底上下文）
  const sectionCtx = findEnclosingTitledSection(element, allElements);
  const effectiveCtx = sectionCtx || ctx;
  // 1) 文本元素 → 语义驼峰命名
  if (element.role === 'text' && element.text) {
    const clean = String(element.text).trim().replace(/\s+/g, '');
    // 短文本（标题/短标签）直接翻译
    const camel = chineseToCamel(clean);
    if (camel && clean.length <= 12) return camel;
    // 纯符号（斜杠/分隔符等）
    const sym = symbolName(clean);
    if (sym) return sym;
    // 纯英文/数字文本（无中文）：去符号转驼峰，如 "Shoo, Fly Guy!" → ShooFlyGuy
    const latin = clean.replace(/[^A-Za-z0-9]+/g, '');
    if (latin && !/[\u4e00-\u9fff]/.test(clean)) return capitalizeFirst(latin);
    // 长描述文本或无法翻译：用所在分区标题兜底，见名知意
    if (sectionCtx) return `${sectionCtx}Description`;
    return `${ctx || capitalizeFirst(element.role)}Text`;
  }
  // 2) 容器/图片元素：优先用直接包含的标题文本语义命名
  const rep = findRepresentativeText(element, allElements);
  if (rep) return `${rep.camel}${classNameSuffix(element)}`;
  // 2.5) 细线分隔图（宽/高 ≤3px）→ Divider
  const hasImg = Boolean(element.imgSrc || (element.style && element.style.bgImage));
  if (hasImg && (element.rect.h <= 3 || element.rect.w <= 3)) {
    return sectionCtx ? `${sectionCtx}Divider` : 'Divider';
  }
  // 3) 回退：所在分区标题 + 语义后缀（自动去重同义词，避免 CourseImageImage / ListeningBoxBox）
  const suffix = buildSemanticSuffix(element);
  return `${effectiveCtx}${suffix}` || `${capitalizeFirst(element.role)}Item`;
}

module.exports = {
  capitalizeFirst,
  chineseToCamel,
  classNameSuffix,
  computeListGeometry,
  detectCardGroups,
  detectGridInfo,
  detectRepeatedTextGroups,
  extractCardSlots,
  findRepresentativeText,
  findTitleForGroup,
  inferComponentName,
  isCardLike,
  isSimilarCard,
  matchSlot,
  summarizeListGeometry,
  sizeSimilar,
  includeClippedTailItems,
};
