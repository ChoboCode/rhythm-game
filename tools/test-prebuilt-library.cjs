/* 등록 곡은 저장 채보가 없거나 손상돼도 연주 중 자동 생성으로 넘어가지 않는다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const start = html.indexOf('  function prepare(song) {');
const end = html.indexOf('  function loadBuffer(song', start);
assert.ok(start >= 0 && end > start, '곡 준비 함수를 찾을 수 있어야 한다');
const source = html.slice(start, end);

function setup(savedChart) {
  const elements = new Map();
  const calls = { analyze: 0, play: 0, load: 0, fetch: 0, cache: 0, message: '', stems: [] };
  const scope = {
    S: { prepareToken: 0, chart: null },
    prefs: { difficulty: 'easy', hitSnd: true },
    previewCache: new Map([['a', {}], ['b', {}]]),
    Snd: {
      unlock() { return Promise.resolve(); },
      loadUrl(url) { calls.stems.push(url); return Promise.resolve({ duration: 145, url }); },
    },
    console: { warn() {} },
    navigator: {},                                 /* 메모리를 알려 주지 않는 브라우저 */
    LANES: 6,
    $: id => {
      if (!elements.has(id)) elements.set(id, { textContent: '' });
      return elements.get(id);
    },
    stopPreview() {}, show() {},
    setProgress(_value, message) { calls.message = message; },
    readCachedChart() { calls.cache++; return null; },
    loadBuffer() { calls.load++; return Promise.resolve({ duration: 145 }); },
    fetchChart() { calls.fetch++; return Promise.resolve(savedChart); },
    startPlay() { calls.play++; },
    runAnalysis() { calls.analyze++; },
  };
  vm.createContext(scope);
  vm.runInContext(source + '\nthis.prepare = prepare;', scope);
  return { prepare: scope.prepare, calls, scope };
}

async function flush() { await new Promise(resolve => setImmediate(resolve)); }

(async function () {
  const library = { kind: 'url', title: '검증 곡', charts: { easy: 'verified.easy.json' } };
  const good = { title: '검증 곡', difficulty: 'easy', lanes: 7,
    duration: 144.9, notes: [{ t: 1, lane: 0, hold: 0 }] };

  const ready = setup(good);
  ready.prepare(library);
  await flush();
  assert.equal(ready.calls.play, 1, '정상 저장 채보는 바로 연주해야 한다');
  assert.equal(ready.calls.analyze, 0, '정상 저장 채보를 다시 만들면 안 된다');
  assert.equal(ready.calls.cache, 0, '등록 곡은 로컬 자동 채보 캐시를 읽지 않는다');

  /* 키음 음원이 있으면 반주+드럼을 읽고, 미리듣기 원곡들은 메모리에서 놓아 준다 */
  const keyed = setup(good);
  keyed.prepare(Object.assign({ stems: { backing: 'stems/x.backing.mp3', drums: 'stems/x.drums.mp3' } }, library));
  await flush(); await flush();
  assert.equal(keyed.calls.play, 1, '키음 음원으로도 바로 연주해야 한다');
  assert.deepEqual(keyed.calls.stems, ['songs/stems/x.backing.mp3', 'songs/stems/x.drums.mp3'], '반주와 드럼을 읽는다');
  assert.equal(keyed.calls.load, 0, '키음으로 칠 때 원곡은 읽지 않는다');
  assert.equal(keyed.scope.previewCache.size, 0, '연주 중엔 미리듣기 원곡을 붙잡고 있지 않는다');

  /* 멜로디 키음이 있으면 반주·드럼·멜로디 셋을 읽는다 */
  const mel = setup(good);
  mel.prepare(Object.assign({ stems: { backing: 'stems/x.backing.mp3', drums: 'stems/x.drums.mp3', melody: 'stems/x.melody.mp3' } }, library));
  await flush(); await flush();
  assert.equal(mel.calls.play, 1, '멜로디 키음으로도 바로 연주해야 한다');
  assert.deepEqual(mel.calls.stems, ['songs/stems/x.backing.mp3', 'songs/stems/x.drums.mp3', 'songs/stems/x.melody.mp3'], '반주·드럼·멜로디를 읽는다');
  assert.equal(mel.scope.S.keyTracks.length, 2, '키음 트랙은 드럼과 멜로디 두 개');

  const absent = setup(good);
  absent.prepare({ kind: 'url', title: '검증 곡', charts: {} });
  await flush();
  assert.equal(absent.calls.load, 0, '채보가 없으면 음원도 읽지 않아야 한다');
  assert.equal(absent.calls.analyze, 0);
  assert.match(absent.calls.message, /저장된 EASY 채보가 없습니다/);

  for (const saved of [null, { ...good, difficulty: 'hard' }, { ...good, title: '다른 곡' },
    { ...good, lanes: 6 }, { ...good, duration: 141 }]) {
    const broken = setup(saved);
    broken.prepare(library);
    await flush();
    assert.equal(broken.calls.play, 0, '누락·오류 채보를 연주하면 안 된다');
    assert.equal(broken.calls.analyze, 0, '누락·오류 채보를 자동 생성하면 안 된다');
    assert.match(broken.calls.message, /저장된 EASY 채보를 읽지 못했습니다/);
  }

  const local = setup(null);
  local.prepare({ kind: 'file', title: '내 파일' });
  await flush();
  assert.equal(local.calls.analyze, 1, '직접 연 파일의 분석 기능은 유지한다');
  console.log('PASS: 등록 곡 저장 채보만 사용 · 누락/손상 시 자동 생성 금지 · 직접 연 파일 분석 유지');
})().catch(error => { console.error(error); process.exitCode = 1; });
