/* 합성 트랙으로 채보 생성기를 검증한다.
   실제 mp3 없이도 BPM 추정 · 패턴 품질 · 난이도 차이 · 긴 노트를 확인할 수 있다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

/* 이 프로젝트는 index.html 한 파일에 CSS·JS 가 모두 들어 있다(유지보수 편의를 위해
   단일 파일로 통합했다). 그래서 테스트도 index.html 안의 <script> 블록을 그대로
   뽑아서 돌린다 — 따로 사본을 두면 둘이 어긋날 수 있어서다. */
/* 파일이 CRLF 로 저장돼 있을 수 있으므로 먼저 LF 로 맞춘다 */
const INDEX_HTML = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8').replace(/\r\n/g, '\n');
const SCRIPT_BLOCKS = INDEX_HTML.split('<script>\n').slice(1).map(function (chunk) {
  return chunk.split('\n</script>')[0];
});
/* 각 블록은 "/* ... 제목 줄 ... " 주석으로 시작한다. 그 제목에 파일 이름이 들어 있으므로
   문자열 포함 여부만으로 찾는다 — 정규식보다 깨지기 쉬운 이스케이프가 없다. */
function extractScript(label) {
  const found = SCRIPT_BLOCKS.find(function (b) { return b.split('\n', 3).join('\n').indexOf(label) >= 0; });
  if (!found) throw new Error('index.html 에서 "' + label + '" 스크립트 블록을 찾지 못했습니다.');
  return found;
}

const ctx = {Math:Math, Date:Date, console:console, Float32Array, Uint32Array, Int32Array, Error};
vm.createContext(ctx);
vm.runInContext(extractScript('fft.js'), ctx);
vm.runInContext(extractScript('chart.js'), ctx);
vm.runInContext('this.CG = ChartGen;', ctx);
const CG = ctx.CG;
const SR = 44100;

/* ── 드럼 + 베이스 + 멜로디가 섞인 트랙 (실제 노래에 가깝게) ── */
function song(sec, bpm) {
  const n = SR * sec, f = new Float32Array(n), BEAT = 60 / bpm;
  const add = (at, dur, gen) => {
    const s = Math.floor(at * SR), c = Math.floor(dur * SR);
    for (let i = 0; i < c; i++) { const k = s + i; if (k >= 0 && k < n) f[k] += gen(i / SR, i / c); }
  };
  const SCALE = [0, 3, 5, 7, 10];
  for (let st = 0; st < Math.floor(sec / (BEAT / 4)); st++) {
    const t = st * BEAT / 4, inBar = st % 16, bar = Math.floor(st / 16);
    if (inBar % 4 === 0) add(t, .24, (x, e) => Math.sin(2 * Math.PI * (118 - 76 * e) * x) * Math.pow(1 - e, 2.2) * .85);
    if (inBar === 4 || inBar === 12) add(t, .18, (x, e) => ((Math.random() * 2 - 1) * .6 + Math.sin(2 * Math.PI * 205 * x) * .3) * Math.pow(1 - e, 4) * .7);
    if (inBar % 2 === 0) add(t, .06, (x, e) => (Math.random() * 2 - 1) * Math.pow(1 - e, 9) * .22);
    if (inBar === 0 || inBar === 6 || inBar === 10) {
      const fr = 110 * Math.pow(2, (SCALE[(bar + (inBar === 6 ? 2 : 0)) % 5] - 12) / 12);
      add(t, inBar === 0 ? BEAT * 1.2 : BEAT * .7, (x, e) => {
        const env = Math.min(1, e * 25) * (1 - e);
        return (Math.sin(2 * Math.PI * fr * x) + Math.sin(2 * Math.PI * fr * 2 * x) * .35) * env * .4;
      });
    }
    if (inBar === 2 || inBar === 7 || inBar === 11 || inBar === 14) {
      const fr = 220 * Math.pow(2, (SCALE[(st * 3) % 5] + 12) / 12);
      add(t, BEAT * .45, (x, e) => {
        const env = Math.min(1, e * 30) * Math.pow(1 - e, 1.4);
        return (Math.sin(2 * Math.PI * fr * x) * .6 + Math.sin(2 * Math.PI * fr * 1.5 * x) * .25) * env * .3;
      });
    }
  }
  return f;
}

function build(buf, difficulty) {
  const job = CG.createJob(buf, SR, {difficulty});
  let guard = 0;
  while (!job.done && guard++ < 10000) job.step(1000);
  assert.ok(job.done, difficulty + ': 분석이 끝나야 한다');
  return job.chart;
}

