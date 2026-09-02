const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { loadReferenceManifest } = require('../reference-manifest');

function writeManifest(value) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'code-html-compose-reference-'));
  const file = path.join(dir, 'references.json');
  fs.writeFileSync(file, JSON.stringify(value));
  return { dir, file };
}

test('参考清单区分主页面、纵向列表状态和右上角弹窗状态', () => {
  const { dir, file } = writeManifest({
    primary: { zip: '/tmp/L6.zip', scope: 'primary-page' },
    fragments: [
      { zip: '/tmp/滑动.zip', scope: 'vertical-list-state' },
      { zip: '/tmp/弹窗.zip', scope: 'popup-state' },
    ],
  });

  const result = loadReferenceManifest(file, dir);

  assert.equal(result.primary.scope, 'primary-page');
  assert.deepEqual(result.fragments.map((item) => item.scope), [
    'vertical-list-state',
    'popup-state',
  ]);
  assert.equal(result.fragments[1].zip, '/tmp/弹窗.zip');
});

test('参考清单拒绝把状态片段声明为主页面', () => {
  const { dir, file } = writeManifest({
    primary: { zip: '/tmp/弹窗.zip', scope: 'popup-state' },
  });

  assert.throws(() => loadReferenceManifest(file, dir), /primary-page/);
});

test('参考清单拒绝未声明 scope 的片段', () => {
  const { dir, file } = writeManifest({
    primary: { zip: '/tmp/L6.zip', scope: 'primary-page' },
    fragments: [{ zip: '/tmp/滑动.zip' }],
  });

  assert.throws(() => loadReferenceManifest(file, dir), /scope/);
});
