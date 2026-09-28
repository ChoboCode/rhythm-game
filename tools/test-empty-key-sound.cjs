const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const drumStart = html.indexOf('  function freeDrum(lane) {');
const drumEnd = html.indexOf('\n  }', drumStart);
assert.ok(drumStart >= 0 && drumEnd > drumStart, 'free drum mapping found');
const start = html.indexOf('  function press(lane) {');
const end = html.indexOf('\n  /*', start);
assert.ok(start >= 0 && end > start, 'press function found');
const pressSource = html.slice(start, end);
const sounds = [];
const state = {
  S: { screen: 'play' },
  P: {
    finished: false, pressed: Array(7).fill(false), flash: Array(7).fill(0),
    laneNotes: Array.from({ length: 7 }, () => []), laneCur: Array(7).fill(0),
  },
  JUDGE: [{ win: .135 }],
  LANES: 6,
  autoCenterEnabled: () => false,
  hitTime: () => 4,
  judgeFor: () => null,
  soundDrum: note => note.drum,
  playKeysound: () => false,                     /* 키음 음원이 없는 곡 — 합성 타격음을 낸다 */
  emptyKeysound: () => false,
  Snd: { hit: (...args) => sounds.push(args) },
};
state.freeDrum = vm.runInNewContext('(' + html.slice(drumStart, drumEnd + 4).trim() + ')', state);
const press = vm.runInNewContext('(' + pressSource.trim() + ')', state);
press(1);
assert.deepEqual(sounds, [['snare']], 'an empty D press plays its lane drum immediately');
press(1);
assert.equal(sounds.length, 1, 'key repeat does not machine-gun sounds while held');
assert.equal(state.P.pressed[1], true);

press(2);
assert.deepEqual(sounds[1], ['kick'], 'a six-key player can add a kick with F');

state.P.pressed[1] = false;
state.P.laneNotes[1] = [{ t: 4, lane: 1, hold: 0, drum: 'kick', state: 'wait' }];
state.judgeFor = () => ({ name: 'PERFECT' });
state.award = () => {};
press(1);
assert.equal(sounds.length, 3, 'a judged note produces one sound');
assert.deepEqual(sounds[2], ['kick', 4], 'judged note keeps its drum, timed to the note (on the beat if early, now if late)');
console.log('PASS: empty press drum, held-key repeat, judged-note drum');
