/**
 * code-html-compose 步骤 9-10（方案 A）：Compose 生成 + 结构校验验收。
 *
 * 串起整条 Compose 链路并自动验收，替代旧的"整页像素收敛"流程：
 *   1. 生成 Compose（html-to-compose.js，高保真基线，确定性生成）
 *   2. 编译打包 debug APK（assembleDebug，含最新 Test1Page.kt）
 *   3. 安装到模拟器（adb install -r）
 *   4. 结构校验 + 局部抽查（compose-validate.js，元素边界 + 关键区块像素抽查）
 *   5. 读 compose-structure-report.json 判定
 *   if 结构通过率 ≥ 阈值 且 抽查通过率 ≥ 阈值: 验收通过，退出
 *   否则输出失败元素清单供人工/脚本修正（html-to-compose.js 已确定性生成，不再做策略回滚）
 *
 * 验收标准（方案 A）：
 *   - 结构校验：uiautomator 提取各 testTag("e<domIndex>") 实际 bounds，与语义树 rect 做容差比对。
 *     通过率默认 95%（VALIDATE_STRUCT_PASS）。
 *   - 局部抽查：对若干关键元素区块裁剪设计稿与 Compose 截图做像素对比，通过率默认 80%
 *     （VALIDATE_SPOT_PASS），区块平均色差阈值 0.18（VALIDATE_SPOT_DIST）。
 *
 * 前置：目标模拟器已启动；ADB 目标由 ADB_SERIAL 配置，验收尺寸从当前 semantic.json 动态读取。
 * 用法：node compose-iterate.js [DESIGN_DIR]
 */
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { shouldAcceptReport } = require('./compose-validation-core');
const { recordExperienceEvent } = require('./compose-generation-rules');
const {
  ADB,
  APK_PATH,
  EXPERIENCE_PATH,
  EXPERIENCE_RULES_PATH,
  PROJECT_ROOT,
  TOOL_OUTPUT_DIR,
  WORK_DIR,
} = require('./config');

const TOOLS = __dirname;
const OUT_DIR = TOOL_OUTPUT_DIR;
const EXPERIENCE = EXPERIENCE_PATH;
const EXPERIENCE_RULES = EXPERIENCE_RULES_PATH;
const REPORT = path.join(OUT_DIR, 'compose-structure-report.json');
const APK = APK_PATH || path.join(PROJECT_ROOT, 'app/build/outputs/apk/debug/app-debug.apk');
const BASE_ENV = { ...process.env, PROJECT_ROOT, CODE_HTML_COMPOSE_WORK_DIR: WORK_DIR };

// 验收阈值（与 compose-validate.js 保持一致，可用环境变量覆盖）
const STRUCT_PASS = parseFloat(process.env.VALIDATE_STRUCT_PASS || '0.95');
const SPOT_PASS = parseFloat(process.env.VALIDATE_SPOT_PASS || '0.8');

function recordScriptFailure(type, error, details = {}) {
  recordExperienceEvent(EXPERIENCE_RULES, {
    type,
    ruleIds: [],
    summary: {
      message: String(error && error.message || error).slice(0, 500),
      ...details,
    },
  });
}

function run(cmd, env = {}) {
  try {
    return execSync(cmd, { cwd: TOOLS, stdio: 'inherit', env: { ...BASE_ENV, ...env } });
  } catch (error) {
    recordScriptFailure('compose-script-error', error, { command: cmd });
    throw error;
  }
}

// 编译 + 打包 debug APK（含最新生成的 Test1Page.kt）。失败则中断。
function build() {
  console.log('\n  [compose-iterate] 编译打包 debug APK ...');
  try {
    execSync('./gradlew :app:assembleDebug --console=plain', {
      cwd: PROJECT_ROOT,
      stdio: 'inherit',
      env: process.env,
    });
  } catch (e) {
    recordScriptFailure('compose-build-failure', e, { command: './gradlew :app:assembleDebug --console=plain' });
    console.error('\n  [compose-iterate] Gradle 构建失败，请检查 Test1Page.kt 编译错误后重试。');
    process.exit(1);
  }
}

function install() {
  console.log('\n  [compose-iterate] 安装到模拟器 ...');
  try {
    execSync(`${ADB} install -r "${APK}"`, { stdio: 'inherit' });
  } catch (error) {
    recordScriptFailure('compose-install-failure', error, { apk: APK });
    throw error;
  }
}

