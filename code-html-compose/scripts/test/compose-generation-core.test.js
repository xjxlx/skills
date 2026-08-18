const assert = require('node:assert/strict');
const test = require('node:test');

const {
  convertSemanticToDp,
  buildBoxDecorationModifier,
  buildCroppedBackgroundModifier,
  deriveBackgroundImageGeometry,
  deriveTextRenderMetrics,
  deriveTextPlacement,
  deriveTextVisualOffsetY,
  findObservableElements,
  orderVisualElements,
  shouldFillRootBackground,
} = require('../compose-generation-core');

test('px 转 dp 必须保留半像素逻辑精度', () => {
  const semantic = {
    designW: 1334,
    designH: 750,
    elements: [{
      domIndex: 1,
      rect: { x: 1, y: 3, w: 5, h: 7 },
      style: {
        fontSize: '25px',
        lineHeight: '27px',
        borderRadius: '9px',
        bgSize: '334px 156px',
        bgPosition: '-10px -8px',
      },
    }],
  };

  const result = convertSemanticToDp(semantic, 0.5);

  assert.deepEqual(result.elements[0].rect, { x: 0.5, y: 1.5, w: 2.5, h: 3.5 });
  assert.equal(result.elements[0].style.fontSize, '12.5px');
  assert.equal(result.elements[0].style.lineHeight, '13.5px');
  assert.equal(result.elements[0].style.borderRadius, '4.5px');
  assert.equal(result.elements[0].style.bgSize, '167px 78px');
  assert.equal(result.elements[0].style.bgPosition, '-5px -4px');
});

test('显式背景尺寸和负定位必须转换为 Compose 内部裁切几何', () => {
  assert.deepEqual(deriveBackgroundImageGeometry({
    boundsWidth: 157,
    boundsHeight: 68,
    backgroundSize: '167px 78px',
    backgroundPosition: '-5px -4px',
  }), {
    imageWidth: 167,
    imageHeight: 78,
    offsetX: -5,
    offsetY: -4,
  });

  assert.equal(deriveBackgroundImageGeometry({
    boundsWidth: 157,
    boundsHeight: 68,
    backgroundSize: '100% 100%',
    backgroundPosition: '0% 0%',
  }), null);
});

test('超出容器的背景图片必须从左上角无约束测量避免父布局隐式居中', () => {
  assert.equal(
    buildCroppedBackgroundModifier({
      imageWidth: 167,
      imageHeight: 78,
      offsetX: -5,
      offsetY: -4,
    }),
    'Modifier.wrapContentSize(unbounded = true, align = Alignment.TopStart)' +
      '.requiredSize(width = 167.dp, height = 78.dp)' +
      '.graphicsLayer { translationX = -5.dp.toPx(); translationY = -4.dp.toPx() }',
  );
});

test('高保真基线必须保留全部视觉元素并按 z 顺序输出', () => {
  const elements = [
    { domIndex: 9, z: 100, rect: { x: 0, y: 0, w: 10, h: 10 } },
    { domIndex: 2, z: 1, rect: { x: 0, y: 0, w: 10, h: 10 } },
    { domIndex: 3, z: 1, rect: { x: 0, y: 0, w: 10, h: 10 } },
  ];

  const result = orderVisualElements(elements);

  assert.deepEqual(result.map((element) => element.domIndex), [2, 3, 9]);
  assert.equal(result.length, elements.length);
});

test('被后续完整覆盖的层必须显式归类为不可观测而不是运行时漏算', () => {
  const elements = [
    { domIndex: 1, z: 1, rect: { x: 0, y: 0, w: 100, h: 100 } },
    { domIndex: 2, z: 2, rect: { x: 10, y: 10, w: 20, h: 20 } },
    { domIndex: 3, z: 3, rect: { x: 0, y: 0, w: 100, h: 100 } },
  ];

  const result = findObservableElements(elements);

  assert.deepEqual(result.observable.map((element) => element.domIndex), [3]);
  assert.deepEqual(result.occluded, [
    { domIndex: 1, occludedBy: 3 },
    { domIndex: 2, occludedBy: 3 },
  ]);
});

test('紧贴字号的文本框必须扩展绘制行高且保持原始逻辑边界', () => {
  const result = deriveTextRenderMetrics({
    boundsHeight: 14,
    fontSize: 14,
    lineHeight: 14,
    maxLines: 1,
  });

  assert.equal(result.logicalHeight, 14);
  assert.equal(result.renderLineHeight, 17);
  assert.equal(result.renderHeight, 17);
});

