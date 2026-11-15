const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

test('默认工作目录必须位于调用项目内，而不是个人技能目录', () => {
  const projectRoot = path.resolve('/tmp/code-compose-v2-project');
  const oldProjectRoot = process.env.PROJECT_ROOT;
  const oldWorkDir = process.env.CODE_COMPOSE_V2_WORK_DIR;
  process.env.PROJECT_ROOT = projectRoot;
  delete process.env.CODE_COMPOSE_V2_WORK_DIR;
  delete require.cache[require.resolve('../config')];

  const { PROJECT_ROOT, WORK_DIR, TOOL_OUTPUT_DIR } = require('../config');
  assert.equal(PROJECT_ROOT, projectRoot);
  assert.equal(WORK_DIR, path.join(projectRoot, '.code-compose-v2'));
  assert.equal(TOOL_OUTPUT_DIR, path.join(WORK_DIR, 'out'));

  if (oldProjectRoot === undefined) delete process.env.PROJECT_ROOT;
  else process.env.PROJECT_ROOT = oldProjectRoot;
  if (oldWorkDir === undefined) delete process.env.CODE_COMPOSE_V2_WORK_DIR;
  else process.env.CODE_COMPOSE_V2_WORK_DIR = oldWorkDir;
  delete require.cache[require.resolve('../config')];
});

test('命令行安装和页面路由参数必须可通过环境变量配置', () => {
  const oldInstall = process.env.COMPOSE_INSTALL_COMMAND;
  const oldStartArgs = process.env.COMPOSE_START_ARGS;
  process.env.COMPOSE_INSTALL_COMMAND = './gradlew :app:installDebug';
  process.env.COMPOSE_START_ARGS = '--es codeComposePage NavigationRevisePage';
  delete require.cache[require.resolve('../config')];

  const { COMPOSE_INSTALL_COMMAND, COMPOSE_START_ARGS } = require('../config');
  assert.equal(COMPOSE_INSTALL_COMMAND, './gradlew :app:installDebug');
  assert.equal(COMPOSE_START_ARGS, '--es codeComposePage NavigationRevisePage');

  if (oldInstall === undefined) delete process.env.COMPOSE_INSTALL_COMMAND;
  else process.env.COMPOSE_INSTALL_COMMAND = oldInstall;
  if (oldStartArgs === undefined) delete process.env.COMPOSE_START_ARGS;
  else process.env.COMPOSE_START_ARGS = oldStartArgs;
  delete require.cache[require.resolve('../config')];
});
