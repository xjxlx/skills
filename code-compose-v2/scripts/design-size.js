const fs = require('node:fs');
const path = require('node:path');

const EXPECTED_WIDTH = 1334;
const EXPECTED_HEIGHT = 750;

function positiveDimension(value, name) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} 必须是大于 0 的数值`);
  }
  return Math.round(parsed);
}

/**
 * 从设计包 CSS 或目录名读取当前页面尺寸。
 * 尺寸只用于确认设计稿符合固定基准，不接受环境变量覆盖。
 */
function detectDesignSize(directory) {
  let cssFiles = [];
  try {
    cssFiles = fs.readdirSync(directory)
      .filter((file) => file.endsWith('.css') && !/(\.rem|\.response)\.css$/.test(file));
  } catch (error) {
    throw new Error(`无法读取设计稿目录：${directory}（${error.message}）`);
  }
  for (const file of cssFiles) {
    let css;
    try {
      css = fs.readFileSync(path.join(directory, file), 'utf8');
    } catch (error) {
      continue;
    }
    const pageBlock = css.match(/\.page\s*\{[^}]*\}/);
    if (!pageBlock) continue;
    const width = pageBlock[0].match(/width:\s*([\d.]+)px/);
    const height = pageBlock[0].match(/height:\s*([\d.]+)px/);
    if (width && height) {
      return {
        w: positiveDimension(width[1], '设计稿宽度'),
        h: positiveDimension(height[1], '设计稿高度'),
        source: 'css',
      };
    }
  }

  const directorySize = path.basename(directory).match(/(\d+)x(\d+)/);
  if (directorySize) {
    return {
      w: positiveDimension(directorySize[1], '目录名宽度'),
      h: positiveDimension(directorySize[2], '目录名高度'),
      source: 'directory-name',
    };
  }

  throw new Error(
    '无法识别设计稿尺寸：请确保 CSS 的 .page 包含 px 宽高，或目录名包含 1334x750。',
  );
}

/**
 * 校验设计稿必须使用固定的横屏基准。
 * 不匹配时直接停止，禁止通过环境变量或局部缩放继续执行。
 */
function requireSupportedDesignSize(size) {
  if (size.w !== EXPECTED_WIDTH || size.h !== EXPECTED_HEIGHT) {
    throw new Error(
      `设计稿尺寸不匹配：需要 ${EXPECTED_WIDTH}x${EXPECTED_HEIGHT}，实际为 ${size.w}x${size.h}。` +
      '请重新导出正确尺寸的 HTML 设计包。',
    );
  }
  return size;
}

module.exports = {
  EXPECTED_HEIGHT,
  EXPECTED_WIDTH,
  detectDesignSize,
  requireSupportedDesignSize,
};
