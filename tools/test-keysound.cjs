const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const a = html.indexOf('function keysoundWindows(');
const endRe = /\r?\n  \}\r?\n/g;                 /* 함수 끝(두 칸 들여쓴 닫는 괄호) — CRLF도 */
endRe.lastIndex = a;
const b = endRe.exec(html).index + 5;
assert(a > 0 && b > a, 'keysoundWindows found in the game');
const keysoundWindows = new Function(html.slice(a, b) + 'return keysoundWindows;')();

/* 가짜 드럼 트랙: 1.00초·2.08초·3.50초에 탁 치는 소리 */
const sr = 44100, data = new Float32Array(sr * 6);
for (const hit of [1.0, 2.08, 3.5]) {
  for (let i = 0; i < sr * .15; i++) data[Math.floor(hit * sr) + i] = Math.sin(i / 8) * Math.exp(-i / (sr * .03));
}
const note = (t, lane) => ({ t, lane, hold: 0 });
/* 채보는 이미 실제 타격에 맞춰 두었다(snap-notes.py). 남은 10ms 오차는 다듬고(2.07 → 2.08),
   0.08초 떨어진 이웃 타격은 끌어오지 않는다(3.42 노트는 3.5 타격과 별개). 3.5초는 화음, 5.5초는 드럼 없음 */
const notes = [note(1.0, 0), note(2.07, 1), note(3.42, 5), note(3.5, 2), note(3.5, 4), note(5.5, 3)];
const w = keysoundWindows(notes, [{ chans: [data], sampleRate: sr }]);

assert.equal(w.length, 5, 'a chord shares one window');
assert(Math.abs(w[0].t - (1.0 - .004)) < .004, 'window starts just before the real attack');
assert(Math.abs(w[1].t - (2.08 - .004)) < .004, 'a note 10ms early is refined to the real attack (no clipped attack)');
assert(Math.abs(w[2].t - (3.42 - .004)) < 1e-9, 'a hit 0.08s away is not grabbed (the wrong drum would play)');
assert(Math.abs(w[0].end - w[0].t - .9) < 1e-9, 'long gaps are capped at 0.9s; the rest plays by itself');
assert(Math.abs(w[3].end - Math.min(w[4].t, w[3].t + .9)) < 1e-9, 'a window ends where the next one begins (or 0.9s)');
assert.equal(w[4].t, 5.5 - .004, 'no drum nearby → the chart time is kept');
assert.deepEqual(notes.map(n => n.keyWin), [0, 1, 2, 3, 3, 4], 'each note knows its window; chord notes share one');
assert(w.every(x => x.played === false), 'nothing played yet');
assert.deepEqual(w.map(x => x.quiet), [false, false, true, false, true], 'windows with no drum under them (3.42, 5.5) are quiet');
{ const real = w.filter(x => !x.quiet); for (let i = 1; i < real.length; i++) assert(real[i - 1].end <= real[i].t + 1e-9, 'windows on one track never overlap'); }
assert(w.every(x => x.src === 0), 'with drums only, every window uses the drum track');

/* 멜로디 트랙(스테레오): 5.5초에 노래가 시작된다. 드럼 없는 노트 → 멜로디, 둘 다 없으면 합성음 */
{
  const L = new Float32Array(sr * 7), R = new Float32Array(sr * 7);
  for (let i = 0; i < sr * .6; i++) { const v = Math.sin(i / 20) * .4 * Math.min(1, i / 200); L[Math.floor(5.5 * sr) + i] = v; R[Math.floor(5.5 * sr) + i] = v * .8; }
  const ns = [note(1.0, 0), note(2.07, 1), note(3.42, 5), note(3.5, 2), note(3.5, 4), note(5.5, 3)];
  const m = keysoundWindows(ns, [{ chans: [data], sampleRate: sr }, { chans: [L, R], sampleRate: sr }]);
  assert.deepEqual(m.map(x => x.src), [0, 0, 0, 0, 1], 'drum notes keep the drum; the note with no drum takes the melody');
  assert.deepEqual(m.map(x => x.quiet), [false, false, true, false, false], 'only a note with neither drum nor melody is quiet (synth hit)');
  assert(m[4].t < 5.5 && m[4].t > 5.48, 'the melody window starts just before the sung attack (soft onsets are not clipped)');
  assert(Math.abs(m[3].end - (m[3].t + .9)) < 1e-9, 'a drum window ends at the next DRUM window (a melody note in between does not cut it)');
}

