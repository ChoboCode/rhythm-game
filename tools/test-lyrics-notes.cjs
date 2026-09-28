/* 가사: 모든 줄에 단어 시각(황금빛 채우기가 노래를 따라가게), 줄이 한순간에 끝나지 않음.
   채보: 가사가 들릴 때 노트가 온다(단어 시작 ±0.07초 안에 노트) — 쉬움 50%·보통 75%·어려움 90% 이상. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const songs = JSON.parse(fs.readFileSync(path.join(root, 'songs', 'songs.json'), 'utf8'));
const MIN_COVER = { easy: .5, normal: .75, hard: .9 };   /* 쉬움은 1박·보통은 ½박 간격이라 빠르게 부르는 단어는 빠질 수 있다 */
let checked = 0;
for (const song of songs) {
  if (!song.lyrics) continue;
  const lyr = JSON.parse(fs.readFileSync(path.join(root, 'songs', song.lyrics), 'utf8'));
  const lines = lyr.lines.filter(l => (l.text || '').trim());
  assert.equal(lyr.timing, 'vocal-aligned-v2', song.title + ': lyrics aligned to the vocals (tools/align-lyrics.py)');
  let prev = -Infinity;
  for (const l of lines) {
    assert(Array.isArray(l.words) && l.words.length, song.title + ': every line has word times — "' + l.text + '"');
    assert.equal(l.words.map(w => w.text).join(' '), l.text.split(/\s+/).join(' '), song.title + ': words spell the line');
    assert(l.t >= prev, song.title + ': lines in order at ' + l.t);
    assert(l.end > l.t, song.title + ': line ends after it starts');
    assert(l.end - l.t >= .1, song.title + ': not a flash-by line — "' + l.text + '"');
    let wp = -Infinity;
    for (const w of l.words) {
      assert(w.t >= wp && w.end > w.t, song.title + ': word times in order — ' + w.text);
      wp = w.t;
    }
    prev = l.t;
  }
  /* 글자 수에 비해 짧은 줄은 예전 자료부터 몰려 있던 것만 조금(곡의 20% 이하 — 반복 후렴이 몰려 있어 받아쓰기로도 자리를 못 가린 줄) */
  const isShort = l => l.end - l.t < Math.min(.6, .06 * l.text.replace(/\s/g, '').length);
  const short = lines.filter(isShort).length;
  assert(short <= Math.max(2, lines.length * .2), song.title + ': too many flash-by lines (' + short + ')');
  /* 몰린 줄의 단어(0.3초에 4~5단어)는 어느 간격으로도 다 칠 수 없으니 뺀다 */
  const words = lines.filter(l => !isShort(l)).flatMap(l => l.words.map(w => w.t));
  for (const lv of ['easy', 'normal', 'hard']) {
    const ts = [...new Set(JSON.parse(fs.readFileSync(path.join(root, 'songs', song.charts[lv]), 'utf8')).notes.map(n => n.t))].sort((a, b) => a - b);
    let hit = 0, j = 0;
    for (const w of words) {
      while (j < ts.length && ts[j] < w - .07) j++;
      if (j < ts.length && Math.abs(ts[j] - w) <= .07) hit++;
    }
    assert(hit / words.length >= MIN_COVER[lv], song.title + ' ' + lv + ': a note comes with the lyrics (' + (hit / words.length * 100).toFixed(0) + '%)');
  }
  checked++;
}
console.log('PASS: ' + checked + ' songs — lyrics aligned (every line has word times, no flash-by lines), notes come with the lyrics');
