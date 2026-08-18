/**
 * 步骤 6-7：像素对比 + 迭代自修正，直到相似度 > 99.95%；并收集失败经验。
 * 每轮：截图原始 vs new.html → 像素对比 → 记录本轮报告 → 收敛判断。
 * 未达标时依次尝试有限的确定性生成策略；全部失败后保留最优结果并退出，禁止无限循环。
 * 每轮失败都会把差异热点与判定写入 experience.md，供持续优化生成逻辑。
 */
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { summarizeAttempts } = require('./html-iteration-core');
const { recordExperienceEvent } = require('./compose-generation-rules');
const { PROJECT_ROOT, WORK_DIR, TOOL_OUTPUT_DIR, EXPERIENCE_PATH, EXPERIENCE_RULES_PATH } = require('./config');

const TOOLS = __dirname;
const OUT_DIR = TOOL_OUTPUT_DIR; // 中间产物（截图 + 最新报告）
const EXPERIENCE = EXPERIENCE_PATH;
const EXPERIENCE_RULES = EXPERIENCE_RULES_PATH;
const BASE_ENV = { ...process.env, PROJECT_ROOT, CODE_HTML_COMPOSE_WORK_DIR: WORK_DIR };
const TARGET = 0.9995; // 收敛阈值：相似度 > 99.95% 才停止

// 每个确定性策略最多尝试一次。
const STRATEGIES = ['dom', 'legacy'];

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
    execSync(cmd, { cwd: TOOLS, stdio: 'inherit', env: { ...BASE_ENV, ...env } });
  } catch (error) {
    recordScriptFailure('html-script-error', error, { command: cmd });
    throw error;
  }
}

function appendExperience(report, round, strategy) {
  const sim = (report.pixelSimilarity * 100).toFixed(2);
  const hotspotText = (report.hotspots || []).join(' ');
  const ruleIds = /image|arrow|overlay|参考|视觉|reference/i.test(hotspotText)
    ? ['reject-reference-unsupported-images']
    : [];
  recordExperienceEvent(EXPERIENCE_RULES, {
    type: 'html-pixel-validation-failure',
    ruleIds,
    summary: {
      round,
      strategy,
      verdict: report.verdict,
      pixelSimilarity: report.pixelSimilarity,
      hotspots: report.hotspots || [],
    },
  });
  const line = [
    `\n## Round ${round} (策略=${strategy})`,
    `- 时间：${new Date().toISOString()}`,
    `- 相似度：${sim}%（未达标，需修正）`,
    `- 判定：${report.verdict}`,
    `- 差异热点：${(report.hotspots || []).join('；') || '无'}`,
    `- 已更新确定性规则：${ruleIds.join('、') || '本轮未匹配已有规则，保留原始失败证据'}`,
    `- 建议：结合热点区域定位根因后修正 new.html 生成逻辑（见 SKILL.md 对比根因表）。`,
  ].join('\n');
  fs.appendFileSync(EXPERIENCE, line + '\n');
  console.log(`  已记录本轮经验 → ${EXPERIENCE}`);
}

function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  if (!fs.existsSync(EXPERIENCE)) fs.writeFileSync(EXPERIENCE, '# code-html-compose 经验库\n\n记录每次失败差异与修正建议，用于持续优化 new.html 生成逻辑。\n');

  const attempts = [];
  for (let index = 0; index < STRATEGIES.length; index++) {
    const round = index + 1;
    const strategy = STRATEGIES[index];
    console.log(`\n===== 第 ${round} 轮：策略=${strategy} 重新生成 new.html + 截图 =====`);

    // 1) 生成语义树 + new.html + 原始/规范截图（携带策略与设计源）
    run('node normalize.js', { Z_STRATEGY: strategy, DESIGN_DIR: process.env.DESIGN_DIR });
    // 2) 像素对比，产出 compare-report.json
    run('node compare.js', { DESIGN_DIR: process.env.DESIGN_DIR });

    // 3) 收集本轮报告
    const report = JSON.parse(fs.readFileSync(path.join(OUT_DIR, 'compare-report.json'), 'utf8'));
    report.round = round;
    report.strategy = strategy;

    const sim = report.pixelSimilarity;
    console.log(`  第 ${round} 轮相似度 = ${(sim * 100).toFixed(2)}%  verdict=${report.verdict}`);
    attempts.push({ ...report, strategy });

    if (sim > TARGET) {
      console.log(`  已达标（> ${(TARGET * 100).toFixed(2)}%），收敛。`);
      break;
    }
    console.log(`  未达标，记录结果后尝试下一个有限策略...`);
    appendExperience(report, round, strategy); // 步骤 7：收集失败经验
  }

  const summary = summarizeAttempts(attempts, TARGET);
  if (!summary.converged && summary.best && summary.best.strategy !== STRATEGIES[STRATEGIES.length - 1]) {
    run('node normalize.js', { Z_STRATEGY: summary.best.strategy, DESIGN_DIR: process.env.DESIGN_DIR });
    run('node compare.js', { DESIGN_DIR: process.env.DESIGN_DIR });
  }
  fs.writeFileSync(path.join(OUT_DIR, 'html-iteration-report.json'), JSON.stringify({
    target: TARGET,
    converged: summary.converged,
    attempted: summary.attempted,
    bestStrategy: summary.best && summary.best.strategy,
    bestSimilarity: summary.best && summary.best.pixelSimilarity,
    visualSource: 'original.png',
  }, null, 2));
  if (!summary.converged) {
    console.warn('  规范化 HTML 未达到目标；Compose 将以 original.png 为最终视觉真源继续，并在报告中保留中间层告警。');
  }
  console.log(`\n完成。历史最优：相似度=${(summary.best.pixelSimilarity * 100).toFixed(2)}% 策略=${summary.best.strategy}`);
  console.log(`每轮产物已保存到 ${path.join(WORK_DIR, 'run-*')}`);
}

main();
