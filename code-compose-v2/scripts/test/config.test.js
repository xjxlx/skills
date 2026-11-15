const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

test('默认工作目录按 PAGE_NAME 隔离，并位于调用项目内', () => {
  const projectRoot = path.resolve('/tmp/code-compose-v2-project');
  const oldProjectRoot = process.env.PROJECT_ROOT;
  const oldPageName = process.env.PAGE_NAME;
  const oldWorkDir = process.env.CODE_COMPOSE_V2_WORK_DIR;
  process.env.PROJECT_ROOT = projectRoot;
  process.env.PAGE_NAME = 'NavigationRevisePage';
  delete process.env.CODE_COMPOSE_V2_WORK_DIR;
  delete require.cache[require.resolve('../config')];

  const { TASK_ID, PROJECT_ROOT, WORK_DIR, TOOL_OUTPUT_DIR } = require('../config');
  assert.equal(PROJECT_ROOT, projectRoot);
  assert.equal(TASK_ID, 'NavigationRevisePage');
  assert.equal(WORK_DIR, path.join(projectRoot, '.code-compose-v2', 'NavigationRevisePage'));
  assert.equal(TOOL_OUTPUT_DIR, path.join(WORK_DIR, 'out'));

  if (oldProjectRoot === undefined) delete process.env.PROJECT_ROOT;
  else process.env.PROJECT_ROOT = oldProjectRoot;
  if (oldPageName === undefined) delete process.env.PAGE_NAME;
  else process.env.PAGE_NAME = oldPageName;
  if (oldWorkDir === undefined) delete process.env.CODE_COMPOSE_V2_WORK_DIR;
  else process.env.CODE_COMPOSE_V2_WORK_DIR = oldWorkDir;
  delete require.cache[require.resolve('../config')];
});

test('显式工作目录优先于 PAGE_NAME 默认隔离目录', () => {
  const projectRoot = path.resolve('/tmp/code-compose-v2-explicit-project');
  const explicitWorkDir = path.join(projectRoot, '.code-compose-v2', 'custom-task');
  const oldProjectRoot = process.env.PROJECT_ROOT;
  const oldPageName = process.env.PAGE_NAME;
  const oldWorkDir = process.env.CODE_COMPOSE_V2_WORK_DIR;
  process.env.PROJECT_ROOT = projectRoot;
  process.env.PAGE_NAME = 'NavigationRevisePage';
  process.env.CODE_COMPOSE_V2_WORK_DIR = explicitWorkDir;
  delete require.cache[require.resolve('../config')];

  const { WORK_DIR } = require('../config');
  assert.equal(WORK_DIR, explicitWorkDir);

  if (oldProjectRoot === undefined) delete process.env.PROJECT_ROOT;
  else process.env.PROJECT_ROOT = oldProjectRoot;
  if (oldPageName === undefined) delete process.env.PAGE_NAME;
  else process.env.PAGE_NAME = oldPageName;
  if (oldWorkDir === undefined) delete process.env.CODE_COMPOSE_V2_WORK_DIR;
  else process.env.CODE_COMPOSE_V2_WORK_DIR = oldWorkDir;
  delete require.cache[require.resolve('../config')];
});
