const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  buildImageResourceMap,
  loadCodeImageResourceIndex,
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

test('reuse 模式按 originalHash 复用改名后的 code-image 资源', () => {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'html-compose-resource-'));
  try {
    const output = path.join(projectRoot, 'app/src/main/res/mipmap-xhdpi/icon_renamed.webp');
    fs.mkdirSync(path.dirname(output), { recursive: true });
    const bytes = Buffer.from('same-image-bytes');
    fs.writeFileSync(output, bytes);
    const originalHash = crypto.createHash('md5').update(bytes).digest('hex');
    fs.mkdirSync(path.join(projectRoot, '.code-image'), { recursive: true });
    fs.writeFileSync(
      path.join(projectRoot, '.code-image/image.json'),
      JSON.stringify({
        version: 2,
        resources: [{
          originalPath: 'source.zip!/mipmap-xhdpi/original.webp',
          originalName: 'original.webp',
          originalHash,
          outputPath: 'app/src/main/res/mipmap-xhdpi/icon_renamed.webp',
          outputName: 'icon_renamed.webp',
        }],
      }),
    );

    const index = loadCodeImageResourceIndex(projectRoot, path.join(projectRoot, 'app/src/main/res'));
    const resolutions = [];
    const result = buildImageResourceMap(['renamed-in-html.webp'], {
      mode: 'reuse',
      hashes: { 'renamed-in-html.webp': originalHash },
      codeImageIndex: index,
      resolutionSink: resolutions,
    });

    assert.equal(result.get('renamed-in-html.webp'), 'icon_renamed');
    assert.deepEqual(resolutions[0], {
      file: 'renamed-in-html.webp',
      resName: 'icon_renamed',
      reused: true,
      source: 'code-image',
      originalHash,
      outputPath: output,
    });
  } finally {
    fs.rmSync(projectRoot, { recursive: true, force: true });
  }
});

test('reuse 模式按累计 image.json 的 md5/path/name 记录复用项目图片', () => {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'html-compose-resource-'));
  try {
    const output = path.join(projectRoot, 'app/src/main/res/mipmap-xxhdpi/icon_back.webp');
    fs.mkdirSync(path.dirname(output), { recursive: true });
    const bytes = Buffer.from('catalog-image-bytes');
    fs.writeFileSync(output, bytes);
    const md5 = crypto.createHash('md5').update(bytes).digest('hex');
    const relativePath = 'app/src/main/res/mipmap-xxhdpi/icon_back.webp';
    fs.mkdirSync(path.join(projectRoot, '.code-image'), { recursive: true });
    fs.writeFileSync(
      path.join(projectRoot, '.code-image/image.json'),
      JSON.stringify({
        version: 3,
        resources: [{
          md5,
          identifier: `${relativePath}-${md5}`,
          path: relativePath,
          name: 'icon_back.webp',
          source: 'L6.zip!/mipmap-xxhdpi/back.webp',
        }],
      }),
    );

    const index = loadCodeImageResourceIndex(projectRoot, path.join(projectRoot, 'app/src/main/res'));
    const result = buildImageResourceMap(['back.webp'], {
      mode: 'reuse',
      hashes: { 'back.webp': md5 },
      codeImageIndex: index,
    });

    assert.equal(result.get('back.webp'), 'icon_back');
    assert.equal(index.byHash.get(md5)[0].outputPath, output);
    assert.equal(index.ignored.length, 0);
  } finally {
    fs.rmSync(projectRoot, { recursive: true, force: true });
  }
});

test('reuse 模式未命中或输出损坏时回退设计包资源', () => {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'html-compose-resource-'));
  try {
    const output = path.join(projectRoot, 'app/src/main/res/mipmap-xxhdpi/icon_broken.webp');
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, 'different');
    fs.mkdirSync(path.join(projectRoot, '.code-image'), { recursive: true });
    fs.writeFileSync(
      path.join(projectRoot, '.code-image/image.json'),
      JSON.stringify({
        resources: [{
          originalPath: 'source.zip!/mipmap-xxhdpi/source.webp',
          originalName: 'source.webp',
          originalHash: '00000000000000000000000000000000',
          outputPath: 'app/src/main/res/mipmap-xxhdpi/icon_broken.webp',
          outputName: 'icon_broken.webp',
        }],
      }),
    );

    const index = loadCodeImageResourceIndex(projectRoot, path.join(projectRoot, 'app/src/main/res'));
    const result = buildImageResourceMap(['source.webp'], {
      mode: 'reuse',
      hashes: { 'source.webp': '11111111111111111111111111111111' },
      codeImageIndex: index,
    });

    assert.equal(result.get('source.webp'), 'icon_report_html_0');
    assert.equal(index.byHash.size, 0);
  } finally {
    fs.rmSync(projectRoot, { recursive: true, force: true });
  }
});

test('reuse 模式忽略旧版按来源清单，只读取固定 image.json', () => {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'html-compose-resource-'));
  try {
    const output = path.join(projectRoot, 'app/src/main/res/mipmap-xxhdpi/icon_legacy.webp');
    fs.mkdirSync(path.dirname(output), { recursive: true });
    const bytes = Buffer.from('legacy-image-bytes');
    fs.writeFileSync(output, bytes);
    const originalHash = crypto.createHash('md5').update(bytes).digest('hex');
    fs.mkdirSync(path.join(projectRoot, '.code-image'), { recursive: true });
    fs.writeFileSync(
      path.join(projectRoot, '.code-image/legacy.resources.json'),
      JSON.stringify({
        resources: [{
          originalHash,
          outputPath: 'app/src/main/res/mipmap-xxhdpi/icon_legacy.webp',
          outputName: 'icon_legacy.webp',
        }],
      }),
    );

    const index = loadCodeImageResourceIndex(projectRoot, path.join(projectRoot, 'app/src/main/res'));

    assert.equal(index.byHash.size, 0);
    assert.deepEqual(index.ignored, []);
  } finally {
    fs.rmSync(projectRoot, { recursive: true, force: true });
  }
});
