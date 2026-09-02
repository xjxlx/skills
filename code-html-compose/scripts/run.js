/**
 * code-html-compose 总编排入口（步骤 1-9）
 *
 * 用法：node run.js <蓝湖导出zip路径>
 *
 * 流程：
 *   0. 校验 COMPOSE_ACTIVITY 指向的现有 Activity 自身包含 MAIN + LAUNCHER
 *   1. 接收 zip 包（无则提示提供）
 *   2. 解压到 ~/Downloads（unzip-to-downloads.js），定位含 index.html 的设计源目录 DESIGN_DIR
 *   3. 读取 DESIGN_DIR（含 index.html + css + img 资源）
 *   4. 解析 index.html（normalize.js：DOM 采集 → semantic.json）
 *   5. 生成 new.html（normalize.js：规范化 HTML）
 *   6. 像素对比 + 迭代自修正，直到相似度 > 99.95%（iterate.js）
 *   7. 收集失败经验到 experience.md（iterate.js 内完成）
 *   8. 产物（new.html / new.png / 对比图 / 报告）更新到 .code-html-compose/run-<时间戳>/
 *   9. 脚本生成 Compose 布局（html-to-compose.js：semantic.json → Test1Page.kt + 复制 res 图片）
 */
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const {
  COMPOSE_ACTIVITY,
  COMPOSE_ACTIVITY_MODE,
  COMPOSE_REFERENCE_MANIFEST,
  PROJECT_ROOT,
  WORK_DIR,
} = require('./config');
const { ensureLandscapeActivity } = require('./launcher-activity');
const { loadReferenceManifest } = require('./reference-manifest');

const TOOLS = __dirname;
const BASE_ENV = {
  ...process.env,
  PROJECT_ROOT,
  CODE_HTML_COMPOSE_WORK_DIR: WORK_DIR,
};

function run(cmd, env = {}) {
  return execSync(cmd, { cwd: TOOLS, stdio: 'inherit', env: { ...BASE_ENV, ...env } });
}

function main() {
  try {
    ensureLandscapeActivity(PROJECT_ROOT, COMPOSE_ACTIVITY, {
      allowNonLauncher: COMPOSE_ACTIVITY_MODE === 'existing',
    });
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

  // 步骤 4-6-7：解析 → 生成 new.html → 像素对比 + 迭代收敛 >99.95% → 收集经验
  console.log('\n===== 步骤 4-7：解析并生成，迭代至相似度 > 99.95% =====');
  run('node iterate.js', { DESIGN_DIR });

  // 步骤 8：产物已由 compare.js 更新到 .code-html-compose/run-<时间戳>/
  console.log('\n===== 步骤 8：产物已更新 =====');
  console.log(`产物目录：${path.join(WORK_DIR, 'run-*')}`);
  console.log(`经验库：${path.join(WORK_DIR, 'experience.md')}`);

  // 步骤 9-10：Compose 生成 + 自动化收敛循环
  // （生成 → 编译打包 → 安装 → 截图对比 → 换策略直到达标/轮次上限，见 compose-iterate.js）
  console.log('\n===== 步骤 9-10：Compose 生成 + 自动化收敛 =====');
  run('node compose-iterate.js', { DESIGN_DIR });
}

main();
