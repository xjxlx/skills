const assert = require('node:assert/strict');
const test = require('node:test');

const { summarizeAttempts } = require('../html-iteration-core');

test('有限策略都未达标时返回最优结果且不伪称收敛', () => {
  const result = summarizeAttempts([
    { strategy: 'dom', pixelSimilarity: 0.89 },
    { strategy: 'legacy', pixelSimilarity: 0.87 },
  ], 0.9995);

  assert.equal(result.converged, false);
  assert.equal(result.best.strategy, 'dom');
  assert.equal(result.attempted, 2);
});

test('任一有限策略达标时返回收敛结果', () => {
  const result = summarizeAttempts([
    { strategy: 'dom', pixelSimilarity: 0.9996 },
  ], 0.9995);

  assert.equal(result.converged, true);
  assert.equal(result.best.pixelSimilarity, 0.9996);
});
