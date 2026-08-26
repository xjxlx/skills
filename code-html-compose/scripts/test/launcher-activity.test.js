const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const { inspectConfiguredActivity } = require('../launcher-activity');

function createProject(manifest) {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'code-html-compose-launcher-'));
  const manifestPath = path.join(projectRoot, 'app', 'src', 'main', 'AndroidManifest.xml');
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, manifest);
  return projectRoot;
}

test('生成布局的目标 Activity 自身含 MAIN 和 LAUNCHER 时允许继续', () => {
  const projectRoot = createProject(`
    <manifest package="com.example.app" xmlns:android="http://schemas.android.com/apk/res/android">
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

  const result = inspectConfiguredActivity(projectRoot, 'com.example.app/.MainActivity');

  assert.equal(result.found, true);
  assert.equal(result.activity.name, '.MainActivity');
  assert.equal(result.activity.manifest, path.join(projectRoot, 'app', 'src', 'main', 'AndroidManifest.xml'));
});

test('Manifest 未声明 package 时使用 COMPOSE_ACTIVITY 的包名解析相对类名', () => {
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

  assert.equal(inspectConfiguredActivity(projectRoot, 'com.example.app/.MainActivity').found, true);
});

test('其他 Activity 有 Launcher 也不能替代生成布局的目标 Activity', () => {
  const projectRoot = createProject(`
    <manifest package="com.example.app" xmlns:android="http://schemas.android.com/apk/res/android">
      <application>
        <activity android:name=".MainActivity">
          <intent-filter>
            <action android:name="android.intent.action.MAIN" />
            <category android:name="android.intent.category.LAUNCHER" />
          </intent-filter>
        </activity>
        <activity android:name=".PreviewActivity" android:exported="true" />
      </application>
    </manifest>
  `);

  const result = inspectConfiguredActivity(projectRoot, 'com.example.app/.PreviewActivity');

  assert.equal(result.found, false);
  assert.equal(result.reason, 'not-launcher');
  assert.match(result.message, /PreviewActivity/);
  assert.match(result.message, /MAIN/);
  assert.match(result.message, /LAUNCHER/);
  assert.match(result.message, /停止/);
  assert.match(result.message, /不要自动创建|禁止自动创建/);
});

test('被 XML 注释掉的 Launcher 配置不能被当成有效 Activity', () => {
  const projectRoot = createProject(`
    <manifest package="com.example.app" xmlns:android="http://schemas.android.com/apk/res/android">
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

  assert.equal(inspectConfiguredActivity(projectRoot, 'com.example.app/.OldActivity').found, false);
});

test('总入口目标 Activity 缺少 Launcher 时必须在解压前停止且不产生工作目录', () => {
  const projectRoot = createProject(`
    <manifest package="com.example.app" xmlns:android="http://schemas.android.com/apk/res/android">
      <application>
        <activity android:name=".MainActivity">
          <intent-filter>
            <action android:name="android.intent.action.MAIN" />
            <category android:name="android.intent.category.LAUNCHER" />
          </intent-filter>
        </activity>
        <activity android:name=".PreviewActivity" />
      </application>
    </manifest>
  `);

  const result = spawnSync(process.execPath, [path.join(__dirname, '..', 'run.js')], {
    cwd: path.join(__dirname, '..'),
    env: {
      ...process.env,
      PROJECT_ROOT: projectRoot,
      COMPOSE_ACTIVITY: 'com.example.app/.PreviewActivity',
    },
    encoding: 'utf8',
  });

  assert.equal(result.status, 1);
  assert.match(`${result.stdout}\n${result.stderr}`, /已停止后续/);
  assert.match(`${result.stdout}\n${result.stderr}`, /禁止自动创建新的 Activity/);
  assert.equal(fs.existsSync(path.join(projectRoot, '.code-html-compose')), false);
});
