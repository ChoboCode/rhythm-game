/* 로딩 게이지: 곡 준비(받기 0~85% → 풀기 85~97% → 채보)와 첫 실행 화면(곡 목록 → 표지 → 글꼴)이 실제 진행을 보여 준다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8').replace(/\r\n/g, '\n');
const a = html.indexOf('  function downloadMeter(count, tell) {');
const b = html.indexOf('\n  }\n', a) + 4;
assert(a > 0 && b > a, 'downloadMeter found');
const downloadMeter = new Function(html.slice(a, b).replace(/\r/g, '') + 'return downloadMeter;')();

const seen = [];
const meter = downloadMeter(2, (v, msg) => seen.push([+v.toFixed(3), msg]));
const f0 = meter.file(0), f1 = meter.file(1);
f0(1048576, 4194304, 'download');                 /* 1MB / 4MB */
f1(0, 4194304, 'download');
assert.deepEqual(seen[seen.length - 1], [.106, '음원 받는 중 1.0 / 8.0MB'], 'bytes received over the total, scaled to 85%');
f0(4194304, 4194304, 'decode');
f1(4194304, 4194304, 'decode');
assert.deepEqual(seen[seen.length - 1], [.85, '음원 푸는 중 (0/2)'], 'all received → 85%, now decoding');
meter.decoded();
assert.deepEqual(seen[seen.length - 1], [.91, '음원 푸는 중 (1/2)'], 'each decoded file moves the bar');
meter.decoded();
assert.equal(seen[seen.length - 1][0], .97, 'all decoded → 97% (the rest is the chart)');
for (let i = 1; i < seen.length; i++) assert(seen[i][0] >= seen[i - 1][0], 'the bar never goes backwards');

/* 크기를 모르는 서버(Content-Length 없음)는 끝난 파일 수로 */
const unknown = [];
const m2 = downloadMeter(2, (v, msg) => unknown.push([+v.toFixed(3), msg]));
m2.file(0)(500000, 0, 'download');
assert.deepEqual(unknown[0], [0, '음원 받는 중 0.5MB'], 'unknown size: shows bytes, bar waits for whole files');
m2.file(0)(1000000, 1000000, 'decode');
assert.equal(unknown[1][0], .425, 'one of two files received → half of 85%');

/* 연결 */
assert(/loadPlayAudio\(song, function \(v, msg\) \{\s*if \(token === S\.prepareToken\) setProgress\(v, msg\);/.test(html), 'song preparation shows the loading progress');
assert(/Snd\.loadUrl\('songs\/' \+ f, meter\.file\(i\)\)/.test(html), 'each keysound file reports its bytes');
assert(/const reader = r\.body\.getReader\(\)/.test(html), 'downloads are read as a stream to count bytes');
assert(/id="anaBarTrack" role="progressbar"/.test(html) && /id="startupTrack" role="progressbar"/.test(html), 'both gauges are progress bars for screen readers');
assert(/setStartupProgress\(\.2\);/.test(html) && /setStartupProgress\(\.2 \+ \.7 \* done \/ images\.length\)/.test(html) &&
  /setStartupProgress\(\.92\);/.test(html) && /setStartupProgress\(1\);/.test(html), 'startup: list 20% → covers up to 90% → fonts → 100%');
console.log('PASS: loading gauges (bytes → decode → chart, unknown sizes, never backwards; startup steps; progressbar roles)');
