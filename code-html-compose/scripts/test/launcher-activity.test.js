const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const { inspectLauncherActivities } = require('../launcher-activity');

function createProject(manifest) {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'code-html-compose-launcher-'));
  const manifestPath = path.join(projectRoot, 'app', 'src', 'main', 'AndroidManifest.xml');
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, manifest);
  return projectRoot;
}

test('检测到 MAIN 和 LAUNCHER 的默认 Activity 时允许继续', () => {
  const projectRoot = createProject(`
    <manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <application>
        <activity android:name=".MainActivity">
          <intent-filter>
            <action android:name="android.intent.action.MAIN" />
            <category android:name="android.intent.category.LAUNCHER" />
          </intent-filter>
        </activity>
      </application>
    </manifest>
  `);

  assert.deepEqual(inspectLauncherActivities(projectRoot), {
    found: true,
    activities: [{ name: '.MainActivity', manifest: path.join(projectRoot, 'app', 'src', 'main', 'AndroidManifest.xml') }],
  });
});

test('没有默认 Launcher Activity 时必须阻断，不得建议或创建新 Activity', () => {
  const projectRoot = createProject(`
    <manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <application>
        <activity android:name=".PreviewActivity" android:exported="true" />
      </application>
    </manifest>
  `);

  const result = inspectLauncherActivities(projectRoot);

  assert.equal(result.found, false);
  assert.deepEqual(result.activities, []);
  assert.match(result.message, /MAIN/);
  assert.match(result.message, /LAUNCHER/);
  assert.match(result.message, /停止/);
  assert.match(result.message, /不要自动创建|禁止自动创建/);
});

test('被 XML 注释掉的 Launcher 配置不能被当成有效 Activity', () => {
  const projectRoot = createProject(`
    <manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <application>
        <!--
        <activity android:name=".OldActivity">
          <intent-filter>
            <action android:name="android.intent.action.MAIN" />
            <category android:name="android.intent.category.LAUNCHER" />
          </intent-filter>
        </activity>
        -->
      </application>
    </manifest>
  `);

  assert.equal(inspectLauncherActivities(projectRoot).found, false);
});

test('总入口缺少 Launcher 时必须在解压前停止且不产生工作目录', () => {
  const projectRoot = createProject(`
    <manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <application />
    </manifest>
  `);

  const result = spawnSync(process.execPath, [path.join(__dirname, '..', 'run.js')], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, PROJECT_ROOT: projectRoot },
    encoding: 'utf8',
  });

  assert.equal(result.status, 1);
  assert.match(`${result.stdout}\n${result.stderr}`, /已停止后续/);
  assert.match(`${result.stdout}\n${result.stderr}`, /禁止自动创建新的 Activity/);
  assert.equal(fs.existsSync(path.join(projectRoot, '.code-html-compose')), false);
});