/* 게임 연결: 친 노트는 키음, 화음은 한 번만, 자동 레인도 키음, 곡 목록이 stems를 넘긴다 */
assert(/if \(!playKeysound\(target\)\) Snd\.hit\(soundDrum\(target\), target\.t\)/.test(html), 'a judged hit plays its keysound, else the synth hit on the beat');
assert(/list\[k\]\.t <= t \+ \.1/.test(html) && /n\.autoSound = true;/.test(html), 'the auto lane schedules its sound 0.1s ahead (not a frame late)');
assert(/if \(w\.quiet\) return false;/.test(html), 'a note with no drum under it falls back to the synth hit (never a silent hit)');
assert(/if \(!playKeysound\(n, n\.t\)\) Snd\.hit\(soundDrum\(n\), n\.t\)/.test(html), 'the auto lane plays its keysound on time');
assert(/if \(!emptyKeysound\(list, P\.laneCur\[lane\]\)\) Snd\.hit\(freeDrum\(lane\)\)/.test(html),
  'an empty press plays the next note’s real sound in that lane (O2Jam), else the lane drum');
assert(/stems: s\.stems && s\.stems\.backing && s\.stems\.drums \? s\.stems : null/.test(html), 'the manifest passes stems');
assert(/P\.keyWins \? \{ tracks: S\.keyTracks, windows: P\.keyWins \} : null/.test(html), 'play starts with the keysound tracks (drums, melody)');

/* 키음 음원 파일이 곡 목록에 있으면 실제로 있어야 한다 */
const songs = JSON.parse(fs.readFileSync(path.join(root, 'songs', 'songs.json'), 'utf8'));
let withStems = 0;
for (const s of songs) {
  if (!s.stems) continue;
  withStems++;
  for (const f of [s.stems.backing, s.stems.drums]) assert(fs.existsSync(path.join(root, 'songs', f)), s.title + ': ' + f);
}

