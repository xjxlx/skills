const fs = require('node:fs');
const path = require('node:path');

const FRAGMENT_SCOPES = new Set(['vertical-list-state', 'popup-state']);

function resolveZip(value, projectRoot) {
  if (!value || typeof value !== 'string') {
    throw new Error('参考包必须提供 zip 路径');
  }
  return path.isAbsolute(value) ? path.resolve(value) : path.resolve(projectRoot, value);
}

function normalizeEntry(entry, projectRoot, expectedScope) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    throw new Error('参考清单中的页面条目必须是对象');
  }
  if (entry.scope !== expectedScope) {
    throw new Error(`主页面 scope 必须声明为 ${expectedScope}`);
  }
  return { ...entry, zip: resolveZip(entry.zip, projectRoot), scope: expectedScope };
}

function loadReferenceManifest(manifestPath, projectRoot = process.cwd()) {
  const source = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    throw new Error(`参考清单必须是 JSON 对象：${manifestPath}`);
  }

  const primary = normalizeEntry(source.primary, projectRoot, 'primary-page');
  const fragments = (source.fragments || []).map((entry) => {
    if (!entry || !FRAGMENT_SCOPES.has(entry.scope)) {
      throw new Error('参考清单的每个片段必须声明 scope：vertical-list-state 或 popup-state');
    }
    return { ...entry, zip: resolveZip(entry.zip, projectRoot) };
  });

  return { ...source, primary, fragments };
}

module.exports = {
  loadReferenceManifest,
};
