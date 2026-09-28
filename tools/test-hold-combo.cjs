/* Run the hold-tick functions from index.html with a controlled audio clock. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
function sourceOf(name) {
  const start = html.indexOf('function ' + name + '(');
  assert.ok(start >= 0, name + ' is present');
  const end = html.indexOf('\n  }', start);
  assert.ok(end > start, name + ' has an ending');
  return html.slice(start, end + 4);
}
function sourceOfConst(name) {
  const start = html.indexOf('const ' + name + ' = [');
  assert.ok(start >= 0, name + ' is present');
  const end = html.indexOf('];', start);
  assert.ok(end > start, name + ' has an ending');
  return html.slice(start, end + 2);
}

const P = { combo: 1, maxCombo: 1, comboPop: 0, milestone: 0,
  holdTicks: 0, holdTickStep: 60 / 147.7 / 4, flash: Array(7).fill(0),
  holdPulse: Array(7).fill(0), feverWeightSum: 0,
  total: 10, weightSum: 10, maxPossibleCombo: 17, fullCombo: true };
const scope = { P, Math, Skin: { colorOf() { return { rgb: '255,255,255' }; } },
  spawnSparks() {}, skinLane(l) { return l; }, FEVER_SCORE_BONUS: .18 };
vm.createContext(scope);
vm.runInContext(
  sourceOfConst('COMBO_BONUS') + '\n' +
  ['comboMultiplier', 'holdTickCount', 'growCombo', 'advanceHoldTicks', 'finalScore']
    .map(sourceOf).join('\n') +
  '\nthis.fns = {holdTickCount, advanceHoldTicks, finalScore, comboMultiplier};', scope);
const { holdTickCount, advanceHoldTicks, finalScore, comboMultiplier } = scope.fns;

/* ── 콤보 보너스 배율: 경계값이 정확히 그 콤보부터 적용돼야 한다 ── */
assert.equal(comboMultiplier(0), 1, 'no bonus below the first tier');
assert.equal(comboMultiplier(49), 1, 'still no bonus just under 50');
assert.equal(comboMultiplier(50), 1.1, 'bonus starts exactly at 50');
assert.equal(comboMultiplier(99), 1.1, 'stays at the 50-tier until 100');
assert.equal(comboMultiplier(100), 1.2, 'bonus steps up exactly at 100');
assert.equal(comboMultiplier(500), 1.75, 'top tier at 500');
assert.equal(comboMultiplier(9999), 1.75, 'bonus does not grow past the top tier');

const note = { t: .3947, lane: 2, hold: .8125, nextTickIndex: 1,
  tickCount: holdTickCount(.8125, P.holdTickStep) };
assert.equal(note.tickCount, 7);
advanceHoldTicks(note, note.t + .20);
assert.equal(P.combo, 2, 'holding through the first interval grows combo');
advanceHoldTicks(note, note.t + .20);
assert.equal(P.combo, 2, 'same clock time cannot award a tick twice');
advanceHoldTicks(note, note.t + note.hold);
assert.equal(P.combo, 8, 'all seven sustain ticks add to the head combo');
assert.equal(P.holdTicks, 7);
assert.equal(P.holdPulse[2], 1, 'sustain ticks refresh the judgment-line light');
assert.equal(P.maxCombo, 8);
assert.equal(P.total, 10, 'sustain ticks do not become hit judgments');
assert.equal(P.weightSum, 10, 'sustain ticks do not change accuracy');
P.maxCombo = P.maxPossibleCombo;
assert.equal(finalScore(), 1000000, 'full score remains capped at one million');
P.feverWeightSum = P.total;   /* 판정을 전부 피버타임 중에 딴 것으로 가정 */
assert.equal(finalScore(), Math.round(1000000 + 900000 * .18), 'fever bonus adds on top of a perfect score');
P.feverWeightSum = 0;

const perfect = { name: 'PERFECT', win: .042 };
const miss = { name: 'MISS' };
let tailHits = 0;
Object.assign(scope, {
  MISS: miss, JUDGE: [perfect, { name: 'GREAT', win: .085 }, { name: 'GOOD', win: .135 }],
  award(j) { if (j === miss) P.combo = 0; else P.combo++; },
  Snd: { hit() { tailHits++; } },
  Skin: { colorOf() { return { rgb: '255,255,255' }; } }, spawnSparks() {},
});
vm.runInContext(sourceOf('judgeFor') + '\n' + sourceOf('release') + '\nthis.release = release;', scope);
P.holding = Array(7).fill(null);
P.pressed = Array(7).fill(false);
P.holdTicks = 0;
P.combo = 1;
const early = { t: 1, lane: 2, hold: .8125, nextTickIndex: 1, tickCount: 7, state: 'holding' };
P.holding[2] = early;
scope.release(2, 1.35);
assert.equal(P.holdTicks, 3, 'early release receives only elapsed ticks');
assert.equal(P.combo, 0, 'early release breaks combo');
assert.equal(early.state, 'broken');
assert.equal(P.holding[2], null);
P.holdTicks = 0;
P.combo = 1;
const complete = { t: 2, lane: 2, hold: .8125, nextTickIndex: 1, tickCount: 7, state: 'holding' };
P.holding[2] = complete;
scope.release(2, 2.8125);
assert.equal(P.holdTicks, 7, 'release at the tail catches up any pending ticks');
assert.equal(P.combo, 9, 'head, seven ticks, and tail all count');
assert.equal(complete.state, 'done');
assert.equal(tailHits, 0, 'a hold tail must not add an off-beat drum hit');
P.holdTicks = 0;
P.combo = 1;
P.fullCombo = true;
const nearTail = { t: 3, lane: 2, hold: .8125, nextTickIndex: 1, tickCount: 7, state: 'holding' };
P.holding[2] = nearTail;
scope.release(2, 3.6825);
assert.equal(P.holdTicks, 6, 'tail release only earns completed sustain ticks');
assert.equal(P.fullCombo, false, 'missing a sustain tick prevents a full combo label');
console.log('PASS: timed sustain combo, no duplicate ticks, unchanged accuracy, score cap');
