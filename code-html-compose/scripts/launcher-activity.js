const fs = require('node:fs');
const path = require('node:path');

const IGNORED_DIRECTORIES = new Set([
  '.git',
  '.gradle',
  '.idea',
  'build',
  'node_modules',
]);

function collectManifestPaths(projectRoot) {
  const manifests = [];
  const pending = [path.resolve(projectRoot)];

  while (pending.length > 0) {
    const current = pending.pop();
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (!IGNORED_DIRECTORIES.has(entry.name)) pending.push(entryPath);
      } else if (entry.isFile() && entry.name === 'AndroidManifest.xml') {
        manifests.push(entryPath);
      }
    }
  }

  return manifests.sort();
}

function stripXmlComments(xml) {
  return xml.replace(/<!--[\s\S]*?-->/g, '');
}

function readAttribute(source, attributeName) {
  const escapedName = attributeName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = source.match(new RegExp(`${escapedName}\\s*=\\s*["']([^"']+)["']`, 'i'));
  return match ? match[1] : null;
}

function readManifestPackage(xml) {
  const manifestTag = xml.match(/<manifest\b[^>]*>/i);
  return manifestTag ? readAttribute(manifestTag[0], 'package') : null;
}

function normalizeActivityName(name, manifestPackage) {
  if (!name) return null;
  if (name.startsWith('.')) return `${manifestPackage || ''}${name}`;
  if (!name.includes('.')) return manifestPackage ? `${manifestPackage}.${name}` : name;
  return name;
}

function hasNamedTag(source, tagName, name) {
  const tagPattern = new RegExp(`<${tagName}\\b[^>]*>`, 'gi');
  return [...source.matchAll(tagPattern)].some((match) => readAttribute(match[0], 'android:name') === name);
}

function hasLauncherIntentFilter(activityBlock) {
  const filterPattern = /<intent-filter\b[^>]*>([\s\S]*?)<\/intent-filter\s*>/gi;
  return [...activityBlock.matchAll(filterPattern)].some((match) => {
    const filter = match[1];
    return hasNamedTag(filter, 'action', 'android.intent.action.MAIN') &&
      hasNamedTag(filter, 'category', 'android.intent.category.LAUNCHER');
  });
}

function findActivityDeclarations(manifestPath, fallbackPackage) {
  const xml = stripXmlComments(fs.readFileSync(manifestPath, 'utf8'));
  const manifestPackage = readManifestPackage(xml) || fallbackPackage;
  const activityBlocks = [
    ...xml.matchAll(/<(activity|activity-alias)\b(?![^>]*\/\s*>)[^>]*>[\s\S]*?<\/\1\s*>/gi),
    ...xml.matchAll(/<(activity|activity-alias)\b[^>]*\/\s*>/gi),
  ];

  return activityBlocks.flatMap((match) => {
    const block = match[0];
    const name = readAttribute(block, 'android:name');
    if (!name) return [];
    return [{
      name,
      fullName: normalizeActivityName(name, manifestPackage),
      type: match[1],
      targetActivity: readAttribute(block, 'android:targetActivity'),
      manifest: manifestPath,
      launcher: hasLauncherIntentFilter(block),
    }];
  });
}

function findActivityOpeningTag(manifestPath, fullName, fallbackPackage) {
  const xml = fs.readFileSync(manifestPath, 'utf8');
  const manifestPackage = readManifestPackage(stripXmlComments(xml)) || fallbackPackage;
  const comments = [...xml.matchAll(/<!--[\s\S]*?-->/g)].map((match) => ({
    start: match.index,
    end: match.index + match[0].length,
  }));
  const activityPattern = /<(activity|activity-alias)\b[^>]*>/gi;
  for (const match of xml.matchAll(activityPattern)) {
    if (comments.some((comment) => match.index >= comment.start && match.index < comment.end)) continue;
    const name = readAttribute(match[0], 'android:name');
    if (name && normalizeActivityName(name, manifestPackage) === fullName) {
      return { tag: match[0], start: match.index, end: match.index + match[0].length };
    }
  }
  return null;
}

function withLandscapeOrientation(tag) {
  const orientationPattern = /android:screenOrientation\s*=\s*["'][^"']*["']/i;
  if (orientationPattern.test(tag)) {
    return tag.replace(orientationPattern, 'android:screenOrientation="landscape"');
  }
  return /\/\s*>$/.test(tag)
    ? tag.replace(/\/\s*>$/, ' android:screenOrientation="landscape" />')
    : tag.replace(/>$/, ' android:screenOrientation="landscape">');
}

