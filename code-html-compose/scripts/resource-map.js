const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const ANDROID_RESOURCE_NAME = /^[a-z][a-z0-9_]*$/;
const FULL_MD5 = /^[0-9a-f]{32}$/i;

function normalizeResourceExpression(value) {
  const expression = String(value || '').trim()
    .replace(/^@mipmap\//, '')
    .replace(/^R\.mipmap\./, '');
  if (!ANDROID_RESOURCE_NAME.test(expression)) {
    throw new Error(`资源名 ${value} 不是合法的 Android 资源名`);
  }
  return expression;
}

function md5File(filePath) {
  const digest = crypto.createHash('md5');
  digest.update(fs.readFileSync(filePath));
  return digest.digest('hex');
}

function isWithinDirectory(filePath, directory) {
  const relative = path.relative(directory, filePath);
  return relative === '' || (relative && !relative.startsWith('..') && !path.isAbsolute(relative));
}

/**
 * 读取项目根目录累计的 .code-image/image.json，按图片完整 MD5 建立可复用索引。
 * 同时兼容旧版 originalHash/outputPath/outputName 字段，便于项目平滑迁移。
 * 无清单、坏记录、跨模块记录或不存在的输出文件均忽略，由调用方回退设计包图片。
 */
function loadCodeImageResourceIndex(projectRoot, resourceRoot) {
  const byHash = new Map();
  const ignored = [];
  const directory = path.join(path.resolve(projectRoot), '.code-image');
  const targetRoot = path.resolve(resourceRoot);
  try {
    if (!fs.statSync(directory).isDirectory()) return { byHash, ignored };
  } catch (error) {
    return { byHash, ignored };
  }

  const manifestName = 'image.json';
  const files = fs.existsSync(path.join(directory, manifestName)) ? [manifestName] : [];
  for (const name of files) {
    const manifestPath = path.join(directory, name);
    let manifest;
    try {
      manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    } catch (error) {
      ignored.push({ manifest: name, reason: 'invalid-json' });
      continue;
    }
    if (!manifest || !Array.isArray(manifest.resources)) {
      ignored.push({ manifest: name, reason: 'invalid-resources' });
      continue;
    }
    for (const record of manifest.resources) {
      if (!record || typeof record !== 'object' || Array.isArray(record)) {
        ignored.push({ manifest: name, reason: 'invalid-record' });
        continue;
      }
      const hash = String(record.md5 || record.originalHash || '').toLowerCase();
      const outputPathValue = String(record.path || record.outputPath || '');
      const outputName = String(record.name || record.outputName || (outputPathValue ? path.basename(outputPathValue) : ''));
      if (!FULL_MD5.test(hash) || !outputPathValue || !outputName) {
        ignored.push({ manifest: name, reason: 'incomplete-record' });
        continue;
      }
      const outputPath = path.resolve(path.isAbsolute(outputPathValue)
        ? outputPathValue
        : path.join(projectRoot, outputPathValue));
      let outputExists = false;
      try {
        outputExists = fs.statSync(outputPath).isFile()
          && path.basename(outputPath) === outputName
          && md5File(outputPath).toLowerCase() === hash;
      } catch (error) {
        outputExists = false;
      }
      if (!isWithinDirectory(outputPath, targetRoot) || !outputExists) {
        ignored.push({ manifest: name, reason: 'missing-cross-module-or-hash-mismatch', outputPath: outputPathValue });
        continue;
      }
      const outputStem = path.basename(outputName, path.extname(outputName));
      let resourceName;
      try {
        resourceName = normalizeResourceExpression(outputStem);
      } catch (error) {
        ignored.push({ manifest: name, reason: 'invalid-resource-name', outputName });
        continue;
      }
      const entries = byHash.get(hash) || [];
      if (!entries.some((entry) => entry.resourceName === resourceName && entry.outputPath === outputPath)) {
        entries.push({
          resourceName,
          outputPath,
          outputName,
          manifest: name,
          originalPath: record.source || record.originalPath || null,
        });
        entries.sort((a, b) => a.outputPath.localeCompare(b.outputPath));
        byHash.set(hash, entries);
      }
    }
  }
  return { byHash, ignored };
}

function firstCodeImageMatch(fileHash, index) {
  if (!index || !FULL_MD5.test(String(fileHash || ''))) return null;
  const candidates = index.byHash.get(String(fileHash).toLowerCase()) || [];
  return candidates[0] || null;
}

function buildImageResourceMap(files, options = {}) {
  const mode = options.mode || 'copy';
  const mapping = options.mapping || {};
  const hashes = options.hashes || {};
  const resolutionSink = options.resolutionSink;
  const result = new Map();
  const uniqueFiles = [...new Set(files)];

  if (mode !== 'copy' && mode !== 'existing' && mode !== 'reuse') {
    throw new Error(`COMPOSE_RESOURCE_MODE 只支持 copy、reuse 或 existing，当前值：${mode}`);
  }

  uniqueFiles.forEach((file, index) => {
    if (Object.prototype.hasOwnProperty.call(mapping, file)) {
      const resName = normalizeResourceExpression(mapping[file]);
      result.set(file, resName);
      if (resolutionSink) resolutionSink.push({ file, resName, reused: true, source: 'explicit-map' });
      return;
    }
    if (mode === 'existing') {
      throw new Error(`existing 模式缺少图片 ${file} 的资源映射，请在 COMPOSE_RESOURCE_MAP 中补齐`);
    }
    if (mode === 'reuse') {
      const match = firstCodeImageMatch(hashes[file], options.codeImageIndex);
      if (match) {
        result.set(file, match.resourceName);
        if (resolutionSink) {
          resolutionSink.push({
            file,
            resName: match.resourceName,
            reused: true,
            source: 'code-image',
            originalHash: String(hashes[file]).toLowerCase(),
            outputPath: match.outputPath,
          });
        }
        return;
      }
    }
    const resName = `icon_report_html_${index}`;
    result.set(file, resName);
    if (resolutionSink) {
      resolutionSink.push({ file, resName, reused: false, source: 'design-package' });
    }
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
  firstCodeImageMatch,
  loadResourceMapping,
  loadCodeImageResourceIndex,
  md5File,
  normalizeResourceExpression,
};
