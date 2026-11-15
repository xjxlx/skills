#!/usr/bin/env node
/**
 * 执行项目配置的 Debug 安装命令。
 *
 * 构建和安装与页面验收分离：本脚本只负责构建部署，
 * compose-validate.js 继续只负责 ADB 启动和视觉验收。
 */
const { execSync } = require('node:child_process');
const {
  COMPOSE_INSTALL_COMMAND,
  PROJECT_ROOT,
} = require('./config');

function main() {
  console.log(`项目根目录：${PROJECT_ROOT}`);
  console.log(`安装命令：${COMPOSE_INSTALL_COMMAND}`);
  execSync(COMPOSE_INSTALL_COMMAND, {
    cwd: PROJECT_ROOT,
    env: process.env,
    shell: true,
    stdio: 'inherit',
  });
}

try {
  main();
} catch (error) {
  console.error(`安装失败：${error.message}`);
  process.exitCode = 1;
}
