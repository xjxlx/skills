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
process.env.COMPOSE_IMAGE_IMPORTS = 'import com.example.ImageItem\nimport com.example.ImageParameter';
const { renderFlowGroup } = require('../html-to-compose');

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
  assert.doesNotMatch(source, /Spacer\(/);
});
