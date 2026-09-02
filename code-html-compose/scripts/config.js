const path = require('node:path');

function resolveFromProject(value, projectRoot) {
  if (!value) return undefined;
  return path.isAbsolute(value) ? path.resolve(value) : path.resolve(projectRoot, value);
}

const PROJECT_ROOT = path.resolve(process.env.PROJECT_ROOT || process.cwd());
const WORK_DIR = resolveFromProject(
  process.env.CODE_HTML_COMPOSE_WORK_DIR,
  PROJECT_ROOT,
) || path.join(PROJECT_ROOT, '.code-html-compose');
const TOOL_OUTPUT_DIR = path.join(WORK_DIR, 'out');
const EXPERIENCE_PATH = path.join(WORK_DIR, 'experience.md');
const EXPERIENCE_RULES_PATH = path.join(WORK_DIR, 'experience-rules.json');
const DESIGN_DIR = process.env.DESIGN_DIR && path.resolve(process.env.DESIGN_DIR);
const ADB = `adb -s ${process.env.ADB_SERIAL || 'emulator-5554'}`;

function requiredSetting(name, value) {
  if (value) return value;
  throw new Error(`缺少 ${name}。请先按 references/configuration.md 配置后再执行。`);
}

module.exports = {
  PROJECT_ROOT,
  WORK_DIR,
  TOOL_OUTPUT_DIR,
  EXPERIENCE_PATH,
  EXPERIENCE_RULES_PATH,
  DESIGN_DIR,
  ADB,
  CHROME_BIN: process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  COMPOSE_ACTIVITY: process.env.COMPOSE_ACTIVITY,
  COMPOSE_ACTIVITY_MODE: process.env.COMPOSE_ACTIVITY_MODE || 'launcher',
  COMPOSE_KOTLIN_DIR: resolveFromProject(process.env.COMPOSE_KOTLIN_DIR, PROJECT_ROOT),
  COMPOSE_RES_DIR: resolveFromProject(process.env.COMPOSE_RES_DIR, PROJECT_ROOT),
  COMPOSE_PACKAGE: process.env.COMPOSE_PACKAGE,
  COMPOSE_R_IMPORT: process.env.COMPOSE_R_IMPORT,
  COMPOSE_IMAGE_IMPORTS: process.env.COMPOSE_IMAGE_IMPORTS,
  COMPOSE_REFERENCE_MANIFEST: resolveFromProject(process.env.COMPOSE_REFERENCE_MANIFEST, PROJECT_ROOT),
  COMPOSE_RESOURCE_MAP: resolveFromProject(process.env.COMPOSE_RESOURCE_MAP, PROJECT_ROOT),
  COMPOSE_RESOURCE_MODE: process.env.COMPOSE_RESOURCE_MODE || 'reuse',
  APK_PATH: resolveFromProject(process.env.APK_PATH, PROJECT_ROOT),
  requiredSetting,
};
