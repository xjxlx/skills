const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  detectDesignSize,
  requireSupportedDesignSize,
} = require('../design-size');

function withDesignDirectory(files, callback) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'code-compose-v2-size-'));
  try {
    for (const [name, contents] of Object.entries(files)) {
      fs.writeFileSync(path.join(directory, name), contents);
    }
    callback(directory);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test('设计尺寸必须从当前设计包的 page 样式读取并符合固定基准', () => {
  withDesignDirectory({
    'index.css': '.page { width: 1334px; height: 750px; }',
  }, (directory) => {
    const size = detectDesignSize(directory);
    assert.deepEqual(size, { w: 1334, h: 750, source: 'css' });
    assert.deepEqual(requireSupportedDesignSize(size), size);
  });
});

test('非 1334x750 设计稿必须立即停止', () => {
  withDesignDirectory({
    'index.css': '.page { width: 1600px; height: 720px; }',
  }, (directory) => {
    assert.throws(
      () => requireSupportedDesignSize(detectDesignSize(directory)),
      /需要 1334x750，实际为 1600x720/,
    );
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
