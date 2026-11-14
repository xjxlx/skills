function evaluateReferenceDimensions(reference, designWidth, designHeight) {
  const valid = Boolean(reference && reference.width === designWidth && reference.height === designHeight);
  return {
    valid,
    reason: valid ? null : 'reference-size-mismatch',
    expected: `${designWidth}x${designHeight}`,
    actual: reference ? `${reference.width}x${reference.height}` : null,
  };
}

function clipRectToViewport(rect, viewportWidth, viewportHeight) {
  if (!Number.isFinite(viewportWidth) || !Number.isFinite(viewportHeight)) return rect;
  const x = Math.max(0, rect.x);
  const y = Math.max(0, rect.y);
  const right = Math.min(viewportWidth, rect.x + rect.w);
  const bottom = Math.min(viewportHeight, rect.y + rect.h);
  return { x, y, w: Math.max(0, right - x), h: Math.max(0, bottom - y) };
}

function evaluateStructure(elements, bounds, options) {
  const toleranceXY = options.toleranceXY;
  const toleranceWH = options.toleranceWH;
  const toleranceTextWH = options.toleranceTextWH;
  let passed = 0;
  let missing = 0;
  const checks = elements.map((element) => {
    const actual = bounds[`e${element.domIndex}`];
    if (!actual) {
      missing++;
      return {
        domIndex: element.domIndex,
        role: element.role,
        text: element.text ? String(element.text).slice(0, 12) : undefined,
        found: false,
        passed: false,
        reason: 'not-found',
      };
    }

    const expected = clipRectToViewport(
      element.rect,
      options.viewportWidth,
      options.viewportHeight,
    );
    const toleranceSize = element.role === 'text' ? toleranceTextWH : toleranceWH;
    const dx = Math.abs(actual.x - expected.x);
    const dy = Math.abs(actual.y - expected.y);
    const dw = Math.abs(actual.w - expected.w);
    const dh = Math.abs(actual.h - expected.h);
    const ok = dx <= toleranceXY && dy <= toleranceXY && dw <= toleranceSize && dh <= toleranceSize;
    if (ok) passed++;
    return {
      domIndex: element.domIndex,
      role: element.role,
      text: element.text ? String(element.text).slice(0, 12) : undefined,
      found: true,
      expected,
      actual,
      dx,
      dy,
      dw,
      dh,
      passed: ok,
    };
  });

  return {
    total: elements.length,
    passed,
    missing,
    passRate: elements.length ? passed / elements.length : 0,
    checks,
  };
}

function shouldAcceptReport(report, thresholds) {
  return Boolean(
    report.reference && report.reference.valid &&
    report.pixel && report.pixel.similarity >= thresholds.pixelPass &&
    report.structure && report.structure.passRate >= thresholds.structurePass &&
    report.spot && report.spot.passRate >= thresholds.spotPass
  );
}

function selectSpotCandidates(elements, count, designWidth, designHeight) {
  const eligible = elements.filter((element) => !(
    element.rect.w >= designWidth - 16 && element.rect.h >= designHeight - 16
  ));
  const byArea = (items) => [...items].sort((a, b) => {
    const area = b.rect.w * b.rect.h - a.rect.w * a.rect.h;
    return area || a.domIndex - b.domIndex;
  });
  const textTarget = Math.min(Math.ceil(count / 2), eligible.filter((element) => element.role === 'text').length);
  const texts = byArea(eligible.filter((element) => element.role === 'text')).slice(0, textTarget);
  const selected = new Set(texts.map((element) => element.domIndex));
  const remaining = byArea(eligible.filter((element) => !selected.has(element.domIndex))).slice(0, count - texts.length);
  return [...texts, ...remaining];
}

module.exports = {
  evaluateReferenceDimensions,
  evaluateStructure,
  selectSpotCandidates,
  shouldAcceptReport,
};
