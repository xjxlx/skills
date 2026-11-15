const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { after, test } = require('node:test');

const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'code-compose-v2-layout-'));
fs.mkdirSync(path.join(fixtureRoot, 'design'), { recursive: true });
fs.mkdirSync(path.join(fixtureRoot, 'kotlin'), { recursive: true });
fs.mkdirSync(path.join(fixtureRoot, 'res'), { recursive: true });
process.env.PROJECT_ROOT = fixtureRoot;
process.env.DESIGN_DIR = path.join(fixtureRoot, 'design');
process.env.COMPOSE_KOTLIN_DIR = path.join(fixtureRoot, 'kotlin');
process.env.COMPOSE_RES_DIR = path.join(fixtureRoot, 'res');
process.env.COMPOSE_PACKAGE = 'com.example.generated';
process.env.COMPOSE_R_IMPORT = 'import com.example.R';
process.env.COMPOSE_TEXT_IMPORT = 'import com.example.TextItem';
process.env.COMPOSE_IMAGE_IMPORTS = 'import com.example.ImageItem\nimport com.example.ImageParameter';
const {
  assertGeneratedLayoutPolicy,
  generatePage,
  genContent,
  renderFlowGroup,
} = require('../html-to-compose');

after(() => {
  fs.rmSync(fixtureRoot, { recursive: true, force: true });
});

function boxNode(domIndex, rect) {
  return {
    e: {
      domIndex,
      role: 'box',
      rect,
      style: { bgColor: 'rgb(255, 255, 255)' },
      z: domIndex,
    },
    children: [],
  };
}

test('普通文本必须生成 TextItem，图片继续使用 ImageItem', () => {
  const element = {
    domIndex: 1,
    role: 'text',
    text: '示例文本',
    rect: { x: 10, y: 12, w: 80, h: 20 },
    z: 1,
    style: {
      color: 'rgb(0, 0, 0)',
      fontSize: '14px',
      lineHeight: '18px',
      textAlign: 'left',
    },
  };

  const source = genContent(element, { elements: [element], imgMap: new Map() }, 0);

  assert.match(source, /TextItem\(/);
  assert.doesNotMatch(source, /softWrap =/);
  assert.doesNotMatch(source, /PlatformTextStyle/);
});

test('生成页面不得创建第二套窗口适配层', () => {
  const semantic = {
    designW: 667,
    designH: 375,
    elements: [{
      domIndex: 1,
      role: 'text',
      text: '页面标题',
      rect: { x: 16, y: 16, w: 100, h: 24 },
      z: 1,
      style: {
        color: 'rgb(0, 0, 0)',
        fontSize: '16px',
        lineHeight: '20px',
        textAlign: 'left',
      },
    }],
  };

  const source = generatePage(semantic, new Map(), { rules: {} });

  assert.match(source, /TextItem\(/);
  assert.doesNotMatch(source, /BoxWithConstraints/);
  assert.doesNotMatch(source, /LocalDensity/);
  assert.doesNotMatch(source, /CompositionLocalProvider/);
  assert.match(source, /AutoSizeConfig\.DEFAULT_HEIGHT/);
  assert.match(source, /ConstraintLayout\(/);
  assert.match(source, /val \(+[^)]*\) = createRefs\(\)/);
  assert.match(source, /constrainAs\(/);
  assert.doesNotMatch(source, /private const val PAGE_WIDTH/);
  assert.doesNotMatch(source, /private const val PAGE_HEIGHT/);
  assert.match(source, /createGuidelineFromStart\(/);
  assert.match(source, /createGuidelineFromEnd\(/);
  assert.match(source, /createGuidelineFromTop\(/);
  assert.match(source, /createGuidelineFromBottom\(/);
  assert.match(source, /height = Dimension\.fillToConstraints/);
  assert.doesNotMatch(source, /Dimension\.value\(/);
  assert.match(source, /DEFAULT_WIDTH|DEFAULT_HEIGHT/);
  assert.doesNotMatch(source, /testTag\("e0"\)/);
  assert.doesNotMatch(source, /= createRef\(\)/);
  assert.match(source, /\/\/ 展示文本“页面标题”/);
  assert.doesNotMatch(source, /子布局：/);
  assert.match(source, /\/\*\*[\s\S]*用途：展示文本“页面标题”/);
  assert.match(source, /private fun \w+\(modifier: Modifier = Modifier\)/);
  assert.doesNotThrow(() => assertGeneratedLayoutPolicy(source));
});

test('生成器必须拒绝违反 ConstraintLayout 契约的源码', () => {
  assert.throws(
    () => assertGeneratedLayoutPolicy('@Composable fun Bad() { Box {} }'),
    /缺少 createRefs/,
  );
});

function createContext() {
  return {
    imgMap: new Map(),
    elements: [],
  };
}

test('纵向相邻元素使用后一个子项的 top padding 表达间距', () => {
  const parentRect = { x: 0, y: 0, w: 200, h: 100 };
  const source = renderFlowGroup(
    'Column',
    [
      boxNode(1, { x: 0, y: 0, w: 100, h: 20 }),
      boxNode(2, { x: 0, y: 31, w: 100, h: 20 }),
    ],
    parentRect,
    createContext(),
  );

  assert.match(source, /\.padding\(top = 11\.dp\)/);
  assert.match(source, /\/\/ 将 2 个相邻元素按 Column 排列/);
  assert.doesNotMatch(source, /子布局：/);
  assert.doesNotMatch(source, /Spacer\(/);
});

test('横向相邻元素使用后一个子项的 start padding 表达间距', () => {
  const parentRect = { x: 0, y: 0, w: 200, h: 100 };
  const source = renderFlowGroup(
    'Row',
    [
      boxNode(1, { x: 0, y: 0, w: 100, h: 20 }),
      boxNode(2, { x: 121, y: 0, w: 100, h: 20 }),
    ],
    parentRect,
    createContext(),
  );

  assert.match(source, /\.padding\(start = 21\.dp\)/);
  assert.match(source, /\/\/ 将 2 个相邻元素按 Row 排列/);
  assert.doesNotMatch(source, /子布局：/);
  assert.doesNotMatch(source, /Spacer\(/);
});
