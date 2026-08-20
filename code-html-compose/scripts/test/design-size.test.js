const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { detectDesignSize } = require('../design-size');

function withDesignDirectory(files, callback) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'code-html-compose-size-'));
  try {
    for (const [name, contents] of Object.entries(files)) {
      fs.writeFileSync(path.join(directory, name), contents);
    }
    callback(directory);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test('设计尺寸必须从当前设计包的 page 样式读取', () => {
  withDesignDirectory({
    'index.css': '.page { width: 1600px; height: 720px; }',
  }, (directory) => {
    assert.deepEqual(detectDesignSize(directory), { w: 1600, h: 720, source: 'css' });
  });
});

test('无法自动识别时允许成对显式指定当前设计尺寸', () => {
  withDesignDirectory({}, (directory) => {
    assert.deepEqual(detectDesignSize(directory, {
      width: '812',
      height: '375',
    }), { w: 812, h: 375, source: 'environment' });
  });
});

test('无法识别设计尺寸时必须失败而不是回退固定尺寸', () => {
  withDesignDirectory({}, (directory) => {
    assert.throws(
      () => detectDesignSize(directory),
      /无法识别设计稿尺寸/,
    );
  });
});
