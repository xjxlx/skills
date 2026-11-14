/**
 * code-compose-v2 总编排入口。
 *
 * 用法：node run.js <蓝湖导出zip路径>
 *
 * 流程：
 *   1. 扫描一次 Manifest，确认全屏测试 Activity 和横屏配置
 *   2. 解压设计包并定位 index.html
 *   3. 解析一次 DOM，输出 semantic.json 和 original.png
 *   4. 根据 HTML 布局参数直接生成 Compose 页面
 *   5. 提示通过 IDE Running 刷新应用，再执行 compose-validate.js
 */
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const {
  COMPOSE_REFERENCE_MANIFEST,
  PROJECT_ROOT,
  WORK_DIR,
} = require('./config');
const { loadReferenceManifest } = require('./reference-manifest');
const { createRuntimeContext } = require('./runtime-context');

const TOOLS = __dirname;
const BASE_ENV = {
  ...process.env,
  PROJECT_ROOT,
  CODE_COMPOSE_V2_WORK_DIR: WORK_DIR,
};

function run(cmd, env = {}) {
  return execSync(cmd, { cwd: TOOLS, stdio: 'inherit', env: { ...BASE_ENV, ...env } });
}

function main() {
  try {
    createRuntimeContext();
  } catch (error) {
    console.error(`\n${error.message}`);
    process.exit(1);
  }

  const zipPath = process.argv[2] || process.env.ZIP_PATH;
  if (!zipPath) {
    console.error('步骤1：缺少 zip 包。请先提供蓝湖导出的 HTML 压缩包，再执行：');
    console.error('  node run.js <zip路径>');
    process.exit(1);
  }
  if (!fs.existsSync(zipPath)) {
    console.error(`zip 包不存在：${zipPath}`);
    process.exit(1);
  }

  if (COMPOSE_REFERENCE_MANIFEST) {
    let referenceManifest;
    try {
      referenceManifest = loadReferenceManifest(COMPOSE_REFERENCE_MANIFEST, PROJECT_ROOT);
    } catch (error) {
      console.error(`参考清单无效：${error.message}`);
      process.exit(1);
    }
    if (path.resolve(referenceManifest.primary.zip) !== path.resolve(zipPath)) {
      console.error('参考清单的 primary zip 必须与本次 run.js 输入的主页面 zip 相同。');
      process.exit(1);
    }
    console.log(`参考角色：主页面 + ${referenceManifest.fragments.length} 个行为状态片段`);
  }

  // 步骤 1-3：验证 zip → 解压到下载目录 → 定位设计源目录
  console.log('\n===== 步骤 1-3：接收 zip 并解压到下载目录，定位设计源 =====');
  const out = execSync(`node unzip-to-downloads.js "${zipPath}"`, { cwd: TOOLS, encoding: 'utf8', env: BASE_ENV });
  const m = out.match(/DESIGN_DIR=(.+)/);
  if (!m) {
    console.error('未能解析出 DESIGN_DIR，流程终止。');
    process.exit(1);
  }
  const DESIGN_DIR = m[1].trim();
  console.log(`设计源目录：${DESIGN_DIR}`);

  console.log('\n===== 步骤 4：解析 HTML 布局并生成语义树 =====');
  run('node normalize.js', { DESIGN_DIR });

  console.log('\n===== 步骤 5：生成 Compose 页面 =====');
  run('node html-to-compose.js', { DESIGN_DIR });

  console.log('\n===== 生成完成 =====');
  console.log('请先在 IDE 中 Running 或 Apply Changes 刷新已安装应用。');
  console.log('应用显示最新页面后执行：');
  console.log(`  node ${path.join(TOOLS, 'compose-validate.js')}`);
  console.log('验证低于 95% 时，根据 compose-structure-report.json 修正生成逻辑后重复运行和验证。');
}

main();