test('设计稿已有充足行高时不得额外改变文字行高', () => {
  const result = deriveTextRenderMetrics({
    boundsHeight: 20,
    fontSize: 14,
    lineHeight: 20,
    maxLines: 1,
  });

  assert.equal(result.renderLineHeight, 20);
  assert.equal(result.renderHeight, 20);
});

test('单行文本必须启用实际字宽适配而不是按设计框裁切', () => {
  const result = deriveTextRenderMetrics({
    boundsHeight: 28,
    fontSize: 20,
    lineHeight: 20,
    maxLines: 1,
    isNowrap: true,
  });

  assert.equal(result.fitWidth, true);
  assert.equal(result.allowInkOverflow, true);
});

test('多行文本不能允许字形逃逸到相邻区块', () => {
  const result = deriveTextRenderMetrics({
    boundsHeight: 26,
    fontSize: 11,
    lineHeight: 13,
    maxLines: 2,
    isNowrap: false,
  });

  assert.equal(result.allowInkOverflow, false);
});

test('文字必须保留平台字体安全 padding 防止字形被截断', () => {
  const result = deriveTextRenderMetrics({
    boundsHeight: 11,
    fontSize: 11,
    lineHeight: 11,
    maxLines: 1,
    isNowrap: true,
  });

  assert.equal(result.includeFontPadding, true);
});

test('只有从视口原点开始的背景才能转成 fillMaxSize', () => {
  assert.equal(
    shouldFillRootBackground({ rect: { x: 0, y: 0, w: 667, h: 375 }, hasImage: true }, 667, 375),
    true,
  );
  assert.equal(
    shouldFillRootBackground({ rect: { x: 4, y: 4, w: 667, h: 375 }, hasImage: true }, 667, 375),
    false,
  );
});

test('含中文的文字绘制层需要上移但纯数字保持原位', () => {
  assert.equal(deriveTextVisualOffsetY('查看详情'), -2.5);
  assert.equal(deriveTextVisualOffsetY('1000词'), -2.5);
  assert.equal(deriveTextVisualOffsetY('18'), 0);
});

test('等边距徽章内的文字必须覆盖源 CSS 右对齐并按徽章中心放置', () => {
  const badge = {
    domIndex: 75,
    role: 'bg-image',
    rect: { x: 167, y: 92, w: 28, h: 14 },
    z: 76,
  };
  const label = {
    domIndex: 76,
    role: 'text',
    rect: { x: 171, y: 94, w: 20, h: 10 },
    text: '达标',
    z: 100077,
    style: { textAlign: 'right', fontSize: '10px' },
  };

  assert.deepEqual(deriveTextPlacement(label, [badge, label]), {
    alignment: 'center',
    visualOffsetY: -2,
    centeredContainerDomIndex: 75,
  });
});

test('大字号按钮文字不能套用小状态徽章的垂直补偿', () => {
  const button = {
    domIndex: 5,
    role: 'box',
    rect: { x: 413.5, y: 29, w: 60, h: 24 },
    z: 6,
  };
  const label = {
    domIndex: 6,
    role: 'text',
    rect: { x: 429.5, y: 31, w: 28, h: 20 },
    text: '今天',
    z: 100007,
    style: { textAlign: 'center', fontSize: '20px' },
  };

  assert.deepEqual(deriveTextPlacement(label, [button, label]), {
    alignment: 'center',
    visualOffsetY: -2.5,
    centeredContainerDomIndex: null,
  });
});

test('普通文字必须保持设计稿原始对齐与现有基线补偿', () => {
  const label = {
    domIndex: 104,
    role: 'text',
    rect: { x: 493, y: 132, w: 44, h: 11 },
    text: '查看详情',
    z: 100105,
    style: { textAlign: 'left' },
  };

  assert.deepEqual(deriveTextPlacement(label, [label]), {
    alignment: 'left',
    visualOffsetY: -2.5,
    centeredContainerDomIndex: null,
  });
});

test('圆角阴影必须先按同一 shape 绘制再裁剪背景', () => {
  const modifier = buildBoxDecorationModifier({
    tag: 'Modifier.testTag("e5")',
    width: 60,
    height: 24,
    radius: 15,
    backgroundColor: 'Color.White',
    shadowElevation: 2,
  });

  assert.equal(
    modifier,
    'Modifier.testTag("e5").size(60.dp, 24.dp).shadow(2.dp, RoundedCornerShape(15.dp), clip = false).clip(RoundedCornerShape(15.dp)).background(Color.White, RoundedCornerShape(15.dp))',
  );
});
