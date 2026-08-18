const assert = require('node:assert/strict');
const test = require('node:test');

const {
  evaluateStructure,
  selectSpotCandidates,
  evaluateReferenceImage,
  evaluateReferenceDimensions,
  shouldAcceptReport,
} = require('../compose-validation-core');

test('缺失元素必须计入结构校验分母并判失败', () => {
  const elements = [
    { domIndex: 1, role: 'box', rect: { x: 0, y: 0, w: 20, h: 20 } },
    { domIndex: 2, role: 'text', rect: { x: 30, y: 0, w: 20, h: 20 } },
  ];
  const bounds = {
    e1: { x: 0, y: 0, w: 20, h: 20 },
  };

  const result = evaluateStructure(elements, bounds, {
    toleranceXY: 0,
    toleranceWH: 0,
    toleranceTextWH: 0,
  });

  assert.equal(result.total, 2);
  assert.equal(result.passed, 1);
  assert.equal(result.missing, 1);
  assert.equal(result.passRate, 0.5);
  assert.equal(result.checks[1].reason, 'not-found');
});

test('文本宽度必须参与结构校验', () => {
  const elements = [
    { domIndex: 7, role: 'text', rect: { x: 10, y: 10, w: 80, h: 20 } },
  ];
  const bounds = {
    e7: { x: 10, y: 10, w: 104, h: 20 },
  };

  const result = evaluateStructure(elements, bounds, {
    toleranceXY: 0,
    toleranceWH: 0,
    toleranceTextWH: 2,
  });

  assert.equal(result.passed, 0);
  assert.equal(result.checks[0].dw, 24);
});

test('超出视口的元素必须按可见裁剪边界校验', () => {
  const result = evaluateStructure(
    [{ domIndex: 0, role: 'bg-image', rect: { x: 8, y: 8, w: 1334, h: 750 } }],
    { e0: { x: 8, y: 8, w: 1326, h: 742 } },
    {
      toleranceXY: 0,
      toleranceWH: 0,
      toleranceTextWH: 0,
      viewportWidth: 1334,
      viewportHeight: 750,
    },
  );

  assert.equal(result.passed, 1);
  assert.deepEqual(result.checks[0].expected, { x: 8, y: 8, w: 1326, h: 742 });
});

test('设计基准与原始截图差异过大时必须判为无效', () => {
  const reference = {
    width: 2,
    height: 1,
    data: Uint8Array.from([0, 255, 0, 0, 255, 0]),
  };
  const original = {
    width: 2,
    height: 1,
    data: Uint8Array.from([255, 255, 255, 255, 255, 255]),
  };

  const result = evaluateReferenceImage(reference, original, 0.02);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'reference-mismatch');
});

test('原始设计截图尺寸必须与语义树一致', () => {
  assert.equal(evaluateReferenceDimensions({ width: 1334, height: 750 }, 1334, 750).valid, true);
  assert.equal(evaluateReferenceDimensions({ width: 750, height: 1334 }, 1334, 750).valid, false);
});

test('结构或抽查失败时总验收不能通过', () => {
  assert.equal(shouldAcceptReport({
    reference: { valid: true },
    structure: { passRate: 1 },
    spot: { passRate: 0 },
  }, { structurePass: 0.95, spotPass: 0.8 }), false);

  assert.equal(shouldAcceptReport({
    reference: { valid: false },
    structure: { passRate: 1 },
    spot: { passRate: 1 },
  }, { structurePass: 0.95, spotPass: 0.8 }), false);
});

test('局部像素抽查必须覆盖文本而不是只抽大背景', () => {
  const elements = [
    { domIndex: 1, role: 'bg-image', rect: { x: 0, y: 0, w: 500, h: 300 } },
    { domIndex: 2, role: 'box', rect: { x: 0, y: 0, w: 400, h: 200 } },
    { domIndex: 3, role: 'text', rect: { x: 10, y: 10, w: 100, h: 20 } },
    { domIndex: 4, role: 'text', rect: { x: 10, y: 40, w: 80, h: 20 } },
  ];

  const result = selectSpotCandidates(elements, 4, 1334, 750);

  assert.equal(result.filter((element) => element.role === 'text').length, 2);
});
