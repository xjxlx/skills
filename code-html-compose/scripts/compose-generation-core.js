function scalePxValue(value, ratio) {
  if (!value || value === 'normal') return value;
  const match = String(value).match(/(-?[\d.]+)px/);
  return match ? `${Number(match[1]) * ratio}px` : value;
}

function scaleCssPxList(value, ratio) {
  if (!value) return value;
  return String(value).replace(/(-?[\d.]+)px/g, (_, number) => `${Number(number) * ratio}px`);
}

function calculateFitDensity({
  containerWidthPx,
  containerHeightPx,
  designWidthDp,
  designHeightDp,
}) {
  const values = [containerWidthPx, containerHeightPx, designWidthDp, designHeightDp];
  if (values.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error('窗口和设计稿尺寸必须是大于 0 的有限数值');
  }
  return Math.min(containerWidthPx / designWidthDp, containerHeightPx / designHeightDp);
}

function kotlinNumber(value) {
  if (!Number.isFinite(value)) throw new Error(`无法生成 Kotlin 数值：${value}`);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

function buildResponsivePageRoot({
  pageName,
  designWidthDp,
  designHeightDp,
  rootBackgroundColor,
  outerBackgroundCode = '',
  backgroundCode = '',
  contentCode = '',
}) {
  const width = kotlinNumber(designWidthDp);
  const height = kotlinNumber(designHeightDp);
  const backgroundModifier = rootBackgroundColor ? `\n                .background(${rootBackgroundColor})` : '';
  const outerBackgroundModifier = rootBackgroundColor ? `\n                .background(${rootBackgroundColor})` : '';
  return `@SuppressLint("UnusedBoxWithConstraintsScope")
@OptIn(ExperimentalComposeUiApi::class, ExperimentalTextApi::class)
@Preview(widthDp = ${Math.round(designWidthDp)}, heightDp = ${Math.round(designHeightDp)}, showBackground = true)
@Composable
fun ${pageName}(modifier: Modifier = Modifier) {
    val hostDensity = LocalDensity.current
    BoxWithConstraints(
        modifier = modifier
            .fillMaxSize()${outerBackgroundModifier},
        contentAlignment = Alignment.Center,
    ) {
${outerBackgroundCode}
        val windowWidthPx = with(hostDensity) { maxWidth.toPx() }
        val windowHeightPx = with(hostDensity) { maxHeight.toPx() }
        val fitDensity = min(
            windowWidthPx / ${width}f,
            windowHeightPx / ${height}f,
        )
        CompositionLocalProvider(
            LocalDensity provides Density(
                density = fitDensity,
                fontScale = hostDensity.fontScale,
            ),
        ) {
            Box(
                modifier = Modifier
                    .requiredSize(width = ${width}.dp, height = ${height}.dp)${backgroundModifier}
                    .semantics { testTagsAsResourceId = true },
            ) {
${backgroundCode}${contentCode}
            }
        }
    }
}`;
}

function convertSemanticToDp(semantic, ratio) {
  const converted = JSON.parse(JSON.stringify(semantic));
  converted.designW *= ratio;
  converted.designH *= ratio;
  for (const element of converted.elements) {
    element.rect = {
      x: element.rect.x * ratio,
      y: element.rect.y * ratio,
      w: element.rect.w * ratio,
      h: element.rect.h * ratio,
    };
    if (!element.style) continue;
    element.style.fontSize = scalePxValue(element.style.fontSize, ratio);
    element.style.lineHeight = scalePxValue(element.style.lineHeight, ratio);
    element.style.borderRadius = scalePxValue(element.style.borderRadius, ratio);
    element.style.bgSize = scaleCssPxList(element.style.bgSize, ratio);
    element.style.bgPosition = scaleCssPxList(element.style.bgPosition, ratio);
  }
  return converted;
}

function deriveBackgroundImageGeometry({
  boundsWidth,
  boundsHeight,
  backgroundSize,
  backgroundPosition,
}) {
  const sizeMatch = String(backgroundSize || '').trim().match(/^(-?[\d.]+)px\s+(-?[\d.]+)px$/);
  if (!sizeMatch) return null;
  const positionMatch = String(backgroundPosition || '0px 0px').trim().match(/^(-?[\d.]+)px\s+(-?[\d.]+)px$/);
  if (!positionMatch) return null;
  const geometry = {
    imageWidth: Number(sizeMatch[1]),
    imageHeight: Number(sizeMatch[2]),
    offsetX: Number(positionMatch[1]),
    offsetY: Number(positionMatch[2]),
  };
  const alreadyFillsBounds = geometry.imageWidth === boundsWidth && geometry.imageHeight === boundsHeight &&
    geometry.offsetX === 0 && geometry.offsetY === 0;
  return alreadyFillsBounds ? null : geometry;
}

function buildCroppedBackgroundModifier({ imageWidth, imageHeight, offsetX, offsetY }) {
  return 'Modifier.wrapContentSize(unbounded = true, align = Alignment.TopStart)' +
    `.requiredSize(width = ${imageWidth}.dp, height = ${imageHeight}.dp)` +
    `.graphicsLayer { translationX = ${offsetX}.dp.toPx(); translationY = ${offsetY}.dp.toPx() }`;
}

function orderVisualElements(elements) {
  return [...elements].sort((a, b) => {
    const z = (a.z || 0) - (b.z || 0);
    return z || a.domIndex - b.domIndex;
  });
}

function deriveTextRenderMetrics({ boundsHeight, fontSize, lineHeight, maxLines, isNowrap = false }) {
  const logicalHeight = boundsHeight;
  const safeLines = Math.max(1, maxLines || 1);
  // CSS 文本框常与字号等高，但 Compose 字形（尤其中文、粗体）需要额外的上下墨迹空间。
  // 只扩展内部绘制行高；外层逻辑边界仍保持设计稿尺寸，避免破坏定位与结构验收。
  const glyphSafeLineHeight = Math.ceil(fontSize * 1.2 * 2) / 2;
  const renderLineHeight = Math.max(lineHeight, glyphSafeLineHeight);
  const renderHeight = Math.max(boundsHeight, renderLineHeight * safeLines);
  return {
    logicalHeight,
    renderLineHeight,
    renderHeight,
    fitWidth: isNowrap,
    allowInkOverflow: isNowrap && safeLines === 1,
    includeFontPadding: true,
  };
}

function shouldFillRootBackground(element, designW, designH) {
  if (!element || !element.hasImage) return false;
  const { x, y, w, h } = element.rect;
  return Math.abs(x) <= 0.01 && Math.abs(y) <= 0.01 &&
    w >= designW - 0.01 && h >= designH - 0.01;
}

function deriveTextVisualOffsetY(text) {
  return /[\u3400-\u9fff]/.test(String(text || '')) ? -2.5 : 0;
}

function deriveTextPlacement(element, elements) {
  const sourceAlignment = element?.style?.textAlign || 'left';
  const rect = element?.rect;
  const fontSize = Number.parseFloat(element?.style?.fontSize || '0');
  if (!rect || !Number.isFinite(fontSize) || fontSize > 12) {
    return {
      alignment: sourceAlignment,
      visualOffsetY: deriveTextVisualOffsetY(element?.text),
      centeredContainerDomIndex: null,
    };
  }

  const centeredContainer = (elements || [])
    .filter((candidate) => {
      if (!candidate || candidate.domIndex === element.domIndex || candidate.role === 'text') return false;
      if ((candidate.z || 0) >= (element.z || 0) || !containsRect(candidate.rect, rect)) return false;
      const left = rect.x - candidate.rect.x;
      const right = candidate.rect.x + candidate.rect.w - rect.x - rect.w;
      const top = rect.y - candidate.rect.y;
      const bottom = candidate.rect.y + candidate.rect.h - rect.y - rect.h;
      return left >= 0 && top >= 0 && Math.abs(left - right) <= 0.5 && Math.abs(top - bottom) <= 0.5;
    })
    .sort((a, b) => a.rect.w * a.rect.h - b.rect.w * b.rect.h)[0];

  if (centeredContainer) {
    return {
      alignment: 'center',
      visualOffsetY: deriveTextVisualOffsetY(element.text) === 0 ? 0 : -2,
      centeredContainerDomIndex: centeredContainer.domIndex,
    };
  }

  return {
    alignment: sourceAlignment,
    visualOffsetY: deriveTextVisualOffsetY(element.text),
    centeredContainerDomIndex: null,
  };
}

function buildBoxDecorationModifier({
  tag,
  width,
  height,
  radius,
  backgroundColor,
  shadowElevation,
}) {
  const shape = radius > 0 ? `RoundedCornerShape(${radius}.dp)` : null;
  let modifier = `${tag}.size(${width}.dp, ${height}.dp)`;
  if (shadowElevation) {
    modifier += shape
      ? `.shadow(${shadowElevation}.dp, ${shape}, clip = false)`
      : `.shadow(${shadowElevation}.dp)`;
  }
  if (shape) modifier += `.clip(${shape})`;
  modifier += `.background(${backgroundColor}${shape ? `, ${shape}` : ''})`;
  return modifier;
}

function containsRect(outer, inner) {
  return outer.x <= inner.x && outer.y <= inner.y &&
    outer.x + outer.w >= inner.x + inner.w &&
    outer.y + outer.h >= inner.y + inner.h;
}

function findObservableElements(elements) {
  const ordered = orderVisualElements(elements);
  const observable = [];
  const occluded = [];
  for (let index = 0; index < ordered.length; index++) {
    const element = ordered[index];
    let covering = null;
    for (let later = index + 1; later < ordered.length; later++) {
      if (containsRect(ordered[later].rect, element.rect)) covering = ordered[later];
    }
    if (covering) occluded.push({ domIndex: element.domIndex, occludedBy: covering.domIndex });
    else observable.push(element);
  }
  return { observable, occluded };
}

module.exports = {
  buildBoxDecorationModifier,
  buildCroppedBackgroundModifier,
  buildResponsivePageRoot,
  calculateFitDensity,
  convertSemanticToDp,
  deriveBackgroundImageGeometry,
  deriveTextRenderMetrics,
  deriveTextPlacement,
  deriveTextVisualOffsetY,
  findObservableElements,
  orderVisualElements,
  scalePxValue,
  shouldFillRootBackground,
};
