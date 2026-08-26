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

function readAttribute(source, attributeName) {
  const escapedName = attributeName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = source.match(new RegExp(`${escapedName}\\s*=\\s*["']([^"']+)["']`, 'i'));
  return match ? match[1] : null;
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

function findLauncherActivities(manifestPath) {
  const xml = fs.readFileSync(manifestPath, 'utf8').replace(/<!--[\s\S]*?-->/g, '');
  const activities = [];
  const activityBlocks = [
    ...xml.matchAll(/<(activity|activity-alias)\b(?![^>]*\/\s*>)[^>]*>[\s\S]*?<\/\1\s*>/gi),
    ...xml.matchAll(/<(activity|activity-alias)\b[^>]*\/\s*>/gi),
  ];

  for (const match of activityBlocks) {
    const block = match[0];
    if (!hasLauncherIntentFilter(block)) continue;
    const name = readAttribute(block, 'android:name');
    if (name) activities.push({ name, manifest: manifestPath });
  }

  return activities;
}

function inspectLauncherActivities(projectRoot) {
  const activities = collectManifestPaths(projectRoot).flatMap(findLauncherActivities);
  if (activities.length > 0) return { found: true, activities };

  return {
    found: false,
    activities: [],
    message: [
      '未检测到默认 Launcher Activity：AndroidManifest.xml 中没有同时包含',
      '<intent-filter>、<action android:name="android.intent.action.MAIN" />',
      '和 <category android:name="android.intent.category.LAUNCHER" /> 的 Activity。',
      '已停止后续 HTML/Compose 生成、编译、安装和验收操作。',
      '请先确认或提供项目现有的默认 Activity；禁止自动创建新的 Activity。',
    ].join('\n'),
  };
}

function ensureLauncherActivity(projectRoot) {
  const result = inspectLauncherActivities(projectRoot);
  if (!result.found) {
    const error = new Error(result.message);
    error.code = 'NO_LAUNCHER_ACTIVITY';
    throw error;
  }
  return result;
}

module.exports = {
  collectManifestPaths,
  findLauncherActivities,
  inspectLauncherActivities,
  ensureLauncherActivity,
};