const SEC = 30, BPM = 128;
const buf = song(SEC, BPM);
const easy = build(buf, 'easy'), normal = build(buf, 'normal'), hard = build(buf, 'hard');

/* ── BPM 추정 ── */
assert.ok(Math.abs(normal.bpm - BPM) < 4,
  '128 BPM 트랙의 추정값: ' + normal.bpm + ' (확신도 ' + normal.confidence + ')');
assert.ok(normal.confidence > .3, '박자 확신도가 너무 낮다: ' + normal.confidence);

/* half/double 오인: 느린 곡과 빠른 곡에서도 실제 BPM 이나 그 배수로 잡혀야 한다 */
for (const bpm of [84, 100, 160, 174]) {
  const c = build(song(24, bpm), 'normal');
  const ratio = c.bpm / bpm;
  assert.ok(Math.abs(ratio - 1) < .06 || Math.abs(ratio - 2) < .12 || Math.abs(ratio - .5) < .06,
    bpm + ' BPM 트랙을 ' + c.bpm + ' 로 잡았다 (배수 관계도 아님)');
}

/* ── 기본 유효성 ── */
for (const c of [easy, normal, hard]) {
  const tag = c.difficulty;
  assert.ok(c.notes.length > 20, tag + ': 노트가 너무 적다 ' + c.notes.length);
  assert.ok(c.notes[0].t < 3, tag + ': 시작 부분에도 노트가 있어야 한다');
  assert.ok(c.notes[c.notes.length - 1].t > SEC - 4, tag + ': 끝까지 노트가 이어져야 한다');
  for (let i = 0; i < c.notes.length; i++) {
    const n = c.notes[i];
    assert.ok(n.lane >= 0 && n.lane < 7, tag + ': 레인 범위 ' + n.lane);
    assert.ok(n.hold >= 0 && n.hold < 3, tag + ': 긴 노트 길이 ' + n.hold);
    assert.ok(n.t >= 0 && n.t <= SEC, tag + ': 노트 시각 ' + n.t);
    if (i) assert.ok(n.t >= c.notes[i - 1].t, tag + ': 시간순으로 정렬돼야 한다');
  }
  /* 같은 레인은 긴 노트가 끝난 뒤에야 다시 쓸 수 있다 */
  const endOf = new Array(7).fill(-99);
  for (const n of c.notes) {
    assert.ok(n.t >= endOf[n.lane] + .07,
      tag + ': 같은 레인이 너무 빨리 다시 나온다 (레인 ' + n.lane + ' @' + n.t.toFixed(2) + ')');
    endOf[n.lane] = n.t + n.hold;
  }
}

/* ── 난이도: 노트 수와 패턴이 함께 달라져야 한다 ── */
const nps = c => c.notes.length / SEC;
assert.ok(nps(easy) < nps(normal) && nps(normal) < nps(hard),
  '난이도가 올라갈수록 촘촘해야 한다: ' + [nps(easy), nps(normal), nps(hard)].map(x => x.toFixed(2)).join(' < '));
assert.ok(nps(easy) < 2.6, 'EASY 가 너무 빽빽하다: ' + nps(easy).toFixed(2) + '/초');
assert.ok(nps(hard) < 6.5, 'HARD 가 지나치게 빽빽하다: ' + nps(hard).toFixed(2) + '/초');

function maxChord(c) {
  let best = 1, run = 1;
  for (let i = 1; i < c.notes.length; i++) {
    run = Math.abs(c.notes[i].t - c.notes[i - 1].t) < .02 ? run + 1 : 1;
    best = Math.max(best, run);
  }
  return best;
}
assert.equal(maxChord(easy), 1, 'EASY 에는 동시치기가 없어야 한다');
assert.ok(maxChord(hard) <= 3, 'HARD 동시치기: ' + maxChord(hard));

