const fs = require('node:fs');
const path = require('node:path');

function positiveDimension(value, name) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} 必须是大于 0 的数值`);
  }
  return Math.round(parsed);
}

function detectDesignSize(directory, override = {}) {
  const hasWidth = override.width !== undefined && override.width !== '';
  const hasHeight = override.height !== undefined && override.height !== '';
  if (hasWidth || hasHeight) {
    if (!hasWidth || !hasHeight) {
      throw new Error('DESIGN_WIDTH 与 DESIGN_HEIGHT 必须成对设置');
    }
    return {
      w: positiveDimension(override.width, 'DESIGN_WIDTH'),
      h: positiveDimension(override.height, 'DESIGN_HEIGHT'),
      source: 'environment',
    };
  }

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
    '无法识别设计稿尺寸：请确保 CSS 的 .page 包含 px 宽高，或成对设置 DESIGN_WIDTH 与 DESIGN_HEIGHT',
  );
}

module.exports = { detectDesignSize };
