function summarizeAttempts(attempts, target) {
  if (!attempts.length) return { converged: false, best: null, attempted: 0 };
  const best = attempts.reduce((current, attempt) => (
    !current || attempt.pixelSimilarity > current.pixelSimilarity ? attempt : current
  ), null);
  return {
    converged: attempts.some((attempt) => attempt.pixelSimilarity > target),
    best,
    attempted: attempts.length,
  };
}

module.exports = { summarizeAttempts };
