const fs = require('node:fs');
const path = require('node:path');
const {
  COMPOSE_ACTIVITY,
  COMPOSE_ACTIVITY_MODE,
  PAGE_NAME,
  PROJECT_ROOT,
  TASK_ID,
  TOOL_OUTPUT_DIR,
} = require('./config');
const {
  discoverDefaultTestActivity,
  ensureLandscapeActivity,
  parseActivityComponent,
} = require('./launcher-activity');

const RUNTIME_CONTEXT_PATH = path.join(TOOL_OUTPUT_DIR, 'runtime-context.json');

/**
 * 创建运行上下文。
 * 首次解析并缓存应用包名、Activity 组件和方向，后续生成与验证直接复用。
 */
function createRuntimeContext(projectRoot = PROJECT_ROOT, activity = COMPOSE_ACTIVITY) {
  const resolvedActivity = activity || discoverDefaultTestActivity(projectRoot).component;
  const parsed = parseActivityComponent(resolvedActivity);
  if (!parsed) {
    throw new Error(`无效的 COMPOSE_ACTIVITY=${resolvedActivity}，请使用 package/.Activity 或 package/full.Activity 格式。`);
  }
  const result = ensureLandscapeActivity(projectRoot, resolvedActivity, {
    allowNonLauncher: COMPOSE_ACTIVITY_MODE === 'existing',
  });
  const context = {
    taskId: TASK_ID,
    pageName: PAGE_NAME,
    packageName: parsed.packageName,
    activity: resolvedActivity,
    activityClass: parsed.className,
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
  if (context.taskId && context.taskId !== TASK_ID) {
    throw new Error(
      `运行上下文任务不匹配：期望 ${TASK_ID}，实际 ${context.taskId}。请使用对应的 CODE_COMPOSE_V2_WORK_DIR。`,
    );
  }
  if (!context.packageName || !context.activityClass) {
    const parsed = parseActivityComponent(context.activity);
    if (!parsed) {
      throw new Error(`运行上下文中的 activity 无效：${context.activity}`);
    }
    context.packageName = context.packageName || parsed.packageName;
    context.activityClass = context.activityClass || parsed.className;
  }
  return context;
}

/**
 * 直接调用子脚本时复用上下文；只有首次调用才扫描 Manifest。
 */
function loadOrCreateRuntimeContext(activityOverride) {
  const existing = loadRuntimeContext();
  if (activityOverride) {
    const parsed = parseActivityComponent(activityOverride);
    if (!parsed) {
      throw new Error(`无效的 Activity=${activityOverride}，请使用 package/.Activity 或 package/full.Activity 格式。`);
    }
    if (!existing) return createRuntimeContext(PROJECT_ROOT, parsed.component);
    return {
      ...existing,
      packageName: parsed.packageName,
      activity: parsed.component,
      activityClass: parsed.className,
      activityOverride: true,
    };
  }

  const requested = COMPOSE_ACTIVITY;
  if (!requested) return existing || createRuntimeContext();
  const parsed = parseActivityComponent(requested);
  if (!parsed) {
    throw new Error(`无效的 COMPOSE_ACTIVITY=${requested}，请使用 package/.Activity 或 package/full.Activity 格式。`);
  }
  if (existing && existing.activity === parsed.component) return existing;
  return createRuntimeContext(PROJECT_ROOT, parsed.component);
}

module.exports = {
  RUNTIME_CONTEXT_PATH,
  createRuntimeContext,
  loadOrCreateRuntimeContext,
  loadRuntimeContext,
};
