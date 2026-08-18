const assert = require('assert');
const {
  normalizeListGeometry,
} = require('../compose-generation-rules');
const {
  detectRepeatedTextGroups,
} = require('../compose-list-core');

function testUniformGeometry() {
  const group = [
    { rect: { x: 0, y: 0, w: 168, h: 84 } },
    { rect: { x: 177.5, y: 0, w: 169, h: 85 } },
    { rect: { x: 0, y: 93.5, w: 168, h: 84 } },
    { rect: { x: 177.5, y: 93.5, w: 169, h: 85 } },
  ];
  const result = normalizeListGeometry(
    group,
    { containerRect: { x: 0, y: 0, w: 346.5, h: 178.5 }, colGap: 9.5, rowGap: 9.5 },
    { cols: 2, rows: 2 },
  );
  assert.strictEqual(result.itemW, 168.5);
  assert.strictEqual(result.itemH, 84.5);
  assert.strictEqual(result.colGap, 9.5);
  assert.strictEqual(result.rowGap, 9.5);
  assert.deepStrictEqual(result.containerRect, { x: 0, y: 0, w: 346.5, h: 178.5 });
}

function testRepeatedTextItemsBecomeListCandidate() {
  const style = {
    fontSize: '15px',
    fontWeight: '700',
    lineHeight: '18px',
    color: 'rgb(232, 179, 139)',
    textAlign: 'left',
    whiteSpace: 'nowrap',
  };
  const result = detectRepeatedTextGroups([
    { domIndex: 31, role: 'text', text: '01', rect: { x: 10, y: 10, w: 18, h: 15 }, style },
    { domIndex: 35, role: 'text', text: '02', rect: { x: 10, y: 40, w: 18, h: 15 }, style },
    { domIndex: 39, role: 'text', text: '03', rect: { x: 10, y: 70, w: 18, h: 15 }, style },
  ]);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].kind, 'repeated-text');
  assert.strictEqual(result[0].axis, 'vertical');
  assert.deepStrictEqual(result[0].items.map((item) => item.text), ['01', '02', '03']);
}

testUniformGeometry();
testRepeatedTextItemsBecomeListCandidate();
console.log('compose-generation-rules smoke test: PASS');
