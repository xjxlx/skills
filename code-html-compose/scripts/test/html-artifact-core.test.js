const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { packageNormalizedHtml } = require('../html-artifact-core');

test('new.html 归档必须同时复制相对路径引用的完整 img 目录', (t) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'html-artifact-'));
  t.after(() => fs.rmSync(tempRoot, { recursive: true, force: true }));

  const designDir = path.join(tempRoot, 'design');
  const outputDir = path.join(tempRoot, 'run');
  fs.mkdirSync(path.join(designDir, 'img', 'nested'), { recursive: true });
  fs.writeFileSync(
    path.join(designDir, 'normalized.html'),
    '<img src="./img/flame.png"><img src="./img/nested/arrow.png">',
  );
  fs.writeFileSync(path.join(designDir, 'img', 'flame.png'), 'flame');
  fs.writeFileSync(path.join(designDir, 'img', 'nested', 'arrow.png'), 'arrow');

  const result = packageNormalizedHtml({
    normalizedHtml: path.join(designDir, 'normalized.html'),
    designDir,
    outputDir,
  });

  assert.equal(fs.readFileSync(path.join(outputDir, 'new.html'), 'utf8'), '<img src="./img/flame.png"><img src="./img/nested/arrow.png">');
  assert.equal(fs.readFileSync(path.join(outputDir, 'img', 'flame.png'), 'utf8'), 'flame');
  assert.equal(fs.readFileSync(path.join(outputDir, 'img', 'nested', 'arrow.png'), 'utf8'), 'arrow');
  assert.deepEqual(result, { copiedHtml: true, copiedImageDirectory: true });
});
