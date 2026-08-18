const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

test('默认工作目录必须位于调用项目内，而不是个人技能目录', () => {
  const projectRoot = path.resolve('/tmp/code-html-compose-project');
  const oldProjectRoot = process.env.PROJECT_ROOT;
  const oldWorkDir = process.env.CODE_HTML_COMPOSE_WORK_DIR;
  process.env.PROJECT_ROOT = projectRoot;
  delete process.env.CODE_HTML_COMPOSE_WORK_DIR;
  delete require.cache[require.resolve('../config')];

  const { PROJECT_ROOT, WORK_DIR, TOOL_OUTPUT_DIR } = require('../config');
  assert.equal(PROJECT_ROOT, projectRoot);
  assert.equal(WORK_DIR, path.join(projectRoot, '.code-html-compose'));
  assert.equal(TOOL_OUTPUT_DIR, path.join(WORK_DIR, 'out'));

  if (oldProjectRoot === undefined) delete process.env.PROJECT_ROOT;
  else process.env.PROJECT_ROOT = oldProjectRoot;
  if (oldWorkDir === undefined) delete process.env.CODE_HTML_COMPOSE_WORK_DIR;
  else process.env.CODE_HTML_COMPOSE_WORK_DIR = oldWorkDir;
  delete require.cache[require.resolve('../config')];
});
