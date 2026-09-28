/* 곡 끝: 음원 끝의 무음·거의 안 들리는 꼬리를 기다리지 않고, 귀에 들리는 소리 끝과 마지막 노트 판정 중 늦은 쪽 + 0.8초에
   결과 화면(마지막 0.5초는 음악을 줄인다).
   약한 기기(메모리 2GB 이하라고 알려 주는 기기)는 키음 세 트랙 대신 원곡만 읽는다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const a = html.indexOf('  function soundEndOf(buffer) {');
const b = html.indexOf('\n  }', a) + 4;
assert(a > 0, 'soundEndOf found');
const soundEndOf = new Function(html.slice(a, b) + 'return soundEndOf;')();

/* 가짜 음원: 3초 중 앞 2초만 소리(오른쪽 채널은 2.5초까지), 뒤는 무음 */
const sr = 44100;
const buffer = (ends) => {
  const chans = ends.map(end => { const d = new Float32Array(sr * 3); for (let i = 0; i < end * sr; i++) d[i] = Math.sin(i / 10) * .3; return d; });
  return { sampleRate: sr, length: sr * 3, numberOfChannels: chans.length, getChannelData: c => chans[c] };
};
assert(Math.abs(soundEndOf(buffer([2])) - 2) < .1 + 1e-9, 'finds where the sound ends, not the file end');
assert(Math.abs(soundEndOf(buffer([2, 2.5])) - 2.5) < .1 + 1e-9, 'the latest channel counts');
assert.equal(soundEndOf(buffer([0])), 0, 'all silence → 0');
assert.equal(soundEndOf(null), 0, 'no buffer → 0');
{
  /* 큰 소리보다 30dB 넘게 작은 꼬리는 무음으로 본다 */
  const b2 = buffer([2]);
  const d = b2.getChannelData(0);
  for (let i = 2 * sr; i < 3 * sr; i++) d[i] = Math.sin(i / 10) * .002;
  assert(Math.abs(soundEndOf(b2) - 2) < .1 + 1e-9, 'a tail 30 dB below the loud part counts as silence (it cannot really be heard)');
}

/* 게임 연결 */
assert(/const soundEnd = Math\.max\.apply\(null, \[S\.buffer\]\.concat\(S\.keyTracks \|\| \[\]\)\.map\(soundEndOf\)\);/.test(html),
  'the end is measured over the backing and every keysound track');
assert(/P\.endAt = Math\.min\(fullLength \+ \.3, Math\.max\(soundEnd, lastNoteEnd \+ JUDGE\[JUDGE\.length - 1\]\.win\) \+ \.8\);/.test(html),
  'results 0.8 s after the later of the audible end and the last judgement');
assert(/P\.fadeAt = P\.endAt - \.5;/.test(html) && /Snd\.fadeOut\(P\.endAt - P\.fadeAt\)/.test(html), 'the music fades over the last 0.5 s instead of being cut');
assert(/prefs\.hitSnd && !lowMemoryDevice\(\)/.test(html), 'low-memory devices read only the original track');
const l0 = html.indexOf('  function lowMemoryDevice() {');
const lowMemoryDevice = gb => new Function('navigator', html.slice(l0, html.indexOf('\n  }', l0) + 4) + 'return lowMemoryDevice();')({ deviceMemory: gb });
assert.equal(lowMemoryDevice(2), true, '2 GB → original only');
assert.equal(lowMemoryDevice(1), true, '1 GB → original only');
assert.equal(lowMemoryDevice(4), false, '4 GB → keysound tracks');
assert.equal(lowMemoryDevice(undefined), false, 'browsers that do not tell → unchanged');
console.log('PASS: song end (real sound end, not trailing silence), low-memory devices use the original track');