/* ── 키음 트랙: 끊김 없이 흐르고 크기만 바뀐다. 가짜 오디오로 Snd를 그대로 돌려 본다 ── */
{
  const sa = html.indexOf('const Snd = (function () {');
  const sb = html.indexOf('\n})();', sa) + 6;
  class Param {
    constructor(v) { this.value = v; this.ev = []; }
    setValueAtTime(v, t) { this.ev.push([v, t, 'set']); }
    linearRampToValueAtTime(v, t) { this.ev.push([v, t, 'ramp']); }
    cancelScheduledValues(t) { this.ev = this.ev.filter(e => e[1] < t); }
    /* 선형 경사를 흉내 낸다: 경사 이벤트는 앞 이벤트 값에서 그 시각까지 곧게 */
    at(t) {
      const ev = this.ev.slice().sort((x, y) => x[1] - y[1]);
      let v = this.value, vt = -Infinity;
      for (const [val, time, kind] of ev) {
        if (time <= t) { v = val; vt = time; continue; }
        if (kind === 'ramp') return v + (val - v) * (t - vt) / (time - vt);
        break;
      }
      return v;
    }
  }
  const tracks = [], sources = [];
  const node = extra => Object.assign({ outs: [], connect(to) { this.outs.push(to); }, disconnect() {} }, extra);
  class FakeCtx {
    constructor() { this.currentTime = 0; this.sampleRate = 44100; this.state = 'running'; this.destination = {}; }
    createGain() { return node({ gain: new Param(1) }); }
    createDynamicsCompressor() { return node({ threshold: new Param(0), knee: new Param(0), ratio: new Param(0), attack: new Param(0), release: new Param(0) }); }
    createChannelSplitter() { return node({}); }
    createAnalyser() { return node({ fftSize: 512, frequencyBinCount: 256 }); }
    createBufferSource() {
      return node({ playbackRate: new Param(1), stop() {},
        start(when, offset, dur) { sources.push({ buffer: this.buffer, when, offset, dur }); if (this.buffer === drums || this.buffer === melody) tracks.push(this); } });
    }
    resume() { return Promise.resolve(); }
    createBuffer(ch, n, sr) { const d = Array.from({ length: ch }, () => new Float32Array(n)); return { length: n, sampleRate: sr, numberOfChannels: ch, getChannelData: i => d[i] }; }
  }
  const Snd = new Function('window', 'document', html.slice(sa, sb) + '\nreturn Snd;')({ AudioContext: FakeCtx }, {});
  const drums = { duration: 60 }, melody = { duration: 60 }, backing = { duration: 60, numberOfChannels: 2 };
  const ctx = Snd.context();
  const win = [{ t: 1, end: 1.5, src: 0, chain: true }, { t: 1.5, end: 2, src: 0 }, { t: 3, end: 3.4, src: 0 }, { t: 4, end: 4.5, src: 0 },
    { t: 2.2, end: 2.8, src: 1 }, { t: 6, end: 6.1, src: 0, quiet: true }, { t: 5, end: 5.6, src: 1 }, { t: 7, end: 7.6, src: 1 }];
  ctx.currentTime = 10;                              /* 곡 시각 = currentTime − 10 */
  Snd.start(backing, 0, 0, { tracks: [drums, melody], windows: win });
  const go = t => { ctx.currentTime = 10 + t; };
  /* 트랙 k의 실제 크기 = base + boost (같은 소스의 두 갈래) */
  const level = (k, t, origin = 10) => { const tr = tracks.filter(x => x.buffer === (k ? melody : drums)).pop();
    return tr.outs[0].gain.at(origin + t) + tr.outs[1].gain.at(origin + t); };
  const near = (x, y, e = 1e-6) => Math.abs(x - y) < e;
  const GHOST = .18;

  assert(tracks.length === 2 && tracks.every(tr => tr.outs.length === 2), 'each keysound track flows continuously (one source, base + boost)');
  assert(sources.filter(x => x.dur !== undefined).length === 0, 'no cut-up slices — the sound never shifts off the backing’s clock');
  assert(near(level(0, .5), 1) && near(level(0, 2.5), 1), 'drums between notes play at full, on the backing’s clock');
  assert(near(level(0, 1.2), GHOST) && near(level(0, 4.2), GHOST), 'inside note windows the drums are quiet until hit');
  assert(near(level(1, 2.5), GHOST) && near(level(1, 1.2), 1), 'each track quiets only its own windows');
  assert(near(level(0, 6.05), 1), 'a quiet window (synth hit) does not quiet anything');

  go(.95); Snd.keyHit(win[0], undefined, 'hit');
  for (let t = .99; t < 1.01; t += .0005) assert(near(level(0, t), 1, 1e-6), 'an early hit keeps the drum at full straight through the window start (no dip) at ' + t.toFixed(4));
  assert(near(level(0, 1.49), 1), '…and holds it to the next drum');
  assert(level(0, 1.55) < 1 && level(0, 1.55) > GHOST && near(level(0, 1.63), GHOST), 'if the next drum is not hit yet, it eases down (0.12s) — no hard cut');

  go(1.53); Snd.keyHit(win[1], undefined, 'hit');
  const at153 = level(0, 1.53);
  assert(at153 > .7 && near(level(0, 1.535), 1), 'a late hit picks up from where the sound is and rises right away (continuous, never shifted)');
  assert(near(level(0, 1.99), 1) && near(level(0, 2.01), 1, .02), 'held to the end of its window, then the track is full again');

  go(2.1); Snd.keyHit(win[4], undefined, 'hit');
  assert(near(level(1, 2.19), 1) && near(level(1, 2.2), 1) && near(level(1, 2.3), 1) && near(level(1, 2.85), GHOST, .01) === false,
    'hitting a melody note keeps the melody at full through its window (on the beat)');

  go(2.9); Snd.keyHit(win[2], 3, 'auto');
  assert(near(level(0, 2.99), 1) && near(level(0, 3.01), 1), 'the auto lane is full on the beat');

  const before = sources.length;
  go(3.9); Snd.keyHit(win[3], undefined, 'preview');
  assert(sources.length === before && near(level(0, 4.2), GHOST), 'an empty press adds nothing (the track is already flowing)');

  go(3.95); Snd.pause();
  go(20); Snd.resumeFrom(backing, 0);                 /* 곡 3.95초 = ctx 30 */
  assert(near(level(0, 4.2, 30 - 3.95), GHOST), 'after resume the note windows are quiet until hit');
  assert(!/keyMiss/.test(html), 'a miss simply stays quiet — nothing else to switch');

  /* 흐름을 타는 동안: 다가오는 구간의 첫소리를 박자에 맞춰 먼저 열어 둔다 */
  const o2 = 30 - 3.95, go2 = t => { ctx.currentTime = o2 + t; };
  go2(4.9); Snd.keyArm(win[6]);
  for (let t = 4.99; t < 5.08; t += .005) assert(near(level(1, t, o2), 1), 'an armed note starts at full exactly on the beat (no dip) at ' + t.toFixed(3));
  assert(near(level(1, 5.2, o2), GHOST), '…and eases to quiet if it is not hit');
  go2(6.9); Snd.keyArm(win[7]);
  go2(7.05); Snd.keyHit(win[7], undefined, 'hit');
  for (let t = 6.99; t < 7.59; t += .01) assert(near(level(1, t, o2), 1), 'a late hit inside the grace keeps it at full — on time and unbroken at ' + t.toFixed(2));
  assert(/groove = P\.combo > 0 \|\| P\.counts\.MISS === 0/.test(html) && /if \(groove && !w\.played && !w\.quiet\) Snd\.keyArm\(w\)/.test(html),
    'the game arms upcoming notes only while the player is in the groove (a miss stops it until the next hit)');

  /* 합성 타격음도 같은 규칙: 일찍 치면 박자에 예약, 늦으면 지금 */
  const synth = [];
  const origCreate = FakeCtx.prototype.createBufferSource;
  FakeCtx.prototype.createBufferSource = function () {
    const n = origCreate.call(this), ctx2 = this;
    n.start = function (when) { if (this.buffer !== drums && this.buffer !== backing) synth.push({ when: (when || ctx2.currentTime) - 30 + 3.95, at: ctx2.currentTime }); };
    return n;
  };
  Snd.setSfx(true);
  go(20 - 3.95 + 5.0 - .05); Snd.hit('snare', 5.0);    /* 곡 5.0초 노트를 0.05초 일찍 */
  assert(Math.abs(synth[synth.length - 1].when - 5.0) < 1e-6, 'an early synth hit is scheduled on the beat');
  go(20 - 3.95 + 5.2 + .03); Snd.hit('snare', 5.2);    /* 0.03초 늦게 */
  assert(Math.abs(synth[synth.length - 1].when - 5.23) < 1e-6, 'a late synth hit plays right away');
  FakeCtx.prototype.createBufferSource = origCreate;
}

console.log('PASS: keysound tracks (continuous, never shifted; quiet until hit, full on the beat or from a late hit, ease down if the next is missed), keysound windows (real attack, chords, caps, no overlap), game wiring, ' + withStems + ' songs with stems');
