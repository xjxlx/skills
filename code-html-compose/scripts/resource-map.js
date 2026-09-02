const fs = require('node:fs');

const ANDROID_RESOURCE_NAME = /^[a-z][a-z0-9_]*$/;

function normalizeResourceExpression(value) {
  const expression = String(value || '').trim()
    .replace(/^@mipmap\//, '')
    .replace(/^R\.mipmap\./, '');
  if (!ANDROID_RESOURCE_NAME.test(expression)) {
    throw new Error(`资源名 ${value} 不是合法的 Android 资源名`);
  }
  return expression;
}

function buildImageResourceMap(files, options = {}) {
  const mode = options.mode || 'copy';
  const mapping = options.mapping || {};
  const result = new Map();
  const uniqueFiles = [...new Set(files)];

  if (mode !== 'copy' && mode !== 'existing') {
    throw new Error(`COMPOSE_RESOURCE_MODE 只支持 copy 或 existing，当前值：${mode}`);
  }

  uniqueFiles.forEach((file, index) => {
    if (mode === 'existing') {
      if (!Object.prototype.hasOwnProperty.call(mapping, file)) {
        throw new Error(`existing 模式缺少图片 ${file} 的资源映射，请在 COMPOSE_RESOURCE_MAP 中补齐`);
      }
      result.set(file, normalizeResourceExpression(mapping[file]));
      return;
    }
    result.set(file, `icon_report_html_${index}`);
  });

  return result;
}

function loadResourceMapping(resourceMapPath) {
  if (!resourceMapPath) return {};
  const source = JSON.parse(fs.readFileSync(resourceMapPath, 'utf8'));
  const mapping = source && source.files ? source.files : source;
  if (!mapping || Array.isArray(mapping) || typeof mapping !== 'object') {
    throw new Error(`COMPOSE_RESOURCE_MAP 必须是 JSON 对象，或包含 files 对象：${resourceMapPath}`);
  }
  return mapping;
}

module.exports = {
  buildImageResourceMap,
  loadResourceMapping,
  normalizeResourceExpression,
};