function inferRuleIds(report) {
  const ruleIds = [];
  const failed = (report.structure && report.structure.checks || []).filter((check) => !check.passed);
  const failedReasons = failed.map((check) => check.reason || '').join(' ');
  const hasListGeometryFailure = failed.some((check) => [17, 18, 19, 20, 24, 34, 38, 43].includes(check.domIndex));
  if (hasListGeometryFailure || /size|bounds|not-found/.test(failedReasons)) {
    ruleIds.push('uniform-list-card-geometry', 'list-viewport-clips-and-pads');
  }
  if (failed.some((check) => check.domIndex === 38)) {
    ruleIds.push('card-exclusive-slots-stay-in-item');
  }
  const spotText = (report.spot && report.spot.checks || [])
    .map((check) => `${check.role || ''} ${check.reason || ''}`)
    .join(' ');
  if (/image|arrow|overlay|视觉|reference/i.test(`${failedReasons} ${spotText}`)) {
    ruleIds.push('reject-reference-unsupported-images');
  }
  return [...new Set(ruleIds)];
}

function appendExperience(report) {
  const failedStruct = (report.structure.checks || []).filter((c) => !c.passed).length;
  const ruleIds = inferRuleIds(report);
  recordExperienceEvent(EXPERIENCE_RULES, {
    type: 'compose-validation-failure',
    ruleIds,
    summary: {
      verdict: report.verdict,
      structurePassRate: report.structure.passRate,
      spotPassRate: report.spot.passRate,
      failedStruct,
    },
  });
  const line = [
    `\n## Compose 结构校验 (${new Date().toISOString()})`,
    `- 结构通过率：${(report.structure.passRate * 100).toFixed(2)}%（阈值 ${(STRUCT_PASS * 100).toFixed(0)}%）`,
    `- 抽查通过率：${(report.spot.passRate * 100).toFixed(2)}%（阈值 ${(SPOT_PASS * 100).toFixed(0)}%）`,
    `- 判定：${report.verdict}`,
    `- 边界未通过元素：${failedStruct} 个`,
    `- 已更新确定性规则：${ruleIds.join('、') || '本轮未匹配已有规则，保留原始失败证据'}`,
    `- 建议：结合上方失败元素清单修正 html-to-compose.js 的生成逻辑（坐标/尺寸/文本行高），见 SKILL.md Compose 阶段。`,
  ].join('\n');
  fs.appendFileSync(EXPERIENCE, line + '\n');
}

function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  if (!fs.existsSync(EXPERIENCE)) {
    fs.writeFileSync(EXPERIENCE, '# code-html-compose 经验库\n\n记录每次失败差异与修正建议，用于持续优化生成逻辑。\n');
  }

  // 1) 生成 Compose 高保真基线（确定性生成）
  console.log('\n  [compose-iterate] 生成 Compose（html-to-compose.js） ...');
  run('node html-to-compose.js', { DESIGN_DIR: process.env.DESIGN_DIR });

  // 2) 编译打包
  build();

  // 3) 安装
  install();

  // 4) 结构校验 + 局部抽查
  console.log('\n  [compose-iterate] 结构校验 + 局部抽查（compose-validate.js） ...');
  run('node compose-validate.js');

  // 5) 读取校验报告判定
  if (!fs.existsSync(REPORT)) {
    console.error(`   校验报告缺失：${REPORT}`);
    process.exit(1);
  }
  const report = JSON.parse(fs.readFileSync(REPORT, 'utf8'));
  const accepted = shouldAcceptReport(report, { structurePass: STRUCT_PASS, spotPass: SPOT_PASS });

  console.log(`\n===== Compose 验收结果 =====`);
  console.log(`  结构通过率：${(report.structure.passRate * 100).toFixed(2)}%（${report.structure.passed}/${report.structure.total}，阈值 ${(STRUCT_PASS * 100).toFixed(0)}%）`);
  console.log(`  抽查通过率：${(report.spot.passRate * 100).toFixed(2)}%（${report.spot.passed}/${report.spot.total}，阈值 ${(SPOT_PASS * 100).toFixed(0)}%）`);
  console.log(`  判定：${report.verdict}`);

  if (accepted) {
    console.log('\n 验收通过，结构正确。');
  } else {
    console.log('\n 验收未通过。');
    const failed = report.structure.checks.filter((c) => !c.passed);
    if (failed.length) {
      console.log(`  边界未通过元素 ${failed.length} 个：`);
      for (const f of failed.slice(0, 20)) {
        console.log(`    e${f.domIndex} ${f.role} ${f.text || ''} → ${f.reason || `dx=${f.dx} dy=${f.dy}`}`);
      }
    }
    const badSpots = report.spot.checks.filter((c) => !c.passed);
    if (badSpots.length) {
      console.log(`  抽查未通过区块 ${badSpots.length} 个：`);
      for (const s of badSpots.slice(0, 10)) {
        console.log(`    e${s.domIndex} ${s.role} → dist=${s.dist}`);
      }
    }
    appendExperience(report);
    process.exitCode = 1;
  }
}

main();
