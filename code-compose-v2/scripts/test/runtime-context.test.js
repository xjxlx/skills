const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

function createProject() {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'code-compose-v2-context-'));
  const moduleDir = path.join(projectRoot, 'app');
  const manifestPath = path.join(moduleDir, 'src', 'main', 'AndroidManifest.xml');
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(path.join(moduleDir, 'build.gradle.kts'), `
    plugins { id("com.android.application") }
    android {
      namespace = "com.example.app"
      defaultConfig { applicationId = "com.example.app.debug" }
    }
  `);
  fs.writeFileSync(manifestPath, `
    <manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <application>
        <activity android:name=".compose.activity.TestActivity" android:exported="true" />
      </application>
    </manifest>
  `);
  return projectRoot;
}

test('首次运行缓存 applicationId 和 TestActivity 完整类名', () => {
  const projectRoot = createProject();
  const skillTools = path.join(__dirname, '..');
  const script = `
    const fs = require('node:fs');
    const runtime = require(${JSON.stringify(path.join(skillTools, 'runtime-context.js'))});
    runtime.createRuntimeContext(process.env.PROJECT_ROOT);
    process.stdout.write(fs.readFileSync(runtime.RUNTIME_CONTEXT_PATH, 'utf8'));
  `;
  const result = spawnSync(process.execPath, ['-e', script], {
    cwd: projectRoot,
    env: {
      ...process.env,
      PROJECT_ROOT: projectRoot,
      CODE_COMPOSE_V2_WORK_DIR: path.join(projectRoot, '.code-compose-v2'),
      COMPOSE_ACTIVITY: '',
      COMPOSE_ACTIVITY_MODE: 'existing',
    },
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const context = JSON.parse(result.stdout);
  assert.equal(context.packageName, 'com.example.app.debug');
  assert.equal(context.activityClass, 'com.example.app.compose.activity.TestActivity');
  assert.equal(
    context.activity,
    'com.example.app.debug/com.example.app.compose.activity.TestActivity',
  );
});

test('同一项目已有上下文时直接复用缓存，不重新扫描 Manifest', () => {
  const projectRoot = createProject();
  const manifestPath = path.join(projectRoot, 'app', 'src', 'main', 'AndroidManifest.xml');
  const skillTools = path.join(__dirname, '..');
  const script = `
    const fs = require('node:fs');
    const runtime = require(${JSON.stringify(path.join(skillTools, 'runtime-context.js'))});
    runtime.createRuntimeContext(process.env.PROJECT_ROOT);
    fs.writeFileSync(process.env.TARGET_MANIFEST, '<manifest />');
    const cached = runtime.loadOrCreateRuntimeContext();
    process.stdout.write(JSON.stringify(cached));
  `;
  const result = spawnSync(process.execPath, ['-e', script], {
    cwd: projectRoot,
    env: {
      ...process.env,
      PROJECT_ROOT: projectRoot,
      TARGET_MANIFEST: manifestPath,
      CODE_COMPOSE_V2_WORK_DIR: path.join(projectRoot, '.code-compose-v2'),
      COMPOSE_ACTIVITY: '',
      COMPOSE_ACTIVITY_MODE: 'existing',
    },
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const context = JSON.parse(result.stdout);
  assert.equal(context.packageName, 'com.example.app.debug');
  assert.equal(
    context.activity,
    'com.example.app.debug/com.example.app.compose.activity.TestActivity',
  );
});

test('命令参数指定页面只覆盖本次运行，不污染默认 TestActivity 缓存', () => {
  const projectRoot = createProject();
  const skillTools = path.join(__dirname, '..');
  const script = `
    const runtime = require(${JSON.stringify(path.join(skillTools, 'runtime-context.js'))});
    runtime.createRuntimeContext(process.env.PROJECT_ROOT);
    const override = runtime.loadOrCreateRuntimeContext(
      'com.example.app.debug/com.example.app.SpecificTestActivity',
    );
    const persisted = runtime.loadRuntimeContext();
    process.stdout.write(JSON.stringify({ override, persisted }));
  `;
  const result = spawnSync(process.execPath, ['-e', script], {
    cwd: projectRoot,
    env: {
      ...process.env,
      PROJECT_ROOT: projectRoot,
      CODE_COMPOSE_V2_WORK_DIR: path.join(projectRoot, '.code-compose-v2'),
      COMPOSE_ACTIVITY: '',
      COMPOSE_ACTIVITY_MODE: 'existing',
    },
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const output = JSON.parse(result.stdout);
  assert.equal(
    output.override.activity,
    'com.example.app.debug/com.example.app.SpecificTestActivity',
  );
  assert.equal(
    output.persisted.activity,
    'com.example.app.debug/com.example.app.compose.activity.TestActivity',
  );
});
