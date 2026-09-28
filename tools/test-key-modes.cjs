/* 7키 원본 채보가 6키로 옮겨질 때 타이밍·롱노트 점유·레인 범위를 확인한다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8').replace(/\r\n/g, '\n');
const block = html.split('<script>\n').slice(1).map(x => x.split('\n</script>')[0])
  .find(x => x.includes('keymode.js'));
assert.ok(block, '6키 채보 변환 코드를 찾을 수 없다');
const scope = { Math, Array, Object };
vm.createContext(scope);
vm.runInContext(block + '\nthis.KeyModes = KeyModes;', scope);

function verify(notes, label) {
  const indexed = notes.map((n, i) => Object.assign({ sourceIndex: i }, n));
  const converted = scope.KeyModes.toSix(indexed);
  const occupiedUntil = Array(6).fill(-Infinity);
  converted.forEach(n => {
    const original = notes[n.sourceIndex];
    assert.ok(Number.isInteger(n.lane) && n.lane >= 0 && n.lane < 6, label + ': 6키 밖 레인');
    assert.equal(n.t, original.t, label + ': 타격 시점이 바뀌었다');
    assert.equal(n.hold, original.hold, label + ': 롱노트 길이가 바뀌었다');
    assert.ok(n.t >= occupiedUntil[n.lane] + .06 - 1e-6, label + ': 같은 레인 또는 롱노트와 겹친다');
    occupiedUntil[n.lane] = n.t + (n.hold || 0);
  });
  const assigned = new Set(converted.map(n => n.sourceIndex));
  indexed.forEach(n => {
    if (assigned.has(n.sourceIndex)) return;
    const simultaneous = notes.filter(other => other.t <= n.t + 1e-6 &&
      other.t + (other.hold || 0) + .06 > n.t - 1e-6).length;
    assert.ok(simultaneous > 6, label + ': 6개 레인이 비어 있는데 노트가 사라졌다');
  });
  return notes.length - converted.length;
}

verify([
  { t: 1, lane: 3, hold: 2 },
  { t: 1, lane: 2, hold: 0 },
  { t: 1, lane: 4, hold: 0 },
  { t: 1.5, lane: 2, hold: 0 },
  { t: 2, lane: 3, hold: 0 },
  { t: 3.2, lane: 3, hold: 0 }
], '동시타·롱노트');

const dir = path.join(root, 'songs');
const songs = JSON.parse(fs.readFileSync(path.join(dir, 'songs.json'), 'utf8'));
let checked = 0;
let dropped = 0;
for (const song of songs) {
  for (const difficulty of ['easy', 'normal', 'hard']) {
    const chart = JSON.parse(fs.readFileSync(path.join(dir, song.charts[difficulty]), 'utf8'));
    dropped += verify(chart.notes, song.title + ' ' + difficulty);
    checked++;
  }
}
console.log('PASS: ' + checked + '개 채보의 6키 변환 · 타이밍 · 롱노트 점유 · 불가능한 동시 노트 ' + dropped + '개 제외');
