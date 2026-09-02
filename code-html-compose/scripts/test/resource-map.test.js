const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildImageResourceMap,
  normalizeResourceExpression,
} = require('../resource-map');

test('existing 模式使用显式的现有 R 资源名，不生成 icon_report_html 前缀', () => {
  const result = buildImageResourceMap(['mask.png', 'book.webp'], {
    mode: 'existing',
    mapping: {
      'mask.png': 'icon_l6_mask',
      'book.webp': 'icon_l6_group',
    },
  });

  assert.deepEqual([...result.entries()], [
    ['mask.png', 'icon_l6_mask'],
    ['book.webp', 'icon_l6_group'],
  ]);
});

test('existing 模式缺少映射时立即失败并指出缺失文件', () => {
  assert.throws(
    () => buildImageResourceMap(['mask.png', 'book.webp'], {
      mode: 'existing',
      mapping: { 'mask.png': 'icon_l6_mask' },
    }),
    /book\.webp.*COMPOSE_RESOURCE_MAP/,
  );
});

test('资源表达式允许直接配置 R.mipmap，但最终统一为资源名', () => {
  assert.equal(normalizeResourceExpression('R.mipmap.icon_l6_mask'), 'icon_l6_mask');
  assert.equal(normalizeResourceExpression('icon_l6_group'), 'icon_l6_group');
  assert.throws(() => normalizeResourceExpression('not-valid-name'), /合法的 Android 资源名/);
});
