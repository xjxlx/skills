const fs = require('node:fs');
const path = require('node:path');

function packageNormalizedHtml({ normalizedHtml, designDir, outputDir }) {
  fs.mkdirSync(outputDir, { recursive: true });

  let copiedHtml = false;
  if (fs.existsSync(normalizedHtml)) {
    fs.copyFileSync(normalizedHtml, path.join(outputDir, 'new.html'));
    copiedHtml = true;
  }

  const sourceImageDirectory = path.join(designDir, 'img');
  let copiedImageDirectory = false;
  if (fs.existsSync(sourceImageDirectory) && fs.statSync(sourceImageDirectory).isDirectory()) {
    fs.cpSync(sourceImageDirectory, path.join(outputDir, 'img'), {
      recursive: true,
      force: true,
    });
    copiedImageDirectory = true;
  }

  return { copiedHtml, copiedImageDirectory };
}

module.exports = { packageNormalizedHtml };
