const { execSync } = require('node:child_process');

/**
 * 让 Android 模拟器真实进入横屏，截图保持设备返回的原始方向。
 * ROTATION_90（1）对应标准 Android 模拟器的横屏方向。
 */
function rotateEmulatorToLandscape(adb, run = execSync) {
  run(`${adb} shell cmd window user-rotation lock 1`, { shell: true });
}

module.exports = { rotateEmulatorToLandscape };
