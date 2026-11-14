const fs = require('node:fs');
const path = require('node:path');
const {
  COMPOSE_ACTIVITY,
  COMPOSE_ACTIVITY_MODE,
  PROJECT_ROOT,
  TOOL_OUTPUT_DIR,
} = require('./config');
const { ensureLandscapeActivity } = require('./launcher-activity');

const RUNTIME_CONTEXT_PATH = path.join(TOOL_OUTPUT_DIR, 'runtime-context.json');

/**
 * 创建运行上下文。
 * Activity 与方向只在顶层准备一次，后续生成和验证直接读取结果。
 */
function createRuntimeContext(projectRoot = PROJECT_ROOT, activity = COMPOSE_ACTIVITY) {
  const result = ensureLandscapeActivity(projectRoot, activity, {
    allowNonLauncher: COMPOSE_ACTIVITY_MODE === 'existing',
  });
  const context = {
    activity,
    manifest: result.activity.manifest,
    orientationChanged: result.changed,
    generatedAt: new Date().toISOString(),
  };
  fs.mkdirSync(TOOL_OUTPUT_DIR, { recursive: true });
  fs.writeFileSync(RUNTIME_CONTEXT_PATH, JSON.stringify(context, null, 2) + '\n');
  return context;
}

/**
 * 读取顶层已经确认过的 Activity 信息。
 */
function loadRuntimeContext() {
  if (!fs.existsSync(RUNTIME_CONTEXT_PATH)) return null;
  const context = JSON.parse(fs.readFileSync(RUNTIME_CONTEXT_PATH, 'utf8'));
  if (!context.activity) {
    throw new Error(`运行上下文缺少 activity：${RUNTIME_CONTEXT_PATH}`);
  }
  return context;
}

/**
 * 直接调用子脚本时复用上下文；只有首次调用才扫描 Manifest。
 */
function loadOrCreateRuntimeContext() {
  return loadRuntimeContext() || createRuntimeContext();
}

module.exports = {
  RUNTIME_CONTEXT_PATH,
  createRuntimeContext,
  loadOrCreateRuntimeContext,
  loadRuntimeContext,
};
