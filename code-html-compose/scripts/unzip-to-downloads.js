/**
 * 步骤 1-3：接收 zip → 解压到下载目录 → 定位含 index.html 的设计源目录
 * 用法：node unzip-to-downloads.js <zipPath>
 * 输出：打印 DESIGN_DIR（直接包含 index.html 的目录），供后续脚本通过环境变量使用。
 */
const { execSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const DOWNLOADS = path.join(os.homedir(), 'Downloads');

function findIndexDir(startDir) {
  // 在 startDir 内递归查找 index.html 或 .code-lanhu-index.html，返回其所在目录
  const stack = [startDir];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { continue; }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        stack.push(full);
      } else if (/^\.?code-lanhu-index\.html$/.test(e.name) || e.name === 'index.html') {
        return dir;
      }
    }
  }
  return null;
}

function main() {
  const zipPath = process.argv[2] || process.env.ZIP_PATH;
  if (!zipPath) {
    console.error('缺少 zip 包路径。用法：node unzip-to-downloads.js <zipPath>');
    process.exit(1);
  }
  if (!fs.existsSync(zipPath)) {
    console.error(`zip 包不存在：${zipPath}`);
    process.exit(1);
  }
  const abs = path.resolve(zipPath);
  const base = path.basename(abs, path.extname(abs));
  // 解压到下载目录下的同名目录（带时间戳避免冲突）
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const destDir = path.join(DOWNLOADS, `${base}-extracted-${ts}`);
  fs.mkdirSync(destDir, { recursive: true });

  console.log(`解压 ${abs} → ${destDir}`);
  execSync(`unzip -o -q "${abs}" -d "${destDir}"`, { stdio: 'inherit' });

  const designDir = findIndexDir(destDir);
  if (!designDir) {
    console.error(`在 ${destDir} 中未找到 index.html，请确认 zip 是蓝湖导出的 HTML 包。`);
    process.exit(1);
  }
  console.log(`DESIGN_DIR=${designDir}`);
  console.log(`入口文件：${path.join(designDir, fs.readdirSync(designDir).find(f => /^\.?code-lanhu-index\.html$/.test(f) || f === 'index.html'))}`);
}

main();