function parseActivityComponent(activityComponent) {
  const component = String(activityComponent || '').trim();
  const separator = component.lastIndexOf('/');
  if (!component || separator <= 0 || separator === component.length - 1) return null;

  const packageName = component.slice(0, separator);
  const className = component.slice(separator + 1);
  return {
    component,
    packageName,
    className: className.startsWith('.') ? `${packageName}${className}` :
      className.includes('.') ? className : `${packageName}.${className}`,
  };
}

function stopMessage(component, reason) {
  const detail = reason === 'missing-component'
    ? '未配置 COMPOSE_ACTIVITY，无法确定当前生成布局实际由哪个 Activity 承载。'
    : reason === 'not-found'
      ? `未在项目源 AndroidManifest.xml 中找到 COMPOSE_ACTIVITY=${component} 对应的 Activity 或 Activity-alias。`
      : `COMPOSE_ACTIVITY=${component} 已找到，但它没有同时包含 MAIN 和 LAUNCHER 的默认 intent-filter。`;

  return [
    detail,
    '需要确认该承载生成布局的 Activity 中存在：',
    '<intent-filter>、<action android:name="android.intent.action.MAIN" />',
    '和 <category android:name="android.intent.category.LAUNCHER" />。',
    '已停止后续 HTML/Compose 生成、编译、安装和验收操作。',
    '请先确认或提供现有的默认 Activity；禁止自动创建新的 Activity，或补写 MAIN/LAUNCHER 标签。',
  ].join('\n');
}

function inspectConfiguredActivity(projectRoot, activityComponent, options = {}) {
  const parsed = parseActivityComponent(activityComponent);
  if (!parsed) {
    return {
      found: false,
      reason: 'missing-component',
      activities: [],
      message: stopMessage(activityComponent, 'missing-component'),
    };
  }

  const declarations = collectManifestPaths(projectRoot)
    .flatMap((manifestPath) => findActivityDeclarations(manifestPath, parsed.packageName))
    .filter((activity) => activity.fullName === parsed.className);
  const target = declarations[0];
  if (!target) {
    return {
      found: false,
      reason: 'not-found',
      activities: [],
      message: stopMessage(parsed.component, 'not-found'),
    };
  }
  if (!target.launcher && options.allowNonLauncher !== true) {
    return {
      found: false,
      reason: 'not-launcher',
      activities: [target],
      message: stopMessage(parsed.component, 'not-launcher'),
    };
  }

  return {
    found: true,
    reason: target.launcher ? null : 'existing',
    activities: [target],
    activity: target,
  };
}

function ensureConfiguredActivity(projectRoot, activityComponent, options = {}) {
  const result = inspectConfiguredActivity(projectRoot, activityComponent, options);
  if (!result.found) {
    const error = new Error(result.message);
    error.code = `INVALID_COMPOSE_ACTIVITY_${result.reason.toUpperCase()}`;
    throw error;
  }
  return result;
}

function ensureLandscapeActivity(projectRoot, activityComponent, options = {}) {
  const result = ensureConfiguredActivity(projectRoot, activityComponent, options);
  const manifestPath = result.activity.manifest;
  const parsed = parseActivityComponent(activityComponent);
  const orientationTarget = result.activity.type === 'activity-alias'
    ? normalizeActivityName(result.activity.targetActivity, parsed.packageName)
    : result.activity.fullName;
  if (!orientationTarget) {
    throw new Error(`COMPOSE_ACTIVITY=${activityComponent} 是缺少 targetActivity 的 Activity-alias，无法写入横屏配置，已停止后续操作。`);
  }
  const openingTag = findActivityOpeningTag(
    manifestPath,
    orientationTarget,
    parsed.packageName,
  );
  if (!openingTag) {
    throw new Error(`无法定位 ${activityComponent} 在源 AndroidManifest.xml 中的 Activity 声明，已停止后续操作。`);
  }

  const replacement = withLandscapeOrientation(openingTag.tag);

  if (replacement === openingTag.tag) return { ...result, changed: false };

  const xml = fs.readFileSync(manifestPath, 'utf8');
  const rawOpeningTag = xml.slice(openingTag.start, openingTag.end);
  const rawReplacement = withLandscapeOrientation(rawOpeningTag);
  const updated = xml.slice(0, openingTag.start) + rawReplacement + xml.slice(openingTag.end);
  fs.writeFileSync(manifestPath, updated);
  return { ...result, changed: true };
}

module.exports = {
  collectManifestPaths,
  findActivityDeclarations,
  inspectConfiguredActivity,
  ensureConfiguredActivity,
  ensureLandscapeActivity,
};
