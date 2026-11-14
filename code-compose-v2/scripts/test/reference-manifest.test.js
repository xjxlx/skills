const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { loadReferenceManifest } = require('../reference-manifest');

function writeManifest(value) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'code-compose-v2-reference-'));
  const file = path.join(dir, 'references.json');
  fs.writeFileSync(file, JSON.stringify(value));
  return { dir, file };
}

test('参考清单区分主页面和通用状态片段', () => {
  const { dir, file } = writeManifest({
    primary: { zip: '/tmp/主页面.zip', scope: 'primary-page' },
    fragments: [
      { zip: '/tmp/状态一.zip', scope: 'state-reference' },
      { zip: '/tmp/状态二.zip', scope: 'state-reference' },
    ],
  });

  const result = loadReferenceManifest(file, dir);

  assert.equal(result.primary.scope, 'primary-page');
  assert.deepEqual(result.fragments.map((item) => item.scope), [
    'state-reference',
    'state-reference',
  ]);
  assert.equal(result.fragments[1].zip, '/tmp/状态二.zip');
});

test('参考清单拒绝把状态片段声明为主页面', () => {
  const { dir, file } = writeManifest({
    primary: { zip: '/tmp/状态.zip', scope: 'state-reference' },
  });

  assert.throws(() => loadReferenceManifest(file, dir), /primary-page/);
});

test('参考清单拒绝未声明 scope 的片段', () => {
  const { dir, file } = writeManifest({
    primary: { zip: '/tmp/主页面.zip', scope: 'primary-page' },
    fragments: [{ zip: '/tmp/片段.zip' }],
  });

  assert.throws(() => loadReferenceManifest(file, dir), /scope/);
});
