const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

test('安装脚本必须执行 COMPOSE_INSTALL_COMMAND', (t) => {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'code-compose-v2-install-'));
  t.after(() => fs.rmSync(projectRoot, { recursive: true, force: true }));
  const command =
    `"${process.execPath}" -e "require('node:fs').writeFileSync('install-ran.txt', 'ok')"`;
  const result = spawnSync(process.execPath, [path.join(__dirname, '..', 'install-app.js')], {
    cwd: projectRoot,
    env: {
      ...process.env,
      PROJECT_ROOT: projectRoot,
      COMPOSE_INSTALL_COMMAND: command,
      CODE_COMPOSE_V2_WORK_DIR: path.join(projectRoot, '.code-compose-v2'),
    },
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.equal(fs.readFileSync(path.join(projectRoot, 'install-ran.txt'), 'utf8'), 'ok');
});
