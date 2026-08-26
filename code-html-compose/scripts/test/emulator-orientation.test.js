const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { rotateEmulatorToLandscape } = require('../emulator-orientation');

test('横向验收通过 ADB 让模拟器进入横屏，不执行截图旋转', () => {
  const commands = [];
  rotateEmulatorToLandscape('adb -s emulator-5554', (command, options) => {
    commands.push({ command, options });
  });

  assert.deepEqual(commands, [{
    command: 'adb -s emulator-5554 shell cmd window user-rotation lock 1',
    options: { shell: true },
  }]);
});

test('截图与结构验收脚本不包含手动旋转截图逻辑', () => {
  for (const script of ['compose-shoot.js', 'compose-validate.js']) {
    const source = fs.readFileSync(path.join(__dirname, '..', script), 'utf8');
    assert.doesNotMatch(source, /function rotate90/);
    assert.doesNotMatch(source, /rotate90\(/);
    assert.doesNotMatch(source, /user_rotation\s+0/);
  }
});
