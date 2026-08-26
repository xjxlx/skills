const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  ensureLandscapeActivity,
  inspectConfiguredActivity,
} = require('../launcher-activity');

function createProject(manifest) {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'code-html-compose-orientation-'));
  const manifestPath = path.join(projectRoot, 'app', 'src', 'main', 'AndroidManifest.xml');
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, manifest);
  return { projectRoot, manifestPath };
}

const launcherManifest = (activity = '<activity android:name=".MainActivity">') => `
  <manifest package="com.example.app" xmlns:android="http://schemas.android.com/apk/res/android">
    <application>
      ${activity}
        <intent-filter>
          <action android:name="android.intent.action.MAIN" />
          <category android:name="android.intent.category.LAUNCHER" />
        </intent-filter>
      </activity>
    </application>
  </manifest>
`;

test('横向目标 Activity 缺少方向配置时只补写 landscape', () => {
  const { projectRoot, manifestPath } = createProject(`
    ${launcherManifest('<!-- a comment before the target -->\n      <activity android:name=".MainActivity">')}
  `);

  const result = ensureLandscapeActivity(projectRoot, 'com.example.app/.MainActivity');
  const manifest = fs.readFileSync(manifestPath, 'utf8');

  assert.equal(result.changed, true);
  assert.match(manifest, /<activity android:name="\.MainActivity" android:screenOrientation="landscape">/);
  assert.equal((manifest.match(/android:screenOrientation="landscape"/g) || []).length, 1);
});

test('目标 Activity 已配置其他方向时更新为 landscape，不创建新 Activity', () => {
  const { projectRoot, manifestPath } = createProject(
    launcherManifest('<activity android:name=".MainActivity" android:screenOrientation="portrait">'),
  );

  ensureLandscapeActivity(projectRoot, 'com.example.app/.MainActivity');
  const manifest = fs.readFileSync(manifestPath, 'utf8');

  assert.match(manifest, /android:screenOrientation="landscape"/);
  assert.doesNotMatch(manifest, /android:name="\.ComposeGeneratedActivity"/);
});

test('目标 Activity 不是 Launcher 时不修改 Manifest', () => {
  const { projectRoot, manifestPath } = createProject(`
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
  const before = fs.readFileSync(manifestPath, 'utf8');

  assert.throws(
    () => ensureLandscapeActivity(projectRoot, 'com.example.app/.PreviewActivity'),
    /MAIN 和 LAUNCHER/,
  );
  assert.equal(fs.readFileSync(manifestPath, 'utf8'), before);
  assert.equal(inspectConfiguredActivity(projectRoot, 'com.example.app/.PreviewActivity').found, false);
});

test('生成与验收脚本不修改模拟器窗口、系统栏或旋转状态', () => {
  for (const script of ['run.js', 'html-to-compose.js', 'compose-iterate.js', 'compose-shoot.js', 'compose-validate.js']) {
    const source = fs.readFileSync(path.join(__dirname, '..', script), 'utf8');
    assert.doesNotMatch(source, /user-rotation|user_rotation|rotate90|rotateEmulatorToLandscape/);
    assert.doesNotMatch(source, /\$\{ADB\} shell wm\s+(?:size|density)|\$\{ADB\} shell settings put global policy_control|\$\{ADB\} shell settings put system accelerometer_rotation|\$\{ADB\} shell settings put system user_rotation/);
  }
});