/* ── 패턴 품질: 기계가 찍은 티가 나지 않아야 한다 ── */
function pattern(c) {
  const n = c.notes, hand = l => l < 3 ? 0 : (l > 3 ? 1 : 2);
  const dist = new Array(7).fill(0);
  n.forEach(x => dist[x.lane]++);
  let alt = 0, same = 0, jack = 1, maxJack = 1;
  for (let i = 1; i < n.length; i++) {
    if (Math.abs(n[i].t - n[i - 1].t) < .02) continue;
    const a = hand(n[i - 1].lane), b = hand(n[i].lane);
    if (a !== b) alt++; else same++;
    if (n[i].lane === n[i - 1].lane) { jack++; maxJack = Math.max(maxJack, jack); } else jack = 1;
  }
  const seen = new Map();
  let dup = 0, tot = 0;
  for (let i = 0; i + 3 < n.length; i++) {
    const key = n.slice(i, i + 4).map(x => x.lane).join(',');
    tot++;
    const v = (seen.get(key) || 0) + 1;
    seen.set(key, v);
    if (v > 1) dup++;
  }
  return {
    used: dist.filter(d => d > 0).length,
    altRate: alt / Math.max(1, alt + same),
    maxJack,
    repeat4: dup / Math.max(1, tot),
    share: Math.max(...dist) / n.length
  };
}

const pe = pattern(easy), pn = pattern(normal), ph = pattern(hard);
assert.ok(pn.used >= 6 && ph.used >= 6, '보통·어려움은 레인을 고루 써야 한다');
assert.ok(pe.used >= 4, '쉬움도 최소 4개 레인은 써야 한다: ' + pe.used);
for (const [tag, p] of [['EASY', pe], ['NORMAL', pn], ['HARD', ph]]) {
  assert.ok(p.share < .34, tag + ': 한 레인에 너무 몰린다 ' + (p.share * 100).toFixed(0) + '%');
  assert.ok(p.altRate > .3, tag + ': 손 교대가 너무 적다 ' + (p.altRate * 100).toFixed(0) + '%');
  assert.ok(p.repeat4 < .42, tag + ': 같은 네 묶음이 너무 자주 되풀이된다 ' + (p.repeat4 * 100).toFixed(0) + '%');
}
assert.equal(pe.maxJack, 1, 'EASY 에는 같은 레인 연타가 없어야 한다');
assert.ok(pn.maxJack <= 2, 'NORMAL 연타 길이: ' + pn.maxJack);
assert.ok(ph.maxJack <= 3, 'HARD 연타 길이: ' + ph.maxJack);

/* ── 같은 곡·같은 난이도는 항상 같은 채보 ── */
const again = build(buf, 'normal');
assert.equal(JSON.stringify(again.notes), JSON.stringify(normal.notes),
  '같은 입력이면 같은 채보가 나와야 한다(저장해 둔 채보와 어긋나지 않도록)');

/* ── 긴 노트 ── */
function holdShare(c) { return c.notes.filter(n => n.hold > 0).length / c.notes.length; }
const hs = { easy: holdShare(easy), normal: holdShare(normal), hard: holdShare(hard) };
assert.ok(hs.easy > .15 && hs.easy < .38, 'EASY 긴 노트 비율: ' + (hs.easy * 100).toFixed(0) + '%');
assert.ok(hs.normal > .10 && hs.normal < .30, 'NORMAL 긴 노트 비율: ' + (hs.normal * 100).toFixed(0) + '%');
assert.ok(hs.hard > .06 && hs.hard < .24, 'HARD 긴 노트 비율: ' + (hs.hard * 100).toFixed(0) + '%');
assert.ok(hs.easy > hs.hard, '쉬울수록 긴 노트가 많아야 한다');

console.log('BPM 추정   ', normal.bpm, '/ 실제', BPM, '· 확신도', normal.confidence);
console.log('초당 노트  easy', nps(easy).toFixed(2), '· normal', nps(normal).toFixed(2), '· hard', nps(hard).toFixed(2));
console.log('손 교대율  easy', (pe.altRate * 100).toFixed(0) + '%', '· normal', (pn.altRate * 100).toFixed(0) + '%', '· hard', (ph.altRate * 100).toFixed(0) + '%');
console.log('4묶음 반복 easy', (pe.repeat4 * 100).toFixed(0) + '%', '· normal', (pn.repeat4 * 100).toFixed(0) + '%', '· hard', (ph.repeat4 * 100).toFixed(0) + '%');
console.log('최대 연타  easy', pe.maxJack, '· normal', pn.maxJack, '· hard', ph.maxJack);
console.log('긴 노트    easy', (hs.easy * 100).toFixed(0) + '%', '· normal', (hs.normal * 100).toFixed(0) + '%', '· hard', (hs.hard * 100).toFixed(0) + '%');
console.log('PASS: BPM·정렬·난이도 차이·패턴 품질·재현성·긴 노트');